"""配置自检：示例密钥不能被带上生产。"""
from __future__ import annotations

from app.core.config import Settings


def _settings(**kwargs) -> Settings:
    base = {"jwt_secret": "9f2c1b7e4a6d8c0e5b3a1f7d2c8e4b6a", "llm_api_key": "sk-local-test"}
    base.update(kwargs)
    return Settings(_env_file=None, **base)


def test_ready_config_passes():
    assert _settings().insecure_defaults == []


def test_placeholder_jwt_secret_is_flagged():
    for placeholder in ("change-me", "please-change-me", "  ", "CHANGE-ME"):
        assert "JWT_SECRET" in _settings(jwt_secret=placeholder).insecure_defaults


def test_missing_llm_key_is_flagged():
    assert "LLM_API_KEY" in _settings(llm_api_key="   ").insecure_defaults


def test_both_issues_reported_at_once():
    issues = _settings(jwt_secret="change-me", llm_api_key="").insecure_defaults
    assert set(issues) == {"JWT_SECRET", "LLM_API_KEY"}
