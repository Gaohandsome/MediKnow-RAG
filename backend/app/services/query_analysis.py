"""查询理解：意图识别 + 检索策略选择 + 查询改写。

对应流程图的右半部分（策略选择器那一层）：

    query → 意图识别(Bert分类 / LLM+prompt) → 策略选择器
          ├─ 直接检索     原始问题
          ├─ 假设问题检索  LLM 先生成假设答案（HyDE），用答案去召回
          ├─ 子问题查询    把多问句拆成 2~3 个子问题分别召回
          └─ 回溯问题检索  抽象成上位问题（step-back）再召回

设计取舍：
- **一次 LLM 调用产出全部字段**，避免每问 4 次改写把首字延迟拖到十几秒；
- 短问题、寒暄直接走启发式，不花这次调用；
- 结果按「归一化问题」缓存，重复提问不再调用模型；
- 任何异常都降级为 `direct`，改写只是加分项，不能成为故障点。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from app.core.config import settings
from app.services.cache import get_json, set_json
from app.services.llm import complete

INTENTS = ("professional", "coding", "general", "chitchat")
STRATEGIES = ("direct", "hyde", "subquery", "backtrack")

_CODING_HINTS = (
    "python", "java", "sql", "代码", "函数", "接口", "报错", "部署", "docker",
    "fastapi", "vue", "react", "报错信息", "异常栈", "依赖", "环境变量",
)
_MEDICAL_HINTS = (
    "患者", "诊断", "用药", "剂量", "治疗", "症状", "抗生素", "护理", "医嘱",
    "科室", "急诊", "感染", "手术", "检验", "影像", "病史", "临床", "不良反应",
    # 院内制度与操作类术语，避免把临床问题误判成「通用咨询」
    "按压", "通气", "复苏", "急救", "抢救", "除颤", "消毒", "灭菌", "隔离", "防护",
    "职业暴露", "锐器", "手卫生", "培训", "制度", "流程", "危急值", "病历", "处方",
    "输注", "注射", "静脉", "血压", "心率", "体温", "病区", "值班", "交接班",
)
_CHITCHAT = ("你好", "您好", "在吗", "hi", "hello", "谢谢", "感谢", "再见", "嗯", "好的")
_MULTI_SPLIT = re.compile(r"[？?]|(?:以及|还有|分别为|分别是|分别|并且)")

_ANALYZE_PROMPT = """你是院内知识库问答系统的「查询分析器」。请分析用户问题，只输出一个 JSON 对象，不要任何解释。

字段要求：
- intent: 只能是 professional（医疗专业）/ coding（编程技术）/ general（其他咨询）/ chitchat（寒暄，无需检索）
- need_retrieval: 布尔值，是否需要检索院内资料
- strategy: 检索策略，只能是
  direct（问题明确、单点，直接用原问题检索）
  subquery（一个问题里包含多个子问题，需要拆分）
  backtrack（问题过于具体或跳步，需要先抽象成上位问题）
  hyde（问题口语化、简短、与资料表述差异大，需要先生成假设答案再检索）
- simplified: 把口语问题改写成适合检索的短查询（不超过 40 字），没有把握就留空
- sub_queries: strategy=subquery 时给出 2~3 个子问题，否则为空数组
- backtrack: strategy=backtrack 时的上位问题，否则为空字符串
- hyde: strategy=hyde 时写一段 100~150 字的「假设答案」，用院内规范的口吻陈述，否则为空字符串

判断原则：能用原问题直接检索就不要改写；改写只是为了解决「问法与资料表述不一致」。
用户问题：{question}"""


@dataclass
class QueryPlan:
    """一次查询的检索计划。"""

    intent: str = "professional"
    strategy: str = "direct"
    need_retrieval: bool = True
    simplified: str = ""
    hyde: str = ""
    backtrack: str = ""
    sub_queries: list[str] = field(default_factory=list)
    source: str = "heuristic"

    def variants(self, question: str, limit: int | None = None) -> list[dict]:
        """产出待召回的 query 变体，原问题永远排第一。"""
        limit = limit or settings.query_max_variants
        items: list[dict] = [{"text": question, "label": "direct"}]
        if self.simplified and self.simplified.strip() != question.strip():
            items.append({"text": self.simplified.strip(), "label": "simplified"})
        if self.backtrack.strip():
            items.append({"text": self.backtrack.strip(), "label": "backtrack"})
        for sub in self.sub_queries:
            if sub.strip():
                items.append({"text": sub.strip(), "label": "sub"})
        if self.hyde.strip():
            items.append({"text": self.hyde.strip(), "label": "hyde"})
        # 去重（文本相同只保留第一次出现）
        seen: set[str] = set()
        unique: list[dict] = []
        for item in items:
            key = item["text"].strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[: max(1, limit)]

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "strategy": self.strategy,
            "need_retrieval": self.need_retrieval,
            "simplified": self.simplified,
            "sub_queries": self.sub_queries,
            "source": self.source,
        }


def _guess_intent(question: str) -> str:
    text = question.lower()
    if any(word in text for word in _CHITCHAT) and len(question) <= 8:
        return "chitchat"
    coding = sum(1 for word in _CODING_HINTS if word in text)
    medical = sum(1 for word in _MEDICAL_HINTS if word in text)
    if coding > medical:
        return "coding"
    if medical:
        return "professional"
    return "general"


def heuristic_plan(question: str) -> QueryPlan:
    """不调用模型的快速判断。"""
    text = question.strip()
    intent = _guess_intent(text)
    plan = QueryPlan(intent=intent, strategy="direct", source="heuristic")
    if intent == "chitchat" and len(text) <= 8:
        plan.need_retrieval = False
        return plan

    parts = [piece.strip() for piece in _MULTI_SPLIT.split(text) if len(piece.strip()) >= 4]
    if len(parts) >= 2 and len(text) >= 20:
        plan.strategy = "subquery"
        plan.sub_queries = parts[:3]
    elif len(text) >= 30 and any(word in text for word in ("为什么", "原理", "机制", "怎么理解", "底层")):
        plan.strategy = "backtrack"
        plan.backtrack = text
    return plan


def _parse_json(raw: str) -> dict:
    """从模型输出里尽力抠出 JSON（兼容 ```json 包裹与前后废话）。"""
    if not raw:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start >= 0 and end > start else ""
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning(f"查询分析结果不是合法 JSON：{raw[:120]}")
        return {}


def analyze(question: str, history: list[dict] | None = None) -> QueryPlan:
    """分析问题，返回检索计划。失败或未开启时退回启发式结果。"""
    base = heuristic_plan(question)
    if not settings.query_rewrite_enabled:
        return base
    if not base.need_retrieval:
        return base
    if len(question.strip()) < settings.query_rewrite_min_chars:
        return base

    cache_key = f"qa:plan:{abs(hash(question.strip()))}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        plan = QueryPlan(source="cache")
        plan.intent = cached.get("intent") or base.intent
        plan.strategy = cached.get("strategy") or "direct"
        plan.need_retrieval = bool(cached.get("need_retrieval", True))
        plan.simplified = cached.get("simplified") or ""
        plan.hyde = cached.get("hyde") or ""
        plan.backtrack = cached.get("backtrack") or ""
        plan.sub_queries = list(cached.get("sub_queries") or [])
        return plan

    try:
        raw = complete(
            [{"role": "user", "content": _ANALYZE_PROMPT.format(question=question)}],
            temperature=0.1,
            max_tokens=600,
        )
        data = _parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"查询分析调用失败，退回启发式：{exc}")
        return base

    if not data:
        return base

    intent = data.get("intent") if data.get("intent") in INTENTS else base.intent
    strategy = data.get("strategy") if data.get("strategy") in STRATEGIES else "direct"
    plan = QueryPlan(
        intent=intent,
        strategy=strategy,
        need_retrieval=bool(data.get("need_retrieval", True)),
        simplified=str(data.get("simplified") or "").strip()[:200],
        hyde=str(data.get("hyde") or "").strip()[:600],
        backtrack=str(data.get("backtrack") or "").strip()[:200],
        sub_queries=[str(item).strip()[:200] for item in (data.get("sub_queries") or []) if str(item).strip()][:3],
        source="llm",
    )
    # 与启发式取并集：模型漏掉的子问题拆分由正则补上
    if not plan.sub_queries and base.sub_queries:
        plan.sub_queries = base.sub_queries
    set_json(
        cache_key,
        {
            "intent": plan.intent,
            "strategy": plan.strategy,
            "need_retrieval": plan.need_retrieval,
            "simplified": plan.simplified,
            "hyde": plan.hyde,
            "backtrack": plan.backtrack,
            "sub_queries": plan.sub_queries,
        },
        settings.query_rewrite_cache_ttl,
    )
    logger.info(
        f"查询分析：intent={plan.intent} strategy={plan.strategy} "
        f"子问题={len(plan.sub_queries)} 来源={plan.source}"
    )
    return plan
