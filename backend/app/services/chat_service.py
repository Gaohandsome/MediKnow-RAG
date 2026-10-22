"""对话服务：会话管理 + 检索增强 + 流式回答。"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError
from app.db.session import SessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.models.knowledge import KnowledgeBase
from app.schemas.chat import ChatRequest, SessionCreate, SessionUpdate
from app.services.llm import stream_chat
from app.services.media import refresh_url, strip_sign
from app.services.prompt import build_rag_messages
from app.services.qa_cache import lookup as qa_lookup
from app.services.qa_cache import record as qa_record
from app.services.qa_cache import resolve_cached_contexts, touch as qa_touch
from app.services.query_analysis import QueryPlan, analyze, heuristic_plan
from app.services.retrieval import retrieve_multi
from app.services.safety import (
    NO_KB_TEXT,
    REFUSAL_TEXT,
    build_red_flag_notice,
    detect_red_flags,
    disclaimer_text,
    should_refuse,
)


def _get_owned(db: Session, session_id: int, user_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise BizError("会话不存在或无权访问", status_code=404)
    return session


def create_session(db: Session, user_id: int, payload: SessionCreate) -> ChatSession:
    """新建会话。"""
    kb_ids = _validate_kb_ids(db, payload.kb_ids, user_id)
    session = ChatSession(
        user_id=user_id,
        name=(payload.name or "新对话").strip() or "新对话",
        model=payload.model or settings.llm_default_model,
        temperature=settings.llm_temperature if payload.temperature is None else payload.temperature,
        top_p=settings.llm_top_p if payload.top_p is None else payload.top_p,
        max_tokens=settings.llm_max_tokens if payload.max_tokens is None else payload.max_tokens,
        history_rounds=settings.llm_history_rounds if payload.history_rounds is None else payload.history_rounds,
        kb_ids=kb_ids,
    )
    db.add(session)
    db.flush()
    return session


def list_sessions(db: Session, user_id: int) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
        )
    )


def update_session(db: Session, session_id: int, user_id: int, payload: SessionUpdate) -> ChatSession:
    session = _get_owned(db, session_id, user_id)
    if payload.name is not None:
        session.name = payload.name.strip()
    if payload.kb_ids is not None:
        session.kb_ids = _validate_kb_ids(db, payload.kb_ids, user_id)
    if payload.model is not None:
        session.model = payload.model
    if payload.temperature is not None:
        session.temperature = payload.temperature
    if payload.top_p is not None:
        session.top_p = payload.top_p
    if payload.max_tokens is not None:
        session.max_tokens = payload.max_tokens
    if payload.history_rounds is not None:
        session.history_rounds = payload.history_rounds
    db.flush()
    return session


def delete_session(db: Session, session_id: int, user_id: int) -> None:
    session = _get_owned(db, session_id, user_id)
    db.delete(session)
    db.flush()


def list_messages(db: Session, session_id: int, user_id: int) -> list[ChatMessage]:
    """读取历史消息。

    库里存的是规范 URL，这里对图片重新签一次名——签名只有 24 小时有效期，
    不重签的话旧会话里的缩略图过一天就变死链。
    """
    _get_owned(db, session_id, user_id)
    messages = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        )
    )
    for message in messages:
        if message.contexts:
            message.contexts = _refresh_contexts(message.contexts)
    return messages


def _refresh_contexts(contexts: list[dict]) -> list[dict]:
    """把上下文里的图片地址换成此刻可访问的 URL。"""
    refreshed: list[dict] = []
    for item in contexts or []:
        images = item.get("images") or []
        if not images:
            refreshed.append(item)
            continue
        refreshed.append(
            {
                **item,
                "images": [{**image, "url": refresh_url(image.get("url", ""))} for image in images],
            }
        )
    return refreshed


def _plain_contexts(contexts: list[dict]) -> list[dict]:
    """落库前把签名剥掉：签名随时会失效，存进数据库只会变成死链。"""
    stored: list[dict] = []
    for item in contexts or []:
        images = item.get("images") or []
        if not images:
            stored.append(item)
            continue
        stored.append(
            {
                **item,
                "images": [{**image, "url": strip_sign(image.get("url", ""))} for image in images],
            }
        )
    return stored


def _validate_kb_ids(db: Session, kb_ids: list[int], user_id: int) -> list[int]:
    """校验会话选中的知识库是否可用。

    `KB_SHARED_READ=true`（默认）时任意存在的知识库都能选——院内资料全院共用；
    关闭共享后才要求必须是自己名下的库。
    """
    if not kb_ids:
        return []
    stmt = select(KnowledgeBase.id).where(KnowledgeBase.id.in_(kb_ids))
    if not settings.kb_shared_read:
        stmt = stmt.where(KnowledgeBase.user_id == user_id)
    rows = db.scalars(stmt)
    valid = list(rows)
    if len(valid) != len(set(kb_ids)):
        raise BizError("存在无效的知识库选择", status_code=400)
    return valid


def _sse(event_type: str, **payload) -> str:
    data = {"type": event_type, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history_messages(db: Session, session_id: int, rounds: int) -> list[dict]:
    """取最近 N 轮历史对话（不含当前这条用户消息）。"""
    if rounds <= 0:
        return []
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(rounds * 2 + 1)
        )
    )
    rows.reverse()
    # 去掉最后一条（本次用户提问已入库）
    if rows and rows[-1].role == "user":
        rows = rows[:-1]
    return [{"role": row.role, "content": row.content} for row in rows if row.content]


def _save_assistant(
    db: Session,
    session: ChatSession,
    content: str,
    contexts: list[dict],
    latency_ms: int,
    plan: dict | None = None,
) -> ChatMessage:
    """落库助手消息（正常回答与拒答共用）。

    上下文里的图片地址会被剥掉签名再存——签名 24 小时就失效，
    存下来只会变成死链；读取时（`list_messages`）再按需重签。
    """
    assistant = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=content,
        contexts=_plain_contexts(contexts),
        plan=plan or {},
        latency_ms=latency_ms,
    )
    db.add(assistant)
    session.last_message_at = datetime.now()
    db.commit()
    return assistant


def _plan_from_cache(payload: dict, question: str) -> QueryPlan:
    """复用命中缓存时记录的检索计划，避免再调用一次模型。"""
    plan = QueryPlan(source="cache")
    plan.intent = payload.get("intent") or heuristic_plan(question).intent
    plan.strategy = payload.get("strategy") or "direct"
    plan.need_retrieval = True
    plan.simplified = payload.get("simplified") or ""
    plan.sub_queries = list(payload.get("sub_queries") or [])
    return plan


def _collect_images(contexts: list[dict], limit: int) -> list[dict]:
    """从命中的参考资料里挑出配图并下载为 base64。

    只取前 limit 张，避免一次塞太多图拖慢首字延迟；下载失败的图直接跳过，
    不影响纯文本回答。
    """
    if limit <= 0:
        return []
    from app.services.media import to_data_url

    picked: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(contexts, start=1):
        for image in item.get("images") or []:
            url = (image or {}).get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            data_url = to_data_url(url)
            if not data_url:
                continue
            picked.append(
                {
                    "caption": image.get("caption", "示意图"),
                    "url": url,
                    "kind": image.get("kind", "figure"),
                    "page": item.get("page"),
                    "ref_index": index,
                    "data_url": data_url,
                }
            )
            if len(picked) >= limit:
                return picked
    return picked


def stream_answer(user_id: int, payload: ChatRequest) -> Iterator[str]:
    """SSE 流式回答：检索 -> 组装提示词 -> 流式生成 -> 落库。"""
    db = SessionLocal()
    started = time.perf_counter()
    try:
        # 1. 会话准备
        if payload.session_id:
            session = _get_owned(db, payload.session_id, user_id)
        else:
            session = create_session(db, user_id, SessionCreate(kb_ids=payload.kb_ids))
            db.commit()

        # 2. 推理参数与知识库以本次请求为准，并回写会话
        if payload.model:
            session.model = payload.model
        if payload.temperature is not None:
            session.temperature = payload.temperature
        if payload.top_p is not None:
            session.top_p = payload.top_p
        if payload.max_tokens is not None:
            session.max_tokens = payload.max_tokens
        if payload.history_rounds is not None:
            session.history_rounds = payload.history_rounds
        kb_ids = payload.kb_ids or list(session.kb_ids or [])
        if payload.kb_ids:
            session.kb_ids = _validate_kb_ids(db, payload.kb_ids, user_id)

        if session.name in ("", "新对话"):
            session.name = payload.question[:20]

        # 3. 取历史（在写入本次提问之前查询）
        history = _history_messages(db, session.id, session.history_rounds)

        # 4. 记录用户消息
        user_message = ChatMessage(session_id=session.id, role="user", content=payload.question)
        db.add(user_message)
        session.last_message_at = datetime.now()
        db.commit()

        yield _sse("meta", session_id=session.id, message_id=user_message.id, session_name=session.name)

        # 5. 精确问答缓存（流程图上的第一道判断：命中就不用再花模型调用）
        cached = qa_lookup(db, payload.question, kb_ids) if kb_ids else None

        # 5.1 查询理解：命中缓存时沿用当时的计划，不再调用模型
        if cached:
            plan = _plan_from_cache(cached.get("plan") or {}, payload.question)
        elif not kb_ids:
            plan = QueryPlan(intent="chitchat", need_retrieval=False)
        else:
            plan = analyze(payload.question, history)
        variants = (
            plan.variants(payload.question)
            if kb_ids and plan.need_retrieval and not cached
            else []
        )
        yield _sse(
            "plan",
            intent=plan.intent,
            strategy=plan.strategy,
            need_retrieval=plan.need_retrieval,
            source=plan.source,
            variants=[{"label": item["label"], "text": item["text"][:120]} for item in variants],
        )
        yield _sse(
            "cache",
            hit=bool(cached),
            source=(cached or {}).get("source"),
            score=(cached or {}).get("score"),
            matched_question=(cached or {}).get("question"),
        )

        if cached:
            contexts = resolve_cached_contexts(cached.get("contexts") or [])
            yield _sse("contexts", contexts=contexts)
            red_flags = detect_red_flags(payload.question)
            notice = build_red_flag_notice(red_flags)
            disclaimer = disclaimer_text() if settings.medical_disclaimer_enabled else ""
            yield _sse(
                "safety",
                refusal=False,
                reason="",
                red_flags=red_flags,
                notice=notice,
                disclaimer=disclaimer,
            )
            answer = cached["answer"]
            if notice:
                answer = f"{notice}\n\n{answer}"
            latency = int((time.perf_counter() - started) * 1000)
            yield _sse("delta", content=answer)
            info = {
                **plan.to_dict(),
                "cache_hit": True,
                "cache_source": cached.get("source"),
                "cache_score": cached.get("score"),
            }
            assistant = _save_assistant(db, session, answer, contexts, latency, info)
            qa_touch(db, cached.get("question") or payload.question)
            yield _sse(
                "done",
                message_id=assistant.id,
                session_id=session.id,
                latency_ms=latency,
                contexts=contexts,
                refused=False,
                cache_hit=True,
                plan=info,
            )
            logger.info(
                f"缓存命中：session={session.id} source={cached.get('source')} "
                f"score={cached.get('score')} 耗时={latency}ms"
            )
            return

        # 5.2 多路召回（融合 + 父文档去重 + 精排）
        contexts: list[dict] = []
        if variants:
            try:
                contexts = retrieve_multi(
                    db,
                    variants,
                    kb_ids=kb_ids,
                    user_id=user_id,
                    top_k=payload.top_k,
                    use_rerank=payload.use_rerank,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"检索失败：{exc}")
                yield _sse("warning", message=f"检索服务异常，本次不基于院内资料作答：{exc}")

        yield _sse("contexts", contexts=contexts)

        # 6. 医疗安全层：疾症预警 / 无依据拒答 / 免责声明
        if kb_ids and plan.intent == "chitchat" and not plan.need_retrieval:
            # 寒暄不需要资料，也不该被「无依据拒答」拦下
            refuse, refuse_reason = False, ""
        elif not kb_ids and settings.safety_refuse_when_no_context:
            refuse, refuse_reason = True, "no_kb"
        else:
            refuse, refuse_reason = should_refuse(contexts)
        red_flags = detect_red_flags(payload.question)
        notice = build_red_flag_notice(red_flags)
        disclaimer = disclaimer_text() if settings.medical_disclaimer_enabled else ""
        yield _sse(
            "safety",
            refusal=refuse,
            reason=refuse_reason,
            red_flags=red_flags,
            notice=notice,
            disclaimer=disclaimer,
        )

        if refuse:
            refusal = NO_KB_TEXT if refuse_reason == "no_kb" else REFUSAL_TEXT
            latency = int((time.perf_counter() - started) * 1000)
            yield _sse("delta", content=refusal)
            info = {**plan.to_dict(), "cache_hit": False, "refused": True}
            assistant = _save_assistant(db, session, refusal, [], latency, info)
            yield _sse(
                "done",
                message_id=assistant.id,
                session_id=session.id,
                latency_ms=latency,
                contexts=[],
                refused=True,
                reason=refuse_reason,
            )
            logger.warning(
                f"触发无依据拒答：session={session.id} reason={refuse_reason} kb={kb_ids}"
            )
            return

        # 7. 图文混合：命中的资料带图时下载图片，走多模态模型
        images: list[dict] = []
        if settings.vision_enabled and any(item.get("has_image") for item in contexts):
            images = _collect_images(contexts, settings.vision_max_images)
        model = settings.llm_vl_model if images else (session.model or settings.llm_default_model)
        yield _sse(
            "vision",
            used=bool(images),
            model=model,
            images=[
                {
                    "url": item["url"],
                    "caption": item["caption"],
                    "kind": item["kind"],
                    "page": item.get("page"),
                    "ref_index": item.get("ref_index"),
                }
                for item in images
            ],
        )
        if images:
            logger.info(f"图文问答：命中图片 {len(images)} 张，model={model}")
        else:
            logger.info(f"纯文本问答：model={model}")

        # 8. 流式生成
        messages = build_rag_messages(
            payload.question, contexts, history, images=images, intent=plan.intent
        )
        answer_parts: list[str] = []
        try:
            for delta in stream_chat(
                messages,
                model=model,
                temperature=session.temperature,
                top_p=session.top_p,
                max_tokens=session.max_tokens,
            ):
                answer_parts.append(delta)
                yield _sse("delta", content=delta)
        except BizError as exc:
            # 多模态模型不可用时（如网关没开该模型）退回文本模型，保证问答不中断
            if not images or answer_parts:
                raise
            logger.warning(f"多模态模型调用失败，回退文本模型：{exc.message}")
            model = session.model or settings.llm_default_model
            images = []
            yield _sse("warning", message=f"图片理解模型不可用，已回退纯文本回答（{model}）")
            messages = build_rag_messages(
                payload.question, contexts, history, images=[], intent=plan.intent
            )
            for delta in stream_chat(
                messages,
                model=model,
                temperature=session.temperature,
                top_p=session.top_p,
                max_tokens=session.max_tokens,
            ):
                answer_parts.append(delta)
                yield _sse("delta", content=delta)

        answer = "".join(answer_parts).strip()
        latency = int((time.perf_counter() - started) * 1000)

        # 9. 保存助手消息（高危提示写入正文，便于历史回看时仍然可见）
        stored = f"{notice}\n\n{answer}" if notice else answer
        info = {**plan.to_dict(), "cache_hit": False}
        assistant = _save_assistant(db, session, stored, contexts, latency, info)

        # 10. 沉淀问答对：下次同样问法可直接命中缓存
        if settings.qa_cache_enabled and contexts and stored:
            try:
                qa_record(db, payload.question, stored, kb_ids, contexts, plan.to_dict())
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"问答对沉淀失败：{exc}")

        yield _sse(
            "done",
            message_id=assistant.id,
            session_id=session.id,
            latency_ms=latency,
            contexts=contexts,
            refused=False,
            cache_hit=False,
            plan=info,
        )
        logger.info(f"回答完成：session={session.id} 长度={len(answer)} 耗时={latency}ms")
    except BizError as exc:
        yield _sse("error", message=exc.message)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"对话处理异常：{exc}")
        yield _sse("error", message=f"回答生成失败：{exc}")
    finally:
        db.close()
