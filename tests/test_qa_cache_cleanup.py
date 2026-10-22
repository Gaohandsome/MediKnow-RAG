"""问答缓存的库级清理：删知识库时把独占的缓存一起带走。"""
from __future__ import annotations

from sqlalchemy import delete, select

from app.models.qa import QAPair
from app.services.qa_cache import forget_kb, normalize


def _add(db, question: str, kb_ids: list[int]) -> QAPair:
    row = QAPair(
        question=question,
        question_key=normalize(question),
        answer="答案占位",
        kb_ids=kb_ids,
        contexts=[],
        plan={},
        hit_count=1,
    )
    db.add(row)
    db.commit()
    return row


def test_forget_kb_removes_exclusive_pairs(db):
    exclusive = _add(db, "删库专用问题 A", [901])
    shared = _add(db, "多库共享问题 B", [901, 902])
    other = _add(db, "别的库问题 C", [902])
    try:
        removed = forget_kb(db, 901)
        assert removed == 1

        db.expire_all()
        assert db.get(QAPair, exclusive.id) is None
        # 共享条目保留，只摘掉被删的 kb_id
        kept = db.get(QAPair, shared.id)
        assert kept is not None and kept.kb_ids == [902]
        assert db.get(QAPair, other.id) is not None
    finally:
        db.execute(delete(QAPair).where(QAPair.question_key.in_(
            [normalize("删库专用问题 A"), normalize("多库共享问题 B"), normalize("别的库问题 C")]
        )))
        db.commit()


def test_forget_kb_ignores_unknown_kb(db):
    row = _add(db, "无关问题 D", [903])
    try:
        assert forget_kb(db, 999) == 0
        db.expire_all()
        assert db.scalar(select(QAPair).where(QAPair.id == row.id)) is not None
    finally:
        db.execute(delete(QAPair).where(QAPair.id == row.id))
        db.commit()
