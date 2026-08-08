from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

# Nomes de evento publicados no EventBus — espelham LicenseEventType (mesmos
# 5 estados), mas como string solta (nao o enum) pra RoleSyncService e o
# endpoint HTTP interno (api/routes/internal_routes.py) nao precisarem
# importar o model de dominio inteiro so pra assinar/despachar eventos.
LICENSE_CREATED = "LICENSE_CREATED"
LICENSE_RENEWED = "LICENSE_RENEWED"
LICENSE_REVOKED = "LICENSE_REVOKED"
LICENSE_EXPIRED = "LICENSE_EXPIRED"
LICENSE_REACTIVATED = "LICENSE_REACTIVATED"

# Quem recebe estes eventos deve CONCEDER o cargo (o Product passou a estar
# coberto por uma License ACTIVE).
LICENSE_GRANT_EVENTS = (LICENSE_CREATED, LICENSE_RENEWED, LICENSE_REACTIVATED)
# Quem recebe estes eventos deve REMOVER o cargo.
LICENSE_REVOKE_EVENTS = (LICENSE_REVOKED, LICENSE_EXPIRED)


@dataclass(frozen=True, slots=True)
class LicenseEventPayload:
    """Payload publicado no EventBus (e aceito por POST /internal/license-events)
    toda vez que uma License muda de status. E o unico jeito pelo qual o bot
    fica sabendo que precisa conceder/remover um cargo — nunca reage a evento
    do Discord (member update, role manual) como fonte de verdade."""

    license_id: uuid.UUID
    player_id: uuid.UUID
    product_id: uuid.UUID
    status: str
    event_type: str
    occurred_at: datetime


# --- eventos de assinatura (Fase 3D) ----------------------------------------
#
# Catalogo fixado no desenho da Fase 3D (docs/migracao-bot-backend.md).
# SUBSCRIPTION_REMINDER esta reservado para o SubscriptionReminderService
# (Fase 3D-3, ainda no bot, nao migrado) — nao e publicado por
# SubscriptionDomainService/SubscriptionNotificationPublisher nesta fase.
SUBSCRIPTION_CREATED = "SUBSCRIPTION_CREATED"
SUBSCRIPTION_RENEWED = "SUBSCRIPTION_RENEWED"
SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"
SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
SUBSCRIPTION_PAYMENT_REJECTED = "SUBSCRIPTION_PAYMENT_REJECTED"
SUBSCRIPTION_PAYMENT_PENDING = "SUBSCRIPTION_PAYMENT_PENDING"
SUBSCRIPTION_PAYMENT_CANCELED = "SUBSCRIPTION_PAYMENT_CANCELED"
SUBSCRIPTION_PAYMENT_EXPIRED = "SUBSCRIPTION_PAYMENT_EXPIRED"
SUBSCRIPTION_REFUNDED = "SUBSCRIPTION_REFUNDED"
SUBSCRIPTION_CHARGEBACK = "SUBSCRIPTION_CHARGEBACK"
SUBSCRIPTION_REMINDER = "SUBSCRIPTION_REMINDER"  # reservado, ver nota acima

SUBSCRIPTION_EVENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class SubscriptionEventEnvelope:
    """Envelope publicado em POST /internal/subscription-events (endpoint
    ainda nao existe no bot — Fase 3D-2). `aggregate_id` e sempre o
    subscription_id; `payload` carrega os dados especificos do evento
    (guild_id, user_id, plan_id, status, payment_id, executor_id/name,
    reason, metadata) — schema mais rico que LicenseEventPayload de proposito,
    ja nasce com identidade/versionamento de evento (event_id, version) que o
    catalogo LICENSE_* nao tem."""

    event_id: uuid.UUID
    event_type: str
    aggregate_id: uuid.UUID
    occurred_at: datetime
    version: int
    payload: dict[str, object] = field(default_factory=dict)
