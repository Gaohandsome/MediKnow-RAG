"""轻量 BM25 + 覆盖率：判定「这次提问是否就是缓存里的那个问题」。

为什么不用 jieba / rank_bm25：
- 依赖越少越好（本机 pip 代理时常不可用），中文二元切分不依赖词典；
- 原始 BM25 分数无上界，没法直接和 0.8 这种阈值比。

两套分数各司其职：
- `bm25()`   —— 标准 BM25（tf 饱和 + 文档长度归一化），用于候选排序；
- `scores()` —— **对称覆盖率**（0~1），用于阈值判定：
      max( query 有多少被文档覆盖 , 文档有多少被 query 覆盖 )
  取双向最大值是为了吃掉「请问／吗／？／多打几个字」这类噪声：
  新问题把旧问题整句包含时，反向覆盖率是 1.0，可以直接命中；
  而换个说法的同义问句两个方向都偏低，会自然落到向量检索，医疗场景更安全。
"""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-z0-9]+")
_ZH_RE = re.compile(r"[\u4e00-\u9fa5]")

# 高频虚词，参与计算只会稀释区分度
_STOPWORDS = {
    "什么", "怎么", "如何", "为什", "么样", "哪些", "哪个", "多少", "是否",
    "可以", "需要", "应该", "以及", "还有", "请问", "一下", "这个", "那个",
    "的", "了", "是", "在", "有", "和", "与", "吗", "呢", "啊", "呀",
}


def tokenize(text: str) -> list[str]:
    """英文/数字按词、中文按「单字 + 二元组」切分。

    单字保证改写问句（多字少字）仍有重合，二元组保证词序与搭配的区分度。
    """
    lowered = (text or "").lower()
    tokens = _WORD_RE.findall(lowered)
    chinese = "".join(_ZH_RE.findall(lowered))
    tokens.extend(chinese)
    tokens.extend(chinese[i : i + 2] for i in range(len(chinese) - 1))
    return [token for token in tokens if token not in _STOPWORDS]


class BM25:
    """语料级 BM25 索引，同时提供归一化覆盖率。"""

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.doc_count = len(corpus_tokens)
        self.doc_lengths = [len(tokens) for tokens in corpus_tokens]
        self.avg_length = (sum(self.doc_lengths) / self.doc_count) if self.doc_count else 0.0

        self.doc_freqs: Counter[str] = Counter()
        for tokens in corpus_tokens:
            self.doc_freqs.update(set(tokens))

    def idf(self, token: str) -> float:
        df = self.doc_freqs.get(token, 0)
        # 未登录词视为最稀有，权重最高；加 1 保证非负
        return math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)

    def _saturation(self, tf: int, doc_length: int) -> float:
        """词频饱和分，值域 0~1（tf=1 且长度等于均值时为 0.4）。"""
        if tf <= 0:
            return 0.0
        norm = self.k1 * (
            1 - self.b + self.b * (doc_length / self.avg_length if self.avg_length else 1.0)
        )
        return (tf * (self.k1 + 1) / (tf + norm)) / (self.k1 + 1)

    def bm25(self, query_tokens: list[str]) -> list[float]:
        """标准 BM25 原始分（无界），可选用于排序。"""
        unique = list(dict.fromkeys(query_tokens))
        results: list[float] = []
        for index, tokens in enumerate(self.corpus):
            counts = Counter(tokens)
            results.append(
                sum(
                    self.idf(token) * self._saturation(counts.get(token, 0), self.doc_lengths[index])
                    for token in unique
                )
            )
        return results

    def _weighted_coverage(self, source: list[str], target: set[str]) -> float:
        unique = list(dict.fromkeys(source))
        weights = {token: self.idf(token) for token in unique}
        total = sum(weights.values()) or 1.0
        return sum(weight for token, weight in weights.items() if token in target) / total

    def scores(self, query_tokens: list[str]) -> list[float]:
        """对称覆盖率（0~1）：越接近 1 越说明两句话是同一个问题。"""
        if not self.corpus or not query_tokens:
            return [0.0] * self.doc_count
        query_set = set(query_tokens)
        results: list[float] = []
        for tokens in self.corpus:
            doc_set = set(tokens)
            forward = self._weighted_coverage(query_tokens, doc_set)
            backward = self._weighted_coverage(tokens, query_set)
            results.append(max(forward, backward))
        return results
