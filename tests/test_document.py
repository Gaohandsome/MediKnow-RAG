"""文档上传、解析、向量入库、块编辑删除的端到端测试。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import retrieval
from app.services.vector_store import get_vector_store
from tests.conftest import API

SAMPLE_MD = """# 社区获得性肺炎诊疗规范

## 一、诊断依据
影像学新出现浸润影，伴咳嗽、咳痰或发热，排除肺结核等疾病后可临床诊断。

## 二、严重程度评估
CURB-65 评分 0~1 分可门诊治疗，2 分建议住院治疗，3 分及以上评估入住重症监护病房。

## 三、经验性抗菌治疗
1. 门诊无基础疾病患者：阿莫西林 500 mg 口服，每 8 小时一次。
2. 住院非重症患者：头孢曲松 1 g 静脉滴注，每日一次。

## 四、疗程与随访
疗程一般 5~7 天，出院后 7~10 天至呼吸内科门诊复诊。
"""


def _upload(client: TestClient, headers: dict, kb_id: int, filename: str, content: bytes, **params):
    data = {"chunk_size": 200, "chunk_overlap": 40, "retrieval_mode": "hybrid", **params}
    return client.post(
        f"{API}/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": (filename, content, "text/markdown")},
        data={key: str(value) for key, value in data.items()},
    )


def _wait_done(client: TestClient, headers: dict, doc_id: int, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"{API}/documents/{doc_id}", headers=headers).json()["data"]
        if detail["status"] in {"completed", "failed"}:
            return detail
        time.sleep(0.5)
    raise AssertionError("文档解析超时")


@pytest.mark.integration
def test_upload_markdown_parsed_into_milvus(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "肺炎诊疗规范.md", SAMPLE_MD.encode("utf-8")
    )
    assert response.status_code == 200, response.text
    doc = response.json()["data"]

    detail = _wait_done(client, new_user["headers"], doc["id"])
    assert detail["status"] == "completed", detail
    assert detail["chunk_count"] > 0
    assert detail["char_count"] > 0

    # 向量库中应写入相同数量的实体（共享集合按 kb_id 统计）
    store = get_vector_store()
    collection = settings.milvus_collection_prefix
    kb_expr = f"kb_id == {knowledge_base['id']}"
    assert store.has_collection(collection)
    assert store.count(collection, kb_expr) == detail["chunk_count"]

    # 块内容可查询：章节级切分后，子块只带本章节正文（文档标题留在父块里，
    # 否则同一文档的子块语义会趋同），所以校验章节正文而不是标题
    chunks = client.get(f"{API}/documents/{doc['id']}/chunks", headers=new_user["headers"]).json()["data"]
    assert chunks["total"] == detail["chunk_count"]
    joined = "\n".join(item["content"] for item in chunks["items"])
    assert "阿莫西林" in joined and "CURB-65" in joined
    assert len(chunks["items"]) >= 3, "按 ## 章节切分后不应只剩一个大块"


@pytest.mark.integration
def test_retrieval_finds_uploaded_content(client: TestClient, db, new_user: dict, knowledge_base: dict):
    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "肺炎诊疗规范.md", SAMPLE_MD.encode("utf-8")
    )
    doc = response.json()["data"]
    _wait_done(client, new_user["headers"], doc["id"])

    user_id = client.get(f"{API}/auth/me", headers=new_user["headers"]).json()["data"]["id"]
    contexts = retrieval.retrieve(
        db,
        query="门诊患者首选的抗菌药物是什么？",
        kb_ids=[knowledge_base["id"]],
        user_id=user_id,
        top_k=3,
        use_rerank=False,
    )
    assert contexts, "检索结果为空"
    assert any("阿莫西林" in item["content"] or "抗菌" in item["content"] for item in contexts)


@pytest.mark.integration
def test_chunk_update_and_delete_syncs_milvus(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "肺炎诊疗规范.md", SAMPLE_MD.encode("utf-8")
    )
    doc = response.json()["data"]
    detail = _wait_done(client, new_user["headers"], doc["id"])
    store = get_vector_store()
    collection = settings.milvus_collection_prefix
    kb_expr = f"kb_id == {knowledge_base['id']}"
    before = store.count(collection, kb_expr)
    assert before == detail["chunk_count"]

    chunks = client.get(f"{API}/documents/{doc['id']}/chunks", headers=new_user["headers"]).json()["data"]
    target = chunks["items"][0]

    updated = client.patch(
        f"{API}/chunks/{target['id']}",
        headers=new_user["headers"],
        json={"content": "门诊无基础疾病患者：阿莫西林 500 mg 口服，每 8 小时一次。"},
    )
    assert updated.status_code == 200
    assert "每 8 小时一次" in updated.json()["data"]["content"]
    assert store.count(collection, kb_expr) == before, "更新块后向量数量应保持不变"

    removed = client.delete(f"{API}/chunks/{target['id']}", headers=new_user["headers"])
    assert removed.status_code == 200
    assert store.count(collection, kb_expr) == before - 1


@pytest.mark.integration
def test_delete_document_clears_vectors(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "肺炎诊疗规范.md", SAMPLE_MD.encode("utf-8")
    )
    doc = response.json()["data"]
    _wait_done(client, new_user["headers"], doc["id"])

    store = get_vector_store()
    collection = settings.milvus_collection_prefix
    kb_expr = f"kb_id == {knowledge_base['id']}"
    assert store.count(collection, kb_expr) > 0

    assert client.delete(f"{API}/documents/{doc['id']}", headers=new_user["headers"]).status_code == 200
    assert store.count(collection, kb_expr) == 0

    detail = client.get(f"{API}/knowledge-bases/{knowledge_base['id']}", headers=new_user["headers"]).json()["data"]
    assert detail["document_count"] == 0
    assert detail["chunk_count"] == 0


def test_upload_rejects_unsupported_type(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(client, new_user["headers"], knowledge_base["id"], "病毒.exe", b"binary")
    assert response.status_code == 400
    assert "不支持" in response.json()["message"]


def test_upload_rejects_empty_file(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(client, new_user["headers"], knowledge_base["id"], "空.md", b"")
    assert response.status_code == 400


@pytest.mark.integration
def test_reindex_document(client: TestClient, new_user: dict, knowledge_base: dict):
    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "肺炎诊疗规范.md", SAMPLE_MD.encode("utf-8")
    )
    doc = response.json()["data"]
    first = _wait_done(client, new_user["headers"], doc["id"])

    reindex = client.post(f"{API}/documents/{doc['id']}/reindex", headers=new_user["headers"])
    assert reindex.status_code == 200
    second = reindex.json()["data"]
    assert second["status"] == "completed"
    assert second["chunk_count"] == first["chunk_count"]

    store = get_vector_store()
    collection = settings.milvus_collection_prefix
    assert store.count(collection, f"kb_id == {knowledge_base['id']}") == first["chunk_count"]


@pytest.mark.integration
def test_concurrent_ingest_is_serialized(client: TestClient, db, new_user: dict, knowledge_base: dict):
    """并发解析多个文档时不应触发数据库死锁（回归：曾出现 1213 Deadlock）。"""
    import threading

    from app.models.document import Document
    from app.services.document_service import ingest_document

    user_id = client.get(f"{API}/auth/me", headers=new_user["headers"]).json()["data"]["id"]
    target_dir = Path(settings.upload_path) / f"kb_{knowledge_base['id']}"
    target_dir.mkdir(parents=True, exist_ok=True)

    doc_ids = []
    for index in range(3):
        path = target_dir / f"concurrent_{index}.md"
        path.write_text(SAMPLE_MD + f"\n\n附注 {index}", encoding="utf-8")
        document = Document(
            knowledge_base_id=knowledge_base["id"],
            user_id=user_id,
            filename=f"并发文档{index}.md",
            stored_path=str(path),
            file_type="Markdown",
            file_size=path.stat().st_size,
            status="pending",
        )
        db.add(document)
        db.flush()
        doc_ids.append(document.id)
    db.commit()

    threads = [threading.Thread(target=ingest_document, args=(doc_id,)) for doc_id in doc_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)

    for doc_id in doc_ids:
        detail = client.get(f"{API}/documents/{doc_id}", headers=new_user["headers"]).json()["data"]
        assert detail["status"] == "completed", detail["error_message"]
        assert detail["chunk_count"] > 0


@pytest.mark.integration
def test_upload_pdf_file(client: TestClient, new_user: dict, knowledge_base: dict, tmp_path: Path):
    """PDF 解析链路：用 reportlab 生成一个最小 PDF。"""
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("未安装 reportlab，跳过 PDF 解析测试")

    tmp = tmp_path / "sample_report.pdf"
    c = canvas.Canvas(str(tmp))
    c.drawString(80, 760, "Community acquired pneumonia: CURB-65 score guides admission.")
    c.drawString(80, 740, "Outpatients without comorbidity receive amoxicillin 500 mg q8h.")
    c.save()

    response = _upload(
        client, new_user["headers"], knowledge_base["id"], "vendor_guide.pdf", tmp.read_bytes(),
        retrieval_mode="dense",
    )
    assert response.status_code == 200
    detail = _wait_done(client, new_user["headers"], response.json()["data"]["id"])
    assert detail["status"] == "completed"
    assert detail["chunk_count"] > 0
