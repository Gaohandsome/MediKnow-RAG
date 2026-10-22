"""缓存后端：连接串拼装、密码脱敏、Redis 不可用时降级。"""
from __future__ import annotations

import app.services.cache as cache
from app.core.config import Settings, settings


def test_dsn_built_from_parts():
    s = Settings(_env_file=None, redis_host="10.0.0.9", redis_port=6380,
                 redis_password="pwd", redis_db=2, redis_url="")
    assert s.redis_dsn == "redis://:pwd@10.0.0.9:6380/2"


def test_dsn_without_password():
    s = Settings(_env_file=None, redis_host="127.0.0.1", redis_port=6379,
                 redis_password="", redis_db=0, redis_url="")
    assert s.redis_dsn == "redis://127.0.0.1:6379/0"


def test_explicit_url_wins():
    s = Settings(_env_file=None, redis_url="redis://:x@example.com:6379/5",
                 redis_host="ignored", redis_password="ignored")
    assert s.redis_dsn == "redis://:x@example.com:6379/5"


def test_masked_dsn_hides_password(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://:secret@127.0.0.1:6379/0")
    masked = cache._masked_dsn()
    assert "secret" not in masked
    assert "***" in masked
    assert masked.endswith("127.0.0.1:6379/0")


def _reset_kv():
    cache._kv = None
    cache._warned = False


def test_degrades_to_memory_when_disabled(monkeypatch):
    _reset_kv()
    monkeypatch.setattr(settings, "redis_enabled", False)
    kv = cache.get_kv()
    assert kv.backend == "memory"
    kv.set("k", "v", 10)
    assert kv.get("k") == "v"
    assert kv.incr("n", 10) == 1
    _reset_kv()


def test_degrades_when_redis_unreachable(monkeypatch):
    """端口写错也要能起，不能因为 Redis 挂了导致问答不可用。"""
    _reset_kv()
    monkeypatch.setattr(settings, "redis_enabled", True)
    monkeypatch.setattr(settings, "redis_url", "redis://:pwd@127.0.0.1:6390/0")
    monkeypatch.setattr(settings, "redis_timeout", 0.3)
    kv = cache.get_kv()
    assert kv.backend == "memory"
    assert kv.health()["ok"] is True
    _reset_kv()
