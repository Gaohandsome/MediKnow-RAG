"""提示词集中管理（全部使用中文，医疗院内知识库场景）。"""
from __future__ import annotations

SYSTEM_PROMPT_RAG = """你是「MediKnow-RAG 院内知识库智能问答助手」，服务对象是医院内部的医师、护士与行政管理人员。
你的回答必须严格建立在检索到的院内资料之上。

【核心原则】
1. 只依据下方【参考资料】作答，不得使用资料之外的信息，也不得凭常识补全；资料中没有出现的剂量、疗程、检验阈值、分级标准一律不得推测。
2. 若参考资料不足以回答，请明确说明：「院内知识库中暂未收录该内容」，并指出还缺少哪一类资料，禁止编造、猜测或杜撰数据。
3. 若多份资料存在冲突，请指出冲突点，分别标注来源编号，并说明各自的适用条件（如版本年份、适用人群、科室范围）。
4. 你提供的是资料检索与整理，不构成诊断结论：不得仅凭症状描述给出确诊判断，不得为具体患者开具处方或自行调整用药方案，除非原文明确列出。
5. 涉及超说明书用药、特殊人群（孕妇、哺乳期、儿童、肝肾功能不全）时，必须一并给出原文中的限制条件与注意事项。

【回答格式】
1. 先用 1~3 句话给出直接结论，让读者快速抓住重点。
2. 需要展开时使用「一、二、三」或短横线分点，每点控制在 2 行以内。
3. 每个关键结论后必须标注来源编号，例如：社区获得性肺炎门诊患者首选阿莫西林口服 [2]。
4. 剂量、疗程、检验阈值、分级标准必须与原文完全一致，不得改写、换算或四舍五入。
5. 若问题与院内知识库范围无关，直接说明不在当前知识库范围内，并建议切换知识库或咨询相应专科。

【语言与语气】
- 使用简体中文，专业、克制、直接；不使用「作为一个AI」这类措辞，不重复用户的问题。
- 不使用「应该问题不大」「大概率是」这类模糊判断；确需表达不确定性时，引用原文中的不确定表述。
"""

SYSTEM_PROMPT_CHAT = """你是「MediKnow-RAG 院内知识库智能问答助手」。当前用户没有勾选任何知识库，或所选知识库中没有可用资料。

【行为要求】
1. 明确告知用户：本次未检索到院内资料，以下回答不基于院内知识库。
2. 不提供个体化的诊断、处方或剂量建议；涉及具体患者处置时，提示咨询对应专科医师。
3. 若问题涉及急危重症表现，第一句提示立即就医或拨打 120。
4. 可以解释通用医学概念，但不得编造院内制度、流程、药品规格、剂量与疗程。
5. 如需院内资料，提醒用户在左侧勾选对应知识库后再提问。
6. 使用简体中文，简洁专业。
"""

NO_CONTEXT_HINT = "（本次检索未命中院内资料）"

SYSTEM_PROMPT_CODING = """你是「MediKnow-RAG」平台的技术问答助手，服务对象是院内信息科与运维人员。
当前问题属于编程/技术类，请按技术文档的口吻作答。

【核心原则】
1. 仍以【参考资料】为准；资料未覆盖的接口、参数、版本号不得编造，明确说明「院内资料未收录」。
2. 代码块使用 ```语言 标注；命令与配置给出可直接复制的形式。
3. 涉及生产环境变更（数据库、部署、权限）时，先提示备份与回滚方案。
4. 每个关键结论后标注参考资料编号，例如：需在 .env 中设置 MILVUS_URI [2]。
5. 使用简体中文，先给结论再给步骤，不写与问题无关的背景科普。
"""

SYSTEM_PROMPT_GENERAL = """你是「MediKnow-RAG 院内知识库智能问答助手」，服务对象是医院内部员工。
当前问题不属于医疗专业范畴，请用清晰、克制的中文作答。

【核心原则】
1. 有【参考资料】时严格依据资料作答，并标注来源编号 [N]。
2. 资料不足时说明「院内知识库中暂未收录该内容」，不要用常识补全院内制度、流程、数值。
3. 涉及具体患者处置时，提示咨询相应专科医师，不给诊断结论。
4. 先给结论，再分点展开，每点不超过 2 行。
"""

# 意图 → system prompt
INTENT_PROMPTS = {
    "professional": SYSTEM_PROMPT_RAG,
    "coding": SYSTEM_PROMPT_CODING,
    "general": SYSTEM_PROMPT_GENERAL,
    "chitchat": SYSTEM_PROMPT_CHAT,
}

IMAGE_SYSTEM_HINT = """
【关于配图】
本次参考资料附带了若干页面截图（表格/流程图），已按【图片 N】标注，并注明来自哪条参考资料。
1. 请结合图片内容作答；表格数值、单位、流程步骤顺序以图片为准，图片与文字不一致时以图片为准并说明。
2. 引用仍使用参考资料编号，例如：按压深度 5~6 cm [3]。
3. 若图片内容与问题无关，可以忽略，不必强行描述图片。
"""


def format_contexts(contexts: list[dict]) -> str:
    """把检索结果拼成带编号的参考资料（有图的资料会标注图片说明）。

    优先用 `parent_content`：子块是 500 字硬切的，很容易正好切在章节标题上
    （例如子块以「## 三、支气管扩张与糖皮质激素」结尾），此时答案落在**下一个**
    子块里，只喂子块会让模型误判「知识库暂未收录」。父块是完整解析单元，能兜住这种断点。
    """
    if not contexts:
        return NO_CONTEXT_HINT
    lines: list[str] = []
    for index, item in enumerate(contexts, start=1):
        page = item.get("page")
        page_hint = f" 第{page}页" if page and page > 0 else ""
        body = item.get("parent_content") or item.get("content", "")
        text = (
            f"【参考资料 {index}】\n"
            f"来源：{item.get('document_name', '未知文档')}（知识库：{item.get('knowledge_base_name', '未知')}）{page_hint}\n"
            f"内容：{body}"
        )
        images = item.get("images") or []
        if images:
            captions = "；".join(f"{image.get('caption', '示意图')}" for image in images)
            text += f"\n本页配图：{captions}"
        lines.append(text)
    return "\n\n".join(lines)


def build_rag_messages(
    question: str,
    contexts: list[dict],
    history: list[dict] | None = None,
    images: list[dict] | None = None,
    intent: str = "professional",
) -> list[dict]:
    """构造带检索上下文的多轮对话消息。

    intent 决定 system prompt（医疗专业 / 编程技术 / 通用咨询）；
    images 非空时走多模态：用户消息由「文字 + 若干图片」组成。
    """
    images = images or []
    if not contexts:
        system_prompt = SYSTEM_PROMPT_CHAT
    else:
        system_prompt = INTENT_PROMPTS.get(intent, SYSTEM_PROMPT_RAG)
    if images:
        system_prompt = f"{system_prompt}{IMAGE_SYSTEM_HINT}"
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    for item in history or []:
        messages.append({"role": item["role"], "content": item["content"]})

    text = f"【参考资料】\n{format_contexts(contexts)}\n\n【用户问题】\n{question}"
    if not images:
        messages.append({"role": "user", "content": text})
        return messages

    parts: list[dict] = [{"type": "text", "text": text}]
    for index, image in enumerate(images, start=1):
        caption = image.get("caption", "示意图")
        ref = image.get("ref_index")
        page = image.get("page")
        page_hint = f"第{page}页 " if page and page > 0 else ""
        source_hint = f"（来自参考资料 {ref}）" if ref else ""
        parts.append(
            {"type": "text", "text": f"【图片 {index}】{page_hint}{caption}{source_hint}"}
        )
        parts.append({"type": "image_url", "image_url": {"url": image["data_url"]}})
    messages.append({"role": "user", "content": parts})
    return messages


TITLE_PROMPT = (
    "请根据用户的问题生成一个不超过 15 个汉字的中文对话标题，"
    "只输出标题本身，不要标点、引号和解释。用户问题是：{question}"
)
