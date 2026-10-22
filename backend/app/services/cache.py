"""缓存层：Redis 可用时走 Redis，否则自动降级为进程内实现。

设计原则：
- **不硬依赖 redis 包**。没装、没开、连不上都只是降级，不能让问答挂掉；
- 对外只暴露极小接口（string 的 get/set/delete/incr + hash 的 hget/hset_map/hincrby/
  hgetall/hdel/expire），业务侧不感知后端差异；
- hash 类型专门给问答缓存用：一个问题一个 field，精确命中只走一次 HGET，
  不用为了查一条记录去解析整包索引 JSON；
- 降级只记录一次警告，避免刷日志。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from loguru import logger

from app.core.config import settings


class _MemoryKV:
    """进程内 KV：带过期时间，单进程部署/未开 Redis 时使用。"""

    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._hash_expire: dict[str, float] = {}
        self._lock = threading.Lock()

    # ---------- string ----------

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expire_at = item
            if expire_at and expire_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl if ttl else 0)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._hashes.pop(key, None)
            self._hash_expire.pop(key, None)

    def incr(self, key: str, ttl: int = 0) -> int:
        with self._lock:
            item = self._data.get(key)
            current = 0
            if item and (not item[1] or item[1] > time.time()):
                try:
                    current = int(item[0])
                except ValueError:
                    current = 0
            current += 1
            expire_at = item[1] if item and item[1] > time.time() else (time.time() + ttl if ttl else 0)
            self._data[key] = (str(current), expire_at)
            return current

    # ---------- hash ----------

    def _hash(self, name: str) -> dict[str, str] | None:
        """取 hash（调用方已持锁）；已过期返回 None 并顺手清理。"""
        expire_at = self._hash_expire.get(name, 0)
        if expire_at and expire_at < time.time():
            self._hashes.pop(name, None)
            self._hash_expire.pop(name, None)
            return None
        return self._hashes.setdefault(name, {})

    def hget(self, name: str, key: str) -> str | None:
        with self._lock:
            bucket = self._hash(name)
            return bucket.get(key) if bucket is not None else None

    def hset_map(self, name: str, mapping: dict[str, str], ttl: int = 0) -> None:
        with self._lock:
            bucket = self._hash(name)
            if bucket is None:
                bucket = self._hashes.setdefault(name, {})
            bucket.update(mapping)
            if ttl:
                self._hash_expire[name] = time.time() + ttl

    def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        with self._lock:
            bucket = self._hash(name)
            if bucket is None:
                bucket = self._hashes.setdefault(name, {})
            try:
                current = int(bucket.get(key, 0))
            except ValueError:
                current = 0
            current += amount
            bucket[key] = str(current)
            return current

    def hgetall(self, name: str) -> dict[str, str]:
        with self._lock:
            bucket = self._hash(name)
            return dict(bucket) if bucket is not None else {}

    def hlen(self, name: str) -> int:
        with self._lock:
            bucket = self._hash(name)
            return len(bucket) if bucket is not None else 0

    def hdel(self, name: str, key: str) -> None:
        with self._lock:
            bucket = self._hash(name)
            if bucket is not None:
                bucket.pop(key, None)

    def expire(self, name: str, ttl: int) -> None:
        with self._lock:
            if name in self._hashes and ttl:
                self._hash_expire[name] = time.time() + ttl

    def health(self) -> dict[str, Any]:
        return {"backend": "memory", "ok": True, "detail": "进程内缓存（重启即失效）"}


def _masked_dsn() -> str:
    """日志/健康检查里用的连接串：隐去密码。"""
    dsn = settings.redis_dsn
    if "@" in dsn and "://" in dsn:
        scheme, rest = dsn.split("://", 1)
        auth, host = rest.rsplit("@", 1)
        user = auth.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return dsn


class _RedisKV:
    """Redis KV：跨 worker / 跨进程共享。"""

    backend = "redis"

    def __init__(self, client) -> None:  # noqa: ANN001
        self._client = client

    # ---------- string ----------

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        if ttl:
            self._client.set(key, value, ex=ttl)
        else:
            self._client.set(key, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def incr(self, key: str, ttl: int = 0) -> int:
        value = int(self._client.incr(key))
        if value == 1 and ttl:
            self._client.expire(key, ttl)
        return value

    # ---------- hash ----------

    def hget(self, name: str, key: str) -> str | None:
        return self._client.hget(name, key)

    def hset_map(self, name: str, mapping: dict[str, str], ttl: int = 0) -> None:
        """批量写 field：300 条问题不该发 300 次往返。

        Redis 4.0 起才支持多字段的 `HSET k f1 v1 f2 v2`；3.x 上这条会报
        "wrong number of arguments for 'hset'"，所以退回流水线（同样只要一次往返）。
        """
        if not mapping:
            return
        client = self._client
        try:
            client.hset(name, mapping=mapping)
        except Exception:  # noqa: BLE001  老版本 Redis 不支持多字段 HSET
            pipe = client.pipeline(transaction=False)
            for field, value in mapping.items():
                pipe.hset(name, field, value)
            pipe.execute()
        if ttl:
            client.expire(name, ttl)

    def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        return int(self._client.hincrby(name, key, amount))

    def hgetall(self, name: str) -> dict[str, str]:
        return self._client.hgetall(name) or {}

    def hlen(self, name: str) -> int:
        return int(self._client.hlen(name) or 0)

    def hdel(self, name: str, key: str) -> None:
        self._client.hdel(name, key)

    def expire(self, name: str, ttl: int) -> None:
        if ttl:
            self._client.expire(name, ttl)

    def health(self) -> dict[str, Any]:
        try:
            self._client.ping()
            return {"backend": "redis", "ok": True, "detail": _masked_dsn()}
        except Exception as exc:  # noqa: BLE001
            return {"backend": "redis", "ok": False, "detail": str(exc)}


_kv: _MemoryKV | _RedisKV | None = None
_kv_lock = threading.Lock()
_warned = False


def _build_client():
    """构造 redis 客户端。

    **必须显式指定 RESP2**：redis-py 8.x 默认走 RESP3，连接时先发 `HELLO`，
    而 Redis < 6.0（本项目实测 3.0.504）根本不认这条命令，会直接握手失败。
    redis-py 5 以下的版本没有 protocol 参数，故按大版本号区分。
    """
    import redis  # 延迟导入：没装也不影响启动

    kwargs = {
        "decode_responses": True,
        "socket_timeout": settings.redis_timeout,
        "socket_connect_timeout": settings.redis_timeout,
    }
    try:
        major = int(str(redis.__version__).split(".", 1)[0])
    except (ValueError, AttributeError):
        major = 0
    if major >= 5:
        kwargs["protocol"] = 2
    return redis.Redis.from_url(settings.redis_dsn, **kwargs)


def get_kv() -> _MemoryKV | _RedisKV:
    """获取缓存实例；Redis 不可用时自动降级。"""
    global _kv, _warned
    if _kv is not None:
        return _kv
    with _kv_lock:
        if _kv is not None:
            return _kv
        if settings.redis_enabled:
            try:
                client = _build_client()
                client.ping()
                _kv = _RedisKV(client)
                logger.info(f"缓存后端：Redis（{_masked_dsn()}）")
                return _kv
            except Exception as exc:  # noqa: BLE001
                if not _warned:
                    logger.warning(f"Redis 不可用（{exc}），降级为进程内缓存")
                    _warned = True
        _kv = _MemoryKV()
        if settings.redis_enabled and not _warned:
            logger.warning("未启用 Redis，使用进程内缓存")
            _warned = True
        return _kv


def cache_health() -> dict[str, Any]:
    return get_kv().health()


def get_json(key: str) -> Any | None:
    raw = get_kv().get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json(key: str, value: Any, ttl: int = 0) -> None:
    get_kv().set(key, json.dumps(value, ensure_ascii=False), ttl)
