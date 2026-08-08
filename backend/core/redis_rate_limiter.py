from __future__ import annotations

import time
import uuid
from typing import Any

from core.rate_limiter import RateLimitExceeded


class RedisRateLimiter:
    """Janela deslizante compartilhada via Redis (sorted set por chave) —
    mesma interface `async hit(key)` do `RateLimiter` in-memory
    (`core/rate_limiter.py`), drop-in replacement quando `REDIS_URL` esta
    configurado. Sobrevive a restart e escala pra multiplas instancias do
    backend — fecha o TODO documentado em `core/rate_limiter.py`.

    Duas chamadas Redis por `hit()` em vez de uma (remove+conta, depois
    adiciona só se permitido) — não é atômico ponta a ponta sob alta
    concorrência (mesma classe de corrida que qualquer sliding-window
    distribuído sem Lua script), mas é a mesma garantia prática que o
    rate limiter existia pra dar: um teto aproximado, não uma trava exata."""

    def __init__(
        self, redis_client: Any, *, max_hits: int, window_seconds: float, key_prefix: str = "ratelimit"
    ) -> None:
        self._redis = redis_client
        self._max_hits = max_hits
        self._window_seconds = window_seconds
        self._key_prefix = key_prefix

    async def hit(self, key: str) -> None:
        redis_key = f"{self._key_prefix}:{key}"
        now = time.time()
        window_start = now - self._window_seconds

        await self._redis.zremrangebyscore(redis_key, 0, window_start)
        count = await self._redis.zcard(redis_key)
        if count >= self._max_hits:
            oldest = await self._redis.zrange(redis_key, 0, 0, withscores=True)
            retry_after = self._window_seconds - (now - oldest[0][1]) if oldest else self._window_seconds
            raise RateLimitExceeded(max(retry_after, 0.1))

        await self._redis.zadd(redis_key, {uuid.uuid4().hex: now})
        await self._redis.expire(redis_key, int(self._window_seconds) + 1)
