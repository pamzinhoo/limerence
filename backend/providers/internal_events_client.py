from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime

import aiohttp

from core.events import LicenseEventPayload, SubscriptionEventEnvelope
from core.logger import get_logger

logger = get_logger("internal_events_client")

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class InternalEventsClient:
    """Canal HTTP autenticado Backend -> Bot (`/internal/*`, ver
    bot/api/routes/internal_routes.py). Substitui o `EventBus` in-process:
    onde antes `LicenseService` publicava num pub/sub do mesmo processo,
    agora faz um POST assinado por HMAC-SHA256 pro processo do bot.

    Best-effort de proposito, igual o EventBus era (handler que falha nunca
    derrubava o publisher nem os outros handlers): o estado de dominio (ex.:
    License) ja foi commitado no banco antes desta chamada. Falha de rede,
    timeout ou 5xx aqui nunca propaga — so loga erro e segue. O pior caso e o
    Discord ficar temporariamente sem o cargo atualizado; o job de
    reconciliacao periodico do bot (license_reconciliation.py, ja existe,
    roda a cada 60min) e a rede de seguranca pra esse cenario, exatamente como
    era antes desta mudanca.
    """

    def __init__(self, base_url: str, secret: str, *, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret.encode("utf-8")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    def _sign(self, timestamp: str, raw_body: bytes) -> str:
        manifest = f"{timestamp}.".encode() + raw_body
        return hmac.new(self._secret, manifest, hashlib.sha256).hexdigest()

    @staticmethod
    def _json_default(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        raise TypeError(f"Objeto nao serializavel: {value!r}")

    async def _post(self, path: str, body: dict[str, object]) -> None:
        raw_body = json.dumps(body, default=self._json_default).encode("utf-8")
        url = f"{self._base_url}{path}"

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-Internal-Timestamp": timestamp,
                "X-Internal-Signature": self._sign(timestamp, raw_body),
            }
            should_retry = False
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(url, data=raw_body, headers=headers) as response:
                        if response.status < 400:
                            return
                        if response.status in _RETRYABLE_STATUS and not is_last_attempt:
                            should_retry = True
                        else:
                            text = await response.text()
                            logger.error(
                                "Falha ao notificar evento interno (%s): HTTP %s — %s",
                                path, response.status, text,
                            )
                            return
            except (TimeoutError, aiohttp.ClientError) as exc:
                if is_last_attempt:
                    logger.error(
                        "Falha ao notificar evento interno (%s) apos %d tentativas: %s", path, attempt, exc
                    )
                    return
                should_retry = True
                logger.warning(
                    "Tentativa %d/%d falhou pra %s: %s — retry em %.1fs",
                    attempt, _MAX_ATTEMPTS, path, exc, _BACKOFF_SECONDS[attempt - 1],
                )

            if should_retry:
                await asyncio.sleep(_BACKOFF_SECONDS[attempt - 1])

    async def notify_license_event(self, payload: LicenseEventPayload) -> None:
        await self._post("/internal/license-events", asdict(payload))

    async def notify_player_verified(self, discord_id: int) -> None:
        """POST /internal/player-verified — dispara depois de um login com
        Discord bem-sucedido no launcher, pro bot conceder o cargo de
        verificado (GuildSettings.verified_role_id, configurado em
        /config -> Cargos) em qualquer guild onde o membro estiver e o cargo
        estiver configurado. Best-effort, mesmo padrao dos outros eventos."""
        await self._post("/internal/player-verified", {"discord_id": discord_id})

    async def notify_subscription_event(self, event: SubscriptionEventEnvelope) -> None:
        """POST /internal/subscription-events — endpoint ainda nao existe no
        bot (Fase 3D-2, nao implementada). Ate la, esta chamada sempre recebe
        404, cai no ramo "nao retryable" de `_post` (loga erro, nao tenta de
        novo) e retorna normal — mesma resiliencia ja validada com
        notify_license_event, publicar pra um consumidor que ainda nao existe
        e seguro."""
        await self._post("/internal/subscription-events", asdict(event))
