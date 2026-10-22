"""bge-m3 向量化：同时产出稠密向量与稀疏（词权重）向量，供稠密/混合检索使用。"""
from __future__ import annotations

import threading
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.core.exceptions import BizError


class BGEM3Embedder:
    """bge-m3 推理封装（CPU 亦可运行）。模型懒加载，全局单例。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None
        self._sparse_linear = None
        self._device = settings.embedding_device or "cpu"
        self.model_path = settings.embedding_model_path
        self.max_length = settings.embedding_max_length

    @property
    def dim(self) -> int:
        return settings.embedding_dim

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModel, AutoTokenizer

            path = Path(self.model_path)
            if not path.exists():
                raise BizError(f"向量模型路径不存在：{path}，请检查 .env 中的 EMBEDDING_MODEL_PATH")

            logger.info(f"正在加载 bge-m3 向量模型：{path}（device={self._device}）")
            self._tokenizer = AutoTokenizer.from_pretrained(str(path))
            self._model = AutoModel.from_pretrained(str(path))
            self._model.eval()
            if self._device.startswith("cuda") and torch.cuda.is_available():
                self._model.to(self._device)
            else:
                self._device = "cpu"
                self._model.to("cpu")

            self._sparse_linear = self._load_sparse_linear(path, torch)
            logger.info("bge-m3 向量模型加载完成")

    @staticmethod
    def _load_sparse_linear(path: Path, torch):  # noqa: ANN001
        """加载稀疏权重层（sparse_linear.pt）。"""
        import torch.nn as nn

        linear = nn.Linear(settings.embedding_dim, 1, bias=False)
        weight_file = path / "sparse_linear.pt"
        if weight_file.exists():
            state = torch.load(str(weight_file), map_location="cpu", weights_only=False)
            if isinstance(state, dict) and "weight" in state:
                state = state["weight"]
            linear.weight.data = state.to(torch.float32)
        else:
            logger.warning("未找到 sparse_linear.pt，稀疏向量退化为按 token 均匀权重")
            linear.weight.data = torch.ones(1, settings.embedding_dim) / settings.embedding_dim
        linear.eval()
        return linear

    def encode(self, texts: list[str], batch_size: int | None = None) -> tuple[list[list[float]], list[dict[int, float]]]:
        """批量编码，返回 (稠密向量列表, 稀疏向量列表)。"""
        if not texts:
            return [], []
        self._load()
        import torch

        batch_size = batch_size or settings.embedding_batch_size
        dense_vectors: list[list[float]] = []
        sparse_vectors: list[dict[int, float]] = []
        special_ids = {
            self._tokenizer.cls_token_id,
            self._tokenizer.sep_token_id,
            self._tokenizer.pad_token_id,
            self._tokenizer.mask_token_id,
            self._tokenizer.unk_token_id,
        }

        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                inputs = {key: value.to(self._device) for key, value in inputs.items()}
                outputs = self._model(**inputs)
                hidden = outputs.last_hidden_state

                # 稠密向量：CLS 池化 + L2 归一化
                cls_vector = hidden[:, 0]
                cls_vector = torch.nn.functional.normalize(cls_vector.float(), p=2, dim=-1)
                dense_vectors.extend(cls_vector.cpu().tolist())

                # 稀疏向量：每个 token 的词权重，取同 token 的最大值
                mask = inputs["attention_mask"].float()
                token_weights = torch.relu(self._sparse_linear(hidden).squeeze(-1)) * mask
                token_ids = inputs["input_ids"]
                for row in range(len(batch)):
                    ids = token_ids[row][mask[row] > 0].cpu().tolist()
                    weights = token_weights[row][mask[row] > 0].cpu().tolist()
                    sparse: dict[int, float] = {}
                    for token_id, weight in zip(ids, weights):
                        if weight <= 0 or token_id in special_ids:
                            continue
                        if weight > sparse.get(token_id, 0.0):
                            sparse[token_id] = float(weight)
                    sparse_vectors.append(sparse)

        return dense_vectors, sparse_vectors

    def encode_query(self, query: str) -> tuple[list[float], dict[int, float]]:
        dense, sparse = self.encode([query])
        return dense[0], sparse[0]


_embedder: BGEM3Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> BGEM3Embedder:
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = BGEM3Embedder()
    return _embedder
