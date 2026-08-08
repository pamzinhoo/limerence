from __future__ import annotations

import os
from typing import Protocol

from core.logger import get_logger
from core.rate_limiter import RateLimiter

logger = get_logger("rate_limiter_factory")


class SupportsHit(Protocol):
    async def hit(self, key: str) -> None: ...


def create_rate_limiter(*, max_hits: int, window_seconds: float, key_prefix: str = "ratelimit") -> SupportsHit:
    """Fabrica usada em todo lugar que hoje instancia `RateLimiter(...)`
    direto (module-level, nos routers) — mesma assinatura de chamada, troca
    só a implementação: `REDIS_URL` configurado e pacote `redis` instalado
    -> `RedisRateLimiter` (compartilhado, sobrevive a restart, escala pra
    multiplas instancias); caso contrário -> `RateLimiter` in-memory de
    sempre (fallback seguro, mesmo comportamento de hoje). Le `REDIS_URL`
    direto do ambiente (não via `Settings`) de propósito: os limiters são
    criados na importação do módulo, antes de qualquer composition root
    montar `Settings`."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return RateLimiter(max_hits=max_hits, window_seconds=window_seconds)

    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning(
            "REDIS_URL configurado mas o pacote 'redis' nao esta instalado — "
            "usando rate limiter em memoria (adicione 'redis' ao requirements.txt)."
        )
        return RateLimiter(max_hits=max_hits, window_seconds=window_seconds)

    from core.redis_rate_limiter import RedisRateLimiter

    client = redis.from_url(redis_url, decode_responses=True)
    return RedisRateLimiter(client, max_hits=max_hits, window_seconds=window_seconds, key_prefix=key_prefix)
