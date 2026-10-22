"""医疗安全层：红旗症状识别、无依据拒答、免责声明。

设计原则：
1. 所有函数均为纯函数（除读取配置外），便于单元测试；
2. 免责声明由后端强制附加，不依赖模型是否"记得"写；
3. 无检索依据时不调用大模型，避免凭空生成诊疗建议。
"""
from __future__ import annotations

from app.core.config import settings

# 免责声明兜底文案（配置为空时使用）
FALLBACK_DISCLAIMER = (
    "以上内容依据院内知识库资料整理，仅供医疗专业人员参考，"
    "不能替代执业医师的诊断与处方。"
)

# 未选择知识库时的提示（与"检索无结果"区分，便于引导用户操作）
NO_KB_TEXT = (
    "尚未选择知识库，本次不作答。\n\n"
    "请在对话页左侧勾选至少一个院内知识库后再提问；"
    "如果需要具体的临床处置意见，请联系对应专科医师。"
)

# 拒答话术：检索为空或相关度过低时直接返回，不调用大模型
REFUSAL_TEXT = (
    "当前知识库未收录与该问题相关的资料。为避免误导，本次不作回答。\n\n"
    "建议：\n"
    "- 换用更具体的医学术语重新提问，或确认已勾选包含该主题的知识库；\n"
    "- 需要临床处置意见时，请联系对应专科医师，或查阅最新版诊疗规范与药品说明书。"
)

# 红旗规则：分类 -> 关键词（命中任一即触发安全提示）
RED_FLAG_RULES: dict[str, tuple[str, ...]] = {
    "急症表现": (
        "胸痛",
        "胸闷伴大汗",
        "呼吸困难",
        "喘不上气",
        "窒息",
        "意识障碍",
        "昏迷",
        "晕厥",
        "抽搐",
        "大出血",
        "咯血",
        "呕血",
        "黑便",
        "剧烈头痛",
        "高热惊厥",
        "休克",
        "口角歪斜",
        "言语不清",
        "自杀",
        "中毒",
    ),
    "用药风险": (
        "儿童剂量",
        "孕妇用药",
        "哺乳期用药",
        "超剂量",
        "过量服用",
        "药物过敏",
        "配伍禁忌",
        "自行停药",
    ),
}

RED_FLAG_TEMPLATE = (
    "【安全提示】您的问题涉及{category}（{keywords}）。"
    "若为正在发生的症状或正在处置的患者，请立即就近就医或拨打 120，"
    "不要以本系统的回答作为急救或用药依据。"
)


def disclaimer_text() -> str:
    """返回当前生效的免责声明。"""
    text = (settings.medical_disclaimer or "").strip()
    return text or FALLBACK_DISCLAIMER


def detect_red_flags(question: str) -> list[dict[str, str]]:
    """识别问题中的高危表述，返回 [{category, keyword}]。"""
    if not settings.safety_red_flag_enabled or not question:
        return []
    text = question.replace(" ", "")
    hits: list[dict[str, str]] = []
    for category, keywords in RED_FLAG_RULES.items():
        for keyword in keywords:
            if keyword in text:
                hits.append({"category": category, "keyword": keyword})
    return hits


def build_red_flag_notice(flags: list[dict[str, str]]) -> str:
    """把命中的红旗词拼成一段提示文案；无命中返回空串。"""
    if not flags:
        return ""
    categories: list[str] = []
    keywords: list[str] = []
    for item in flags:
        if item["category"] not in categories:
            categories.append(item["category"])
        if item["keyword"] not in keywords:
            keywords.append(item["keyword"])
    return RED_FLAG_TEMPLATE.format(
        category="、".join(categories), keywords="、".join(keywords)
    )


def should_refuse(contexts: list[dict], min_score: float | None = None) -> tuple[bool, str]:
    """判断是否应拒答。

    返回 (是否拒答, 原因)：原因为 empty（无召回）/ low_score（相关度不足）/ ""。
    """
    if not settings.safety_refuse_when_no_context:
        return False, ""
    if not contexts:
        return True, "empty"

    threshold = settings.safety_min_score if min_score is None else min_score
    if threshold <= 0:
        return False, ""

    # 优先使用稠密余弦相关度（0~1，跨检索模式可比）；缺失时退回 score
    def _relevance(item: dict) -> float:
        value = item.get("relevance")
        if value is None:
            value = item.get("score")
        return float(value or 0.0)

    best = max((_relevance(item) for item in contexts), default=0.0)
    if best < threshold:
        return True, "low_score"
    return False, ""
