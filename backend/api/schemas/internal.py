from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateDlcRequest(BaseModel):
    """Cadastro de DLC pelo painel admin do bot (`/config -> Monetizacao ->
    DLC -> Criar`). Cria Product(type=DLC) + Plan vinculado (product_id +
    role_id) na guild indicada. NAO concede nem revoga cargo de ninguem —
    isso continua sendo papel exclusivo de RoleSyncService/reconciliation,
    reagindo a quem ja tem/ganha o cargo depois. Aqui so nasce a relacao
    Product <-> Role."""

    guild_id: int
    slug: str
    name: str
    role_id: int
    description: str | None = None
    price_amount: int | None = None
    currency: str = "BRL"
    executor_id: int | None = None
    executor_name: str | None = None


class CreateDlcResponse(BaseModel):
    product_id: uuid.UUID
    plan_id: uuid.UUID
    slug: str
    name: str
    role_id: int


class PublishManifestEntryRequest(BaseModel):
    """Registra uma versao de conteudo ja enviada ao storage (R2/S3/B2) pelo
    fluxo de publicacao (fora desta rota — upload em si nao e HTTP via bot,
    ver docs/LAUNCHER_API_CONTRACT.md). Esta rota so grava metadados e marca
    a versao como atual."""

    version: str
    sha256: str
    size_bytes: int
    storage_path: str
    entry_type: str = "full"
    depends_on: list[str] = []
    release_notes: str | None = None
    executor_id: int | None = None


class PublishManifestEntryResponse(BaseModel):
    manifest_entry_id: uuid.UUID
    product_id: uuid.UUID
    version: str
    sha256: str
    entry_type: str
    is_current: bool


class LicenseEventRequest(BaseModel):
    """Espelha core.events.LicenseEventPayload — formato que um Backend
    desacoplado do processo do bot usaria pra empurrar um evento de licenca
    via HTTP em vez de EventBus in-process."""

    license_id: uuid.UUID
    player_id: uuid.UUID
    product_id: uuid.UUID
    status: str
    event_type: str
    occurred_at: datetime


class GuildReconciliationResultResponse(BaseModel):
    guild_id: int
    roles_granted: int
    roles_removed: int
    errors: int


class ReconciliationReportResponse(BaseModel):
    guilds_checked: int
    roles_granted: int
    roles_removed: int
    errors: int
    per_guild: list[GuildReconciliationResultResponse]


# --- assinaturas (Fase 5 — bot/cogs/subscriptions.py -> BackendClient) -----


class SubscriptionSummaryResponse(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str | None
    status: str
    current_period_end: datetime | None


class CancelSubscriptionRequest(BaseModel):
    executor_id: int | None = None
    executor_name: str | None = None
    remove_role: bool = True


class CancelSubscriptionResponse(BaseModel):
    id: uuid.UUID
    status: str


# --- pagamentos (Fase 5.3 — bot/cogs/payment_expiration.py -> BackendClient,
# so a leitura; expiracao/cancelamento no gateway seguem locais no bot) ------


class PendingExpiredPaymentResponse(BaseModel):
    id: uuid.UUID
    guild_id: int
    external_id: str | None
    provider: str
    expires_at: datetime | None


class ExpirePaymentResponse(BaseModel):
    expired: bool


# --- renovacao de assinaturas (Fase 5.4 — bot/cogs/subscription_renewal.py
# -> BackendClient, so a leitura do throttle por guild; o motor de decisao
# (SubscriptionReminderService: calculo de dias/carencia + DM/embed) continua
# local no bot, ver docs/migracao-bot-backend.md#fase-54) --------------------


class SubscriptionRenewalSettingsResponse(BaseModel):
    guild_id: int
    check_interval_hours: int


# --- sincronizacao de cargo (Fase 5.6 — bot/services/role_sync_service.py
# para de ler Player/Plan direto do banco compartilhado) -------------------


class RoleSyncPlanTargetResponse(BaseModel):
    plan_id: uuid.UUID
    guild_id: int
    role_id: int | None
    name: str


class RoleSyncTargetsResponse(BaseModel):
    discord_id: int | None
    plans: list[RoleSyncPlanTargetResponse]


# --- reconciliacao em lote (Fase Consolidacao — bot/services/reconciliation_service.py
# para de ler Player/License/Plan direto do banco compartilhado) -----------


class ReconciliationPlanResponse(BaseModel):
    plan_id: uuid.UUID
    guild_id: int
    role_id: int
    product_id: uuid.UUID
    name: str


class ReconciliationDivergenceRequest(BaseModel):
    product_id: uuid.UUID
    role_member_discord_ids: list[int]


class ReconciliationDivergenceResponse(BaseModel):
    revoke_discord_ids: list[int]
    active_license_discord_ids: list[int]


# --- motor de renovacao (Fase Final — bot/services/subscription_reminder_service.py
# migra inteiro; bot vira consumidor de notificacoes) ------------------------


class RenewalButtonResponse(BaseModel):
    key: str
    enabled: bool
    label: str | None
    emoji: str | None
    position: int


class ReminderNotificationResponse(BaseModel):
    reminder_id: uuid.UUID
    subscription_id: uuid.UUID
    guild_id: int
    user_id: int
    message_type: str
    days_left: int
    period_end: datetime | None
    grace_days: int
    allow_dm: bool
    notify_via_dm: bool
    notify_via_channel: bool
    renewal_channel_id: int | None
    plan_id: uuid.UUID
    plan_name: str
    plan_role_id: int | None
    plan_emoji: str | None
    plan_price_monthly: int | None
    plan_price_yearly: int | None
    plan_price_one_time: int | None
    template: str
    log_audit: bool
    buttons: list[RenewalButtonResponse]
    reason: str | None = None
    benefits_removed: bool = False


class RunRenewalCycleRequest(BaseModel):
    guild_id: int


class RunRenewalCycleResponse(BaseModel):
    notifications: list[ReminderNotificationResponse]


class FinalizeReminderRequest(BaseModel):
    delivery_status: str


class HandleRenewedRequest(BaseModel):
    subscription_id: uuid.UUID


class SubscriptionReminderHistoryResponse(BaseModel):
    id: uuid.UUID
    reminder_type: str
    period_end: datetime | None
    sent_at: datetime
    delivery_status: str
