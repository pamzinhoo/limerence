from __future__ import annotations

import time

import pytest

from core.rate_limiter import RateLimiter, RateLimitExceeded
from core.rate_limiter_factory import create_rate_limiter
from core.redis_rate_limiter import RedisRateLimiter


def test_falls_back_to_in_memory_without_redis_url(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    limiter = create_rate_limiter(max_hits=5, window_seconds=60)

    assert isinstance(limiter, RateLimiter)


def test_falls_back_to_in_memory_when_redis_package_missing(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "redis.asyncio":
            raise ImportError("no redis installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    limiter = create_rate_limiter(max_hits=5, window_seconds=60)

    assert isinstance(limiter, RateLimiter)


class _FakeRedis:
    def __init__(self) -> None:
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        bucket = self.sorted_sets.setdefault(key, {})
        for member in [m for m, score in bucket.items() if min_score <= score <= max_score]:
            del bucket[member]

    async def zcard(self, key: str) -> int:
        return len(self.sorted_sets.get(key, {}))

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False):
        bucket = self.sorted_sets.get(key, {})
        items = sorted(bucket.items(), key=lambda kv: kv[1])
        return items[start : end + 1 if end != -1 else None]

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.sorted_sets.setdefault(key, {}).update(mapping)

    async def expire(self, key: str, seconds: int) -> None:
        pass


class TestRedisRateLimiter:
    async def test_allows_hits_under_the_limit(self) -> None:
        redis_client = _FakeRedis()
        limiter = RedisRateLimiter(redis_client, max_hits=3, window_seconds=60)

        await limiter.hit("k")
        await limiter.hit("k")
        await limiter.hit("k")

    async def test_raises_when_limit_exceeded(self) -> None:
        redis_client = _FakeRedis()
        limiter = RedisRateLimiter(redis_client, max_hits=2, window_seconds=60)

        await limiter.hit("k")
        await limiter.hit("k")
        with pytest.raises(RateLimitExceeded):
            await limiter.hit("k")

    async def test_different_keys_have_independent_buckets(self) -> None:
        redis_client = _FakeRedis()
        limiter = RedisRateLimiter(redis_client, max_hits=1, window_seconds=60)

        await limiter.hit("a")
        await limiter.hit("b")  # nao deve estourar — chave diferente

    async def test_window_expiry_frees_up_capacity(self) -> None:
        redis_client = _FakeRedis()
        limiter = RedisRateLimiter(redis_client, max_hits=1, window_seconds=0.01)

        await limiter.hit("k")
        time.sleep(0.02)
        await limiter.hit("k")  # janela anterior expirou
