"""Milvus 向量库封装：按知识库维度建 collection，支持稠密检索与稀疏+稠密混合检索。"""
from __future__ import annotations

import threading
from typing import Any

from loguru import logger
from pymilvus import (
    AnnSearchRequest,
    DataType,
    MilvusClient,
    RRFRanker,
)

from app.core.config import settings
from app.core.exceptions import BizError

_TEXT_MAX_LENGTH = 65535

# 固定 schema 的字段；其余键靠动态字段（$meta）承载
_SCHEMA_FIELDS = {
    "id",
    "kb_id",
    "document_id",
    "chunk_id",
    "page",
    "text",
    "parent_id",
    "parent_content",
    "dense",
    "sparse",
}


class MilvusVectorStore:
    """Milvus 客户端封装（线程安全懒加载）。"""

    def __init__(self) -> None:
        self._client: MilvusClient | None = None
        self._lock = threading.Lock()
        self._loaded: set[str] = set()

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    logger.info(f"连接 Milvus：{settings.milvus_uri}（database={settings.milvus_database}）")
                    kwargs: dict[str, Any] = {"uri": settings.milvus_uri}
                    if settings.milvus_token:
                        kwargs["token"] = settings.milvus_token
                    if settings.milvus_database:
                        kwargs["db_name"] = settings.milvus_database
                    self._client = MilvusClient(**kwargs)
        return self._client

    def collection_name(self, knowledge_base_id: int | None = None) -> str:
        """所有知识库共用同一个 Milvus 集合，靠 kb_id 字段隔离。

        `MILVUS_COLLECTION_PREFIX` 即为集合名本身（如 rag_1019），
        不再拼接知识库 ID，避免每个知识库生成一个集合。
        """
        return settings.milvus_collection_prefix

    @staticmethod
    def _kb_expr(kb_ids: list[int] | None) -> str:
        """构造知识库过滤表达式；为空时返回空串（不过滤）。"""
        if not kb_ids:
            return ""
        ids = ",".join(str(int(item)) for item in kb_ids)
        return f"kb_id in [{ids}]"

    def has_collection(self, name: str) -> bool:
        return self.client.has_collection(collection_name=name)

    def ensure_collection(self, name: str, retrieval_mode: str = "hybrid", dim: int | None = None) -> None:
        """集合不存在时创建；已存在则复用。

        共享集合统一带 dense + sparse 两个向量字段：写入时总是写稀疏向量，
        检索时由各知识库自己的 retrieval_mode 决定走混合检索还是纯稠密检索。

        父块（`parent_id` / `parent_content`）建**真实字段**而不是塞动态字段：
        - 在 Attu/Atlas 的「数据」页能直接看到列，便于排查；
        - `parent_id` 可建标量索引，后续能按父块做过滤查询。
        `images` 这类只有展示用途的仍走动态字段（`$meta`）。
        """
        if self.has_collection(name):
            return
        dim = dim or settings.embedding_dim
        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="kb_id", datatype=DataType.INT64)
        schema.add_field(field_name="document_id", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64)
        schema.add_field(field_name="page", datatype=DataType.INT64)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=_TEXT_MAX_LENGTH)
        schema.add_field(field_name="parent_id", datatype=DataType.INT64)
        schema.add_field(
            field_name="parent_content", datatype=DataType.VARCHAR, max_length=_TEXT_MAX_LENGTH
        )
        schema.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(
            field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP"
        )
        # 父块 id 建标量索引：同父块的兄弟块查询/统计会走它
        index_params.add_index(field_name="parent_id", index_type="INVERTED")

        self.client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        logger.info(f"创建 Milvus 集合：{name}（共享集合, mode={retrieval_mode}, dim={dim}）")

    def supports_dynamic_field(self, name: str) -> bool:
        """集合是否开启动态字段（老集合没开，写额外字段会报错）。"""
        try:
            info = self.client.describe_collection(collection_name=name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取集合信息失败：{name} - {exc}")
            return False
        return bool(info.get("enable_dynamic_field"))

    def insert(
        self,
        name: str,
        rows: list[dict[str, Any]],
    ) -> list[int]:
        """写入向量，返回 Milvus 主键列表。

        开启动态字段时，row 里多出来的键（如 `images`）会落进 `$meta`；
        老集合没开则先剔除，避免整批写入失败。
        """
        if not rows:
            return []
        if not self.supports_dynamic_field(name):
            rows = [{k: v for k, v in row.items() if k in _SCHEMA_FIELDS} for row in rows]
        result = self.client.insert(collection_name=name, data=rows)
        ids = [int(pk) for pk in result.get("ids", [])]
        self.client.flush(collection_name=name)
        logger.info(f"向量写入完成：collection={name}, rows={len(rows)}")
        return ids

    def delete_by_ids(self, name: str, ids: list[int]) -> None:
        if not ids:
            return
        self.client.delete(collection_name=name, ids=ids)
        self.client.flush(collection_name=name)

    def delete_by_filter(self, name: str, expr: str) -> None:
        self.client.delete(collection_name=name, filter=expr)
        self.client.flush(collection_name=name)

    def drop_collection(self, name: str) -> None:
        if self.has_collection(name):
            self.client.drop_collection(collection_name=name)
            logger.info(f"删除 Milvus 集合：{name}")

    def count(self, name: str, expr: str = "") -> int:
        """统计集合内有效实体数（count(*) 会排除已删除实体）。

        expr 非空时按条件统计，例如 `kb_id == 12` 统计某个知识库的向量数。
        """
        if not self.has_collection(name):
            return 0
        try:
            result = self.client.query(collection_name=name, filter=expr, output_fields=["count(*)"])
            if result:
                return int(result[0].get("count(*)", 0))
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"统计 Milvus 集合失败：{name} - {exc}")
            return 0

    def max_dense_score(self, name: str, dense_vector: list[float], kb_ids: list[int] | None = None) -> float:
        """返回集合内与查询最相似片段的稠密余弦相似度（0~1），用于相关性判定。"""
        if not self.has_collection(name):
            return 0.0
        try:
            results = self.client.search(
                collection_name=name,
                data=[dense_vector],
                anns_field="dense",
                search_params={"metric_type": "COSINE"},
                limit=1,
                filter=self._kb_expr(kb_ids),
                output_fields=["chunk_id"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"计算相关度失败：{name} - {exc}")
            return 0.0
        if results and results[0]:
            return float(results[0][0].get("distance", 0.0))
        return 0.0

    def search(
        self,
        name: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float] | None = None,
        retrieval_mode: str = "hybrid",
        limit: int = 20,
        output_fields: list[str] | None = None,
        kb_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """执行检索，返回统一结构的命中列表。kb_ids 非空时只检索这些知识库。"""
        if not self.has_collection(name):
            return []
        output_fields = output_fields or [
            "chunk_id",
            "document_id",
            "page",
            "text",
            "parent_id",
            "parent_content",
        ]
        expr = self._kb_expr(kb_ids)
        try:
            if retrieval_mode == "hybrid" and sparse_vector:
                requests = [
                    AnnSearchRequest(
                        data=[dense_vector],
                        anns_field="dense",
                        param={"metric_type": "COSINE"},
                        limit=limit,
                        expr=expr or None,
                    ),
                    AnnSearchRequest(
                        data=[sparse_vector],
                        anns_field="sparse",
                        param={"metric_type": "IP"},
                        limit=limit,
                        expr=expr or None,
                    ),
                ]
                results = self.client.hybrid_search(
                    collection_name=name,
                    reqs=requests,
                    ranker=RRFRanker(60),
                    limit=limit,
                    output_fields=output_fields,
                )
            else:
                results = self.client.search(
                    collection_name=name,
                    data=[dense_vector],
                    anns_field="dense",
                    search_params={"metric_type": "COSINE"},
                    limit=limit,
                    filter=expr,
                    output_fields=output_fields,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Milvus 检索失败：{exc}")
            raise BizError(f"向量检索失败：{exc}", status_code=502) from exc

        hits: list[dict[str, Any]] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity") or {}
            hits.append(
                {
                    "chunk_id": int(entity.get("chunk_id", 0)),
                    "document_id": int(entity.get("document_id", 0)),
                    "page": int(entity.get("page", -1)),
                    "content": entity.get("text", ""),
                    # 动态字段里的副本：MySQL 拿不到时（旧数据/已删文档）用它兜底
                    "parent_id": int(entity.get("parent_id") or 0),
                    "parent_content": entity.get("parent_content") or "",
                    "score": float(hit.get("distance", 0.0)),
                }
            )
        return hits

    def hybrid_search_with_rerank(
        self,
        name: str,
        query: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float] | None = None,
        retrieval_mode: str = "hybrid",
        limit: int = 20,
        top_n: int | None = None,
        kb_ids: list[int] | None = None,
        use_rerank: bool = True,
    ) -> list[dict[str, Any]]:
        """混合检索 + 精排：一次拿到按相关性排序的候选块。

        对应问答链路中的 `VectorStore.hybrid_search_with_rerank`：
        先在共享集合里按 kb_id 过滤召回，再用 bge-reranker 精排。
        """
        hits = self.search(
            name=name,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            retrieval_mode=retrieval_mode,
            limit=limit,
            kb_ids=kb_ids,
        )
        if not hits:
            return []

        top_n = top_n or settings.rag_top_k
        if use_rerank and len(hits) > 1:
            try:
                from app.services.reranker import get_reranker

                reranker = get_reranker()
                scores = reranker.score(query, [item["content"] for item in hits])
                for item, score in zip(hits, scores):
                    item["rerank_score"] = float(score)
                hits.sort(key=lambda item: item["rerank_score"], reverse=True)
                logger.info(f"重排完成：collection={name} 候选={len(hits)}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"重排失败，回退到混合检索分数：{exc}")
        return hits[: max(top_n, 1)]


_store: MilvusVectorStore | None = None
_store_lock = threading.Lock()


def get_vector_store() -> MilvusVectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = MilvusVectorStore()
    return _store
