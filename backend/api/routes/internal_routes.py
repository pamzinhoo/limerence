from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import enforce_rate_limit, get_client_ip, verify_internal_signature
from api.schemas.internal import (
    CancelSubscriptionRequest,
    CancelSubscriptionResponse,
    ExpirePaymentResponse,
    FinalizeReminderRequest,
    HandleRenewedRequest,
    PendingExpiredPaymentResponse,
    ReconciliationDivergenceRequest,
    ReconciliationDivergenceResponse,
    ReconciliationPlanResponse,
    ReminderNotificationResponse,
    RenewalButtonResponse,
    RoleSyncPlanTargetResponse,
    RoleSyncTargetsResponse,
    RunRenewalCycleRequest,
    RunRenewalCycleResponse,
    SubscriptionReminderHistoryResponse,
    SubscriptionRenewalSettingsResponse,
    SubscriptionSummaryResponse,
)
from core.logger import get_logger
from core.rate_limiter_factory import create_rate_limiter
from database.repositories.subscription_renewal_repository import SubscriptionReminderRepository
from providers.base import PaymentGatewayError
from providers.manual import ManualProvider

if TYPE_CHECKING:
    from services.payment_service import PaymentService
    from services.plan_service import PlanService
    from services.player_service import PlayerService
    from services.subscription_domain_service import SubscriptionDomainService
    from services.subscription_renewal_config_service import SubscriptionRenewalConfigService
    from services.subscription_renewal_engine_service import SubscriptionRenewalEngineService

logger = get_logger("internal_routes")

# Defesa em profundidade: mesmo autenticado por HMAC, /internal/* nao fica
# sem limite — mesmo padrao do router equivalente no bot.
_internal_limiter = create_rate_limiter(max_hits=120, window_seconds=60, key_prefix='internal')


async def _enforce_internal_rate_limit(request: Request) -> None:
    await enforce_rate_limit(_internal_limiter, get_client_ip(request) or "unknown")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature), Depends(_enforce_internal_rate_limit)],
)

# Namespace do canal interno Bot -> Backend (direcao oposta ao
# InternalEventsClient, que e Backend -> Bot). O bot/api/routes/internal_routes.py
# original (POST /internal/license-events, POST /internal/reconcile) e logica
# que RECEBE eventos no processo do bot (dispatch pra
# bot.role_sync_service/bot.reconciliation_service) — nao faz sentido duplicar
# no backend, que e quem ENVIA esses eventos (ver InternalEventsClient, Fase
# 3C-1/3D-1). Os 3 endpoints abaixo sao os primeiros do canal reverso —
# prova de conceito da Fase 5, cobrindo exatamente `bot/cogs/subscriptions.py`.
#
# Ainda pendentes (fixados no desenho da Fase 3D-3, nao implementados aqui):
#   GET  /internal/subscriptions/reminders?guild_id=<int>
#   POST /internal/subscriptions/{id}/expire
#   GET/POST /internal/subscriptions/{id}/reminders


async def _resolve_plan_name(plan_service: PlanService, plan_id: uuid.UUID) -> str | None:
    plan = await plan_service.get_plan(plan_id)
    return plan.name if plan is not None else None


@router.get("/subscriptions/active", response_model=list[SubscriptionSummaryResponse])
async def active_subscriptions(
    request: Request, guild_id: int, user_id: int
) -> list[SubscriptionSummaryResponse]:
    """Equivalente a `bot/services/subscription_service.py::list_active_subscriptions`
    (agora `SubscriptionDomainService`), com o nome do plano ja resolvido —
    evita o bot precisar de uma segunda chamada por assinatura."""
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    plan_service: PlanService = request.app.state.plan_service
    subscriptions = await subscription_domain_service.list_active_subscriptions(guild_id, user_id)
    return [
        SubscriptionSummaryResponse(
            id=sub.id,
            plan_id=sub.plan_id,
            plan_name=await _resolve_plan_name(plan_service, sub.plan_id),
            status=sub.status.value,
            current_period_end=sub.current_period_end,
        )
        for sub in subscriptions
    ]


@router.get("/subscriptions/cancelable", response_model=list[SubscriptionSummaryResponse])
async def cancelable_subscriptions(
    request: Request, guild_id: int, user_id: int
) -> list[SubscriptionSummaryResponse]:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    plan_service: PlanService = request.app.state.plan_service
    subscriptions = await subscription_domain_service.list_cancelable_subscriptions(guild_id, user_id)
    return [
        SubscriptionSummaryResponse(
            id=sub.id,
            plan_id=sub.plan_id,
            plan_name=await _resolve_plan_name(plan_service, sub.plan_id),
            status=sub.status.value,
            current_period_end=sub.current_period_end,
        )
        for sub in subscriptions
    ]


@router.post("/subscriptions/{subscription_id}/cancel", response_model=CancelSubscriptionResponse)
async def cancel_subscription(
    request: Request, subscription_id: uuid.UUID, body: CancelSubscriptionRequest
) -> CancelSubscriptionResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    subscription = await subscription_domain_service.cancel_subscription(
        subscription_id,
        remove_role=body.remove_role,
        executor_id=body.executor_id,
        executor_name=body.executor_name,
    )
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "subscription_not_found", "message": "Assinatura nao encontrada."},
        )
    return CancelSubscriptionResponse(id=subscription.id, status=subscription.status.value)


@router.get("/payments/pending-expired", response_model=list[PendingExpiredPaymentResponse])
async def pending_expired_payments(
    request: Request, before: datetime
) -> list[PendingExpiredPaymentResponse]:
    """So leitura (Fase 5.3) — equivalente a `PaymentService.list_pending_expired`.
    Cancelamento no gateway e a escrita de `expire_payment` continuam locais
    no bot (`payment_expiration.py`), fora de escopo desta fase."""
    payment_service: PaymentService = request.app.state.payment_service
    payments = await payment_service.list_pending_expired(before=before)
    return [
        PendingExpiredPaymentResponse(
            id=p.id, guild_id=p.guild_id, external_id=p.external_id,
            provider=p.provider, expires_at=p.expires_at,
        )
        for p in payments
    ]


@router.post("/payments/{payment_id}/expire", response_model=ExpirePaymentResponse)
async def expire_payment(request: Request, payment_id: uuid.UUID) -> ExpirePaymentResponse:
    """Fecha a Fase 5.3: cancelamento no gateway + `expire_payment` agora
    decididos aqui — espelha exatamente `PaymentExpirationCog._expire` (bot),
    trocando so os services locais pelos do backend. O bot continua o
    scheduler (`@tasks.loop`), o backend decide o que fazer com cada
    pagamento vencido."""
    payment_service: PaymentService = request.app.state.payment_service
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service

    payment = await payment_service.get(payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "payment_not_found", "message": "Pagamento nao encontrado."},
        )

    provider = await payment_service.resolve_provider(payment.guild_id)
    if not isinstance(provider, ManualProvider) and payment.external_id:
        try:
            await payment_service.cancel(payment.external_id, provider)
        except PaymentGatewayError:
            logger.warning("Nao foi possivel cancelar pagamento %s no gateway (best-effort).", payment_id)

    expired = await subscription_domain_service.expire_payment(payment_id)
    return ExpirePaymentResponse(expired=expired)


@router.get(
    "/subscription-renewal/enabled-settings", response_model=list[SubscriptionRenewalSettingsResponse]
)
async def enabled_subscription_renewal_settings(
    request: Request,
) -> list[SubscriptionRenewalSettingsResponse]:
    """So leitura (Fase 5.4) — equivalente a
    `SubscriptionRenewalConfigService.list_enabled_settings`, usada pelo bot
    so pro throttle por guild do loop de renovacao. O motor de decisao
    (calculo de dias/carencia, DM/embed) continua local no bot ate a
    migracao completa (ver docs/migracao-bot-backend.md#fase-54)."""
    config_service: SubscriptionRenewalConfigService = request.app.state.subscription_renewal_config_service
    settings_rows = await config_service.list_enabled_settings()
    return [
        SubscriptionRenewalSettingsResponse(guild_id=s.guild_id, check_interval_hours=s.check_interval_hours)
        for s in settings_rows
    ]


@router.get("/role-sync/targets", response_model=RoleSyncTargetsResponse)
async def role_sync_targets(
    request: Request, player_id: uuid.UUID, product_id: uuid.UUID
) -> RoleSyncTargetsResponse:
    """So leitura (Fase 5.6) — equivalente ao que `RoleSyncService.handle_license_event`
    fazia direto no banco (`PlayerRepository.get_by_id` + `PlanRepository.list_by_product`).
    Backend continua autoridade de Player/Plan; o bot so aplica o
    grant/revoke de cargo no Discord com o resultado desta consulta."""
    player_service: PlayerService = request.app.state.player_service
    plan_service: PlanService = request.app.state.plan_service
    discord_id = await player_service.get_discord_id(player_id)
    plans = await plan_service.list_plans_by_product(product_id)
    return RoleSyncTargetsResponse(
        discord_id=discord_id,
        plans=[
            RoleSyncPlanTargetResponse(plan_id=p.id, guild_id=p.guild_id, role_id=p.role_id, name=p.name)
            for p in plans
        ],
    )


@router.get("/reconciliation/guild-plans", response_model=list[ReconciliationPlanResponse])
async def reconciliation_guild_plans(request: Request, guild_id: int) -> list[ReconciliationPlanResponse]:
    """So leitura (Fase Consolidacao) — equivalente ao que
    `ReconciliationService.reconcile_guild` (bot) fazia com
    `PlanRepository.list_by_guild` direto no banco. So devolve planos com
    `product_id`/`role_id` (os unicos elegiveis a reconciliacao de licenca —
    planos legados sem Product nao entram aqui)."""
    plan_service: PlanService = request.app.state.plan_service
    plans = await plan_service.list_plans(guild_id)
    return [
        ReconciliationPlanResponse(
            plan_id=p.id, guild_id=p.guild_id, role_id=p.role_id, product_id=p.product_id, name=p.name
        )
        for p in plans
        if p.product_id is not None and p.role_id is not None
    ]


@router.post("/reconciliation/divergence", response_model=ReconciliationDivergenceResponse)
async def reconciliation_divergence(
    request: Request, body: ReconciliationDivergenceRequest
) -> ReconciliationDivergenceResponse:
    """Equivalente as duas queries batched que `ReconciliationService._reconcile_plan`
    (bot) fazia direto no banco (`PlayerRepository`/`LicenseRepository`).
    Backend decide quem tem/nao tem License ativa; o bot so aplica
    grant/revoke de cargo Discord com o resultado (membership de guild so
    existe no cache do bot, nao migra)."""
    player_service: PlayerService = request.app.state.player_service
    divergence = await player_service.resolve_reconciliation_divergence(
        body.product_id, body.role_member_discord_ids
    )
    return ReconciliationDivergenceResponse(
        revoke_discord_ids=divergence.revoke_discord_ids,
        active_license_discord_ids=divergence.active_license_discord_ids,
    )


def _notification_response(n) -> ReminderNotificationResponse:
    return ReminderNotificationResponse(
        reminder_id=n.reminder_id,
        subscription_id=n.subscription_id,
        guild_id=n.guild_id,
        user_id=n.user_id,
        message_type=n.message_type,
        days_left=n.days_left,
        period_end=n.period_end,
        grace_days=n.grace_days,
        allow_dm=n.allow_dm,
        notify_via_dm=n.notify_via_dm,
        notify_via_channel=n.notify_via_channel,
        renewal_channel_id=n.renewal_channel_id,
        plan_id=n.plan_id,
        plan_name=n.plan_name,
        plan_role_id=n.plan_role_id,
        plan_emoji=n.plan_emoji,
        plan_price_monthly=n.plan_price_monthly,
        plan_price_yearly=n.plan_price_yearly,
        plan_price_one_time=n.plan_price_one_time,
        template=n.template,
        log_audit=n.log_audit,
        reason=n.reason,
        benefits_removed=n.benefits_removed,
        buttons=[
            RenewalButtonResponse(
                key=b.key, enabled=b.enabled, label=b.label, emoji=b.emoji, position=b.position
            )
            for b in n.buttons
        ],
    )


@router.post("/subscription-renewal/run-cycle", response_model=RunRenewalCycleResponse)
async def run_renewal_cycle(request: Request, body: RunRenewalCycleRequest) -> RunRenewalCycleResponse:
    """Fase Final: motor de decisao inteiro (`bot/services/subscription_reminder_service.py`)
    migrado pro backend. Bot so chama isto do `@tasks.loop`, renderiza cada
    `ReminderNotification` com `discord.Member`/`discord.Guild` reais, entrega
    e confirma via `.../reminders/{id}/finalize`."""
    engine: SubscriptionRenewalEngineService = request.app.state.subscription_renewal_engine_service
    notifications = await engine.run_check_cycle(body.guild_id)
    return RunRenewalCycleResponse(notifications=[_notification_response(n) for n in notifications])


@router.post("/subscription-renewal/reminders/{reminder_id}/finalize", status_code=status.HTTP_204_NO_CONTENT)
async def finalize_renewal_reminder(
    request: Request, reminder_id: uuid.UUID, body: FinalizeReminderRequest
) -> None:
    engine: SubscriptionRenewalEngineService = request.app.state.subscription_renewal_engine_service
    await engine.finalize_reminder(reminder_id, delivery_status=body.delivery_status)


@router.post("/subscription-renewal/renewed-notification", response_model=ReminderNotificationResponse | None)
async def renewed_notification(
    request: Request, body: HandleRenewedRequest
) -> ReminderNotificationResponse | None:
    """Chamado pelo bot ao receber o evento `SUBSCRIPTION_RENEWED` (ja
    consumido desde a Fase 5.2 pra conceder cargo) — pede o ledger/texto da
    mensagem de "renovado com sucesso". `None` quando desabilitado ou ja
    enviado pro mesmo periodo (idempotente)."""
    engine: SubscriptionRenewalEngineService = request.app.state.subscription_renewal_engine_service
    notification = await engine.handle_renewed(body.subscription_id)
    return _notification_response(notification) if notification is not None else None


@router.get(
    "/subscription-renewal/{subscription_id}/reminders",
    response_model=list[SubscriptionReminderHistoryResponse],
)
async def subscription_reminder_history(
    request: Request, subscription_id: uuid.UUID
) -> list[SubscriptionReminderHistoryResponse]:
    """Historico do ledger pro painel de staff (`subscription_renewal_view.py`,
    bot) — leitura pura, equivalente a `SubscriptionReminderRepository.list_by_subscription`
    que o bot fazia direto no banco."""
    database = request.app.state.database
    async with database.session() as session:
        reminders = await SubscriptionReminderRepository(session).list_by_subscription(subscription_id)
    return [
        SubscriptionReminderHistoryResponse(
            id=r.id, reminder_type=r.reminder_type, period_end=r.period_end,
            sent_at=r.sent_at, delivery_status=r.delivery_status,
        )
        for r in reminders
    ]
