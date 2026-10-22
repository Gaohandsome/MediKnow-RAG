"""医疗安全层单元测试：红旗识别、无依据拒答、免责声明。"""
from __future__ import annotations

from app.core.config import settings
from app.services import safety


def test_disclaimer_contains_required_wording():
    text = safety.disclaimer_text()
    assert "不能替代执业医师" in text


def test_detect_red_flags_emergency():
    flags = safety.detect_red_flags("我父亲突然胸痛、呼吸困难，应该怎么办？")
    keywords = {item["keyword"] for item in flags}
    assert {"胸痛", "呼吸困难"} <= keywords
    assert all(item["category"] == "急症表现" for item in flags)


def test_detect_red_flags_medication_risk():
    flags = safety.detect_red_flags("儿童剂量怎么换算？可以自行停药吗？")
    categories = {item["category"] for item in flags}
    assert "用药风险" in categories
    assert any(item["keyword"] == "儿童剂量" for item in flags)


def test_detect_red_flags_ignores_guideline_question():
    """规范的诊疗问题不应误触发红牌。"""
    assert safety.detect_red_flags("社区获得性肺炎的经验性抗菌治疗原则是什么？") == []


def test_detect_red_flags_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "safety_red_flag_enabled", False)
    assert safety.detect_red_flags("患者突发胸痛") == []


def test_build_red_flag_notice_merges_categories():
    flags = [
        {"category": "急症表现", "keyword": "胸痛"},
        {"category": "急症表现", "keyword": "呼吸困难"},
        {"category": "用药风险", "keyword": "儿童剂量"},
    ]
    notice = safety.build_red_flag_notice(flags)
    assert "急症表现、用药风险" in notice
    assert "胸痛、呼吸困难、儿童剂量" in notice
    assert "立即就近就医" in notice


def test_build_red_flag_notice_empty():
    assert safety.build_red_flag_notice([]) == ""


def test_should_refuse_without_context():
    refuse, reason = safety.should_refuse([])
    assert refuse is True
    assert reason == "empty"


def test_should_not_refuse_with_context_and_zero_threshold():
    refuse, reason = safety.should_refuse([{"score": 0.01}], min_score=0.0)
    assert refuse is False
    assert reason == ""


def test_should_prefer_relevance_over_score(monkeypatch):
    """稠密相关度优先于 RRF/重排分数，避免混合检索的排名分被误当相似度。"""
    monkeypatch.setattr(settings, "safety_min_score", 0.5)
    refuse, _ = safety.should_refuse([{"score": 0.02, "relevance": 0.42}])
    assert refuse is True

    refuse_ok, _ = safety.should_refuse([{"score": 0.02, "relevance": 0.66}])
    assert refuse_ok is False


def test_should_refuse_when_score_below_threshold(monkeypatch):
    monkeypatch.setattr(settings, "safety_min_score", 0.5)
    refuse, reason = safety.should_refuse([{"score": 0.2}, {"score": 0.3}])
    assert refuse is True
    assert reason == "low_score"

    refuse_ok, _ = safety.should_refuse([{"score": 0.2}, {"score": 0.8}])
    assert refuse_ok is False


def test_should_refuse_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "safety_refuse_when_no_context", False)
    refuse, _ = safety.should_refuse([])
    assert refuse is False


def test_explicit_min_score_overrides_settings(monkeypatch):
    monkeypatch.setattr(settings, "safety_min_score", 0.0)
    refuse, reason = safety.should_refuse([{"score": 0.1}], min_score=0.9)
    assert refuse is True
    assert reason == "low_score"
