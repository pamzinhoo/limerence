from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.events import SUBSCRIPTION_EVENT_VERSION, SubscriptionEventEnvelope
from core.logger import get_logger
from database.models.subscription import Subscription
from providers.internal_events_client import InternalEventsClient

logger = get_logger("subscription_notification_publisher")


class SubscriptionNotificationPublisher:
    """Unica porta de saida do dominio de assinaturas — monta o envelope do
    evento e delega ao `InternalEventsClient` (mesmo Provider da Fase 3C-1,
    so ganhou um metodo novo: `notify_subscription_event`). Nao fala com
    Discord, nao decide regra de negocio, so publica o que
    `SubscriptionDomainService` manda depois de cada transicao de estado
    confirmada (commit ja feito).

    `internal_events_client=None` (default) mantem o publisher inofensivo —
    igual `LicenseService` com `internal_events_client=None`, util pra testes
    e para o SubscriptionDomainService funcionar isolado sem exigir o canal
    HTTP configurado."""

    def __init__(self, internal_events_client: InternalEventsClient | None = None) -> None:
        self._internal_events_client = internal_events_client

    async def publish(
        self,
        event_type: str,
        subscription: Subscription,
        *,
        payment_id: uuid.UUID | None = None,
        executor_id: int | None = None,
        executor_name: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self._internal_events_client is None:
            return
        envelope = SubscriptionEventEnvelope(
            event_id=uuid.uuid4(),
            event_type=event_type,
            aggregate_id=subscription.id,
            occurred_at=datetime.now(UTC),
            version=SUBSCRIPTION_EVENT_VERSION,
            payload={
                "subscription_id": subscription.id,
                "guild_id": subscription.guild_id,
                "user_id": subscription.user_id,
                # `discord_id` e alias explicito de `user_id` — Subscription
                # e guild-scoped e guarda o snowflake do Discord direto (nao
                # tem FK pra Player), diferente de License/LicenseEventPayload
                # (globais, player_id). Nomeado explicito aqui pra o Handler
                # do lado do bot nunca precisar adivinhar qual campo e o
                # discord_id de fato.
                "discord_id": subscription.user_id,
                # Subscription nao referencia Player (so existe pra planos
                # com Product vinculado, resolvido via LicenseService/
                # LicenseEventPayload em canal separado) — sempre None aqui,
                # mantido no payload so pra deixar explicito que foi
                # considerado, nao esquecido.
                "player_id": None,
                "plan_id": subscription.plan_id,
                "status": subscription.status.value,
                "payment_id": payment_id,
                "executor_id": executor_id,
                "executor_name": executor_name,
                "reason": reason,
                "metadata": metadata or {},
            },
        )
        await self._internal_events_client.notify_subscription_event(envelope)
