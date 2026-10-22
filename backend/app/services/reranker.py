"""bge-reranker-v2-m3 重排。"""
from __future__ import annotations

import threading

from loguru import logger

from app.core.config import settings


class BGEReranker:
    """交叉编码器重排，懒加载。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            path = settings.rerank_model_path
            logger.info(f"正在加载 bge-reranker 重排模型：{path}")
            self._tokenizer = AutoTokenizer.from_pretrained(path)
            self._model = AutoModelForSequenceClassification.from_pretrained(path)
            self._model.eval()
            device = settings.embedding_device or "cpu"
            if device.startswith("cuda") and torch.cuda.is_available():
                self._device = device
            self._model.to(self._device)
            logger.info("bge-reranker 重排模型加载完成")

    def score(self, query: str, passages: list[str], batch_size: int = 4) -> list[float]:
        """给每个候选段落打分，值域 (0,1)。"""
        if not passages:
            return []
        self._load()
        import torch

        scores: list[float] = []
        with torch.no_grad():
            for start in range(0, len(passages), batch_size):
                batch = [[query, passage] for passage in passages[start : start + batch_size]]
                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                inputs = {key: value.to(self._device) for key, value in inputs.items()}
                logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
                scores.extend(torch.sigmoid(logits).cpu().tolist())
        return scores


_reranker: BGEReranker | None = None
_reranker_lock = threading.Lock()


def get_reranker() -> BGEReranker:
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = BGEReranker()
    return _reranker
