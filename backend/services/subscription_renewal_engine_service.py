from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from core.logger import get_logger
from database.database import Database
from database.models.plan import Plan
from database.models.subscription import Subscription
from database.models.subscription_renewal import (
    SubscriptionMessageType,
    SubscriptionRenewalSettings,
)
from database.repositories.plan_repository import PlanRepository
from database.repositories.subscription_renewal_repository import SubscriptionReminderRepository
from database.repositories.subscription_repository import SubscriptionRepository
from services.subscription_domain_service import SubscriptionDomainService
from services.subscription_renewal_config_service import SubscriptionRenewalConfigService

logger = get_logger("subscription_renewal_engine_service")

# chaves do livro-razao (SubscriptionReminder.reminder_type) — identicas as
# que existiam em bot/services/subscription_reminder_service.py
REMINDER_DAY_PREFIX = "day_"
REMINDER_TYPE_EXPIRED = "expired"
REMINDER_TYPE_GRACE_STARTED = "grace_started"
REMINDER_TYPE_GRACE_FINISHED = "grace_finished"
REMINDER_TYPE_RENEWED = "renewed"


def days_left_until(period_end: datetime, now: datetime) -> int:
    delta = period_end - now
    return math.ceil(delta.total_seconds() / 86400)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class RenewalButton:
    key: str
    enabled: bool
    label: str | None
    emoji: str | None
    position: int


@dataclass(frozen=True, slots=True)
class ReminderNotification:
    """Ingredientes pro bot montar e entregar a mensagem — nunca o texto
    final. `render_placeholders` precisa de `discord.Member`/`discord.Guild`/
    `discord.Role` reais (mention, nome, cargo) pra formatar `template`, e
    isso so existe no processo do bot. Backend decide QUANDO avisar e
    reserva o ledger; bot decide COMO (DM/canal/embed) e confirma de volta."""

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
    buttons: list[RenewalButton] = field(default_factory=list)
    reason: str | None = None
    benefits_removed: bool = False


class SubscriptionRenewalEngineService:
    """Motor de decisao da renovacao de assinaturas (Fase Final). Extraido
    metodo a metodo de `bot/services/subscription_reminder_service.py`:
    identifica assinaturas vencidas, calcula dias/carencia, reserva o
    livro-razao de idempotencia (`SubscriptionReminderRepository` — mesma
    tabela compartilhada de sempre, zero migracao de dado: bot e backend
    sempre apontaram pro mesmo Postgres) e decide expirar via
    `SubscriptionDomainService.expire_subscription` (ja existente desde a
    Fase 3D-1). Zero Discord aqui: devolve so `ReminderNotification` (dados
    crus) pro bot renderizar e entregar; o bot fecha o ciclo chamando
    `finalize_reminder` com o resultado real da entrega — o ledger so fecha
    depois da tentativa de entrega, nunca antes (mesma garantia do
    desenho original: uma falha de rede no meio do caminho nao duplica
    aviso nem perde a expiracao, porque a reserva ja aconteceu antes de
    qualquer efeito colateral)."""

    def __init__(
        self,
        database: Database,
        config_service: SubscriptionRenewalConfigService,
        subscription_domain_service: SubscriptionDomainService,
    ) -> None:
        self._database = database
        self._config = config_service
        self._subscriptions = subscription_domain_service

    # --- ciclo de checagem ---------------------------------------------------

    async def run_check_cycle(
        self, guild_id: int, *, now: datetime | None = None
    ) -> list[ReminderNotification]:
        now = now or datetime.now(UTC)
        settings = await self._config.get_settings(guild_id)
        if not settings.enabled:
            return []

        async with self._database.session() as session:
            subscriptions = await SubscriptionRepository(session).list_active_with_period(guild_id)
            plans = {p.id: p for p in await PlanRepository(session).list_by_guild(guild_id)}

        reminder_days = [d for d in await self._config.list_reminder_days(guild_id) if d.enabled]
        smallest = min((d.days_before for d in reminder_days), default=None)

        notifications: list[ReminderNotification] = []
        for subscription in subscriptions:
            plan = plans.get(subscription.plan_id)
            if plan is None:
                continue
            try:
                notifications.extend(
                    await self._process_subscription(subscription, plan, settings, reminder_days, smallest, now)
                )
            except Exception:
                logger.exception(
                    "Falha ao processar renovacao da assinatura %s (guild %s).", subscription.id, guild_id
                )
        return notifications

    async def _process_subscription(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        reminder_days: list,
        smallest_days_before: int | None,
        now: datetime,
    ) -> list[ReminderNotification]:
        assert subscription.current_period_end is not None
        period_end = _aware(subscription.current_period_end)
        days_left = days_left_until(period_end, now)

        if period_end > now:
            return await self._maybe_build_day_reminders(
                subscription, plan, settings, reminder_days, smallest_days_before, days_left, now, period_end
            )

        # --- venceu -----------------------------------------------------
        if settings.grace_period_days <= 0:
            return await self._finish(subscription, plan, settings, now, reason=REMINDER_TYPE_EXPIRED)

        grace_end = period_end + timedelta(days=settings.grace_period_days)
        if now < grace_end:
            notifications = await self._start_grace(subscription, plan, settings, period_end, now)
            if settings.continue_reminders_during_grace:
                notifications += await self._maybe_build_day_reminders(
                    subscription,
                    plan,
                    settings,
                    reminder_days,
                    smallest_days_before,
                    days_left_until(grace_end, now),
                    now,
                    grace_end,
                )
            return notifications

        return await self._finish(subscription, plan, settings, now, reason=REMINDER_TYPE_GRACE_FINISHED)

    async def _maybe_build_day_reminders(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        reminder_days: list,
        smallest_days_before: int | None,
        days_left: int,
        now: datetime,
        period_end: datetime,
    ) -> list[ReminderNotification]:
        notifications: list[ReminderNotification] = []
        for day in reminder_days:
            if day.days_before != days_left:
                continue
            is_last = smallest_days_before is not None and day.days_before == smallest_days_before
            message_type = SubscriptionMessageType.LAST_REMINDER if is_last else SubscriptionMessageType.REMINDER
            reminder_type = f"{REMINDER_DAY_PREFIX}{day.days_before}"
            reminder_id = await self._reserve(subscription, reminder_type, period_end, now)
            if reminder_id is None:
                continue  # ja reservado (enviado ou em progresso em outra execucao)
            notifications.append(
                await self._build_notification(
                    reminder_id, subscription, plan, settings, message_type,
                    days_left=days_left, period_end=period_end, allow_dm=True,
                )
            )
        return notifications

    async def _start_grace(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        period_end: datetime,
        now: datetime,
    ) -> list[ReminderNotification]:
        reminder_id = await self._reserve(subscription, REMINDER_TYPE_GRACE_STARTED, period_end, now)
        if reminder_id is None:
            return []
        notification = await self._build_notification(
            reminder_id, subscription, plan, settings, SubscriptionMessageType.GRACE_PERIOD,
            days_left=0, period_end=period_end, allow_dm=True,
        )
        return [notification]

    async def _finish(
        self,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        now: datetime,
        *,
        reason: str,
    ) -> list[ReminderNotification]:
        period_end = _aware(subscription.current_period_end)  # type: ignore[arg-type]
        reminder_id = await self._reserve(subscription, REMINDER_TYPE_EXPIRED, period_end, now)
        if reminder_id is None:
            return []

        notification = await self._build_notification(
            reminder_id, subscription, plan, settings, SubscriptionMessageType.EXPIRED,
            days_left=0, period_end=period_end, allow_dm=settings.send_dm_on_removal,
        )
        notification = replace(
            notification,
            reason=reason,
            benefits_removed=settings.remove_roles_on_expire or settings.remove_benefits_on_expire,
        )

        # Estado + revogacao de licenca/cargo (via evento SUBSCRIPTION_EXPIRED,
        # ja consumido pelo bot desde a Fase 5.2) nao dependem do resultado da
        # entrega da mensagem — mesmo comportamento do original (a mensagem
        # podia falhar e a assinatura expirava do mesmo jeito).
        await self._subscriptions.expire_subscription(
            subscription.id,
            remove_role=settings.remove_roles_on_expire or settings.remove_benefits_on_expire,
            end_subscription=settings.end_subscription_on_expire,
        )
        return [notification]

    # --- renovacao concluida --------------------------------------------------

    async def handle_renewed(
        self, subscription_id: uuid.UUID, *, now: datetime | None = None
    ) -> ReminderNotification | None:
        """Chamado pelo bot quando recebe o evento `SUBSCRIPTION_RENEWED`
        (publicado por `SubscriptionDomainService.renew_subscription`, Fase
        3D-1) — equivalente a `SubscriptionReminderService.handle_renewed`
        (bot, removido nesta fase). Idempotente pelo mesmo ledger."""
        now = now or datetime.now(UTC)
        async with self._database.session() as session:
            subscription = await SubscriptionRepository(session).get_by_id(subscription_id)
        if subscription is None or subscription.current_period_end is None:
            return None

        settings = await self._config.get_settings(subscription.guild_id)
        if not settings.enabled:
            return None

        period_end = _aware(subscription.current_period_end)
        async with self._database.session() as session:
            already_sent = await SubscriptionReminderRepository(session).exists(
                subscription.id, REMINDER_TYPE_RENEWED, period_end
            )
        if already_sent:
            return None

        async with self._database.session() as session:
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
        if plan is None:
            return None

        reminder_id = await self._reserve(subscription, REMINDER_TYPE_RENEWED, period_end, now)
        if reminder_id is None:
            return None

        return await self._build_notification(
            reminder_id, subscription, plan, settings, SubscriptionMessageType.RENEWED,
            days_left=days_left_until(period_end, now), period_end=period_end, allow_dm=True,
        )

    # --- ingredientes da notificacao ------------------------------------------

    async def _build_notification(
        self,
        reminder_id: uuid.UUID,
        subscription: Subscription,
        plan: Plan,
        settings: SubscriptionRenewalSettings,
        message_type: SubscriptionMessageType,
        *,
        days_left: int,
        period_end: datetime | None,
        allow_dm: bool,
    ) -> ReminderNotification:
        template = await self._config.get_message_content(subscription.guild_id, message_type)
        buttons = await self._config.list_buttons(subscription.guild_id)
        return ReminderNotification(
            reminder_id=reminder_id,
            subscription_id=subscription.id,
            guild_id=subscription.guild_id,
            user_id=subscription.user_id,
            message_type=message_type.value,
            days_left=days_left,
            period_end=period_end,
            grace_days=settings.grace_period_days,
            allow_dm=allow_dm,
            notify_via_dm=settings.notify_via_dm,
            notify_via_channel=settings.notify_via_channel,
            renewal_channel_id=settings.renewal_channel_id,
            plan_id=plan.id,
            plan_name=plan.name,
            plan_role_id=plan.role_id,
            plan_emoji=plan.emoji,
            plan_price_monthly=plan.price_monthly,
            plan_price_yearly=plan.price_yearly,
            plan_price_one_time=plan.price_one_time,
            template=template,
            log_audit=settings.log_audit,
            buttons=[
                RenewalButton(
                    key=b.key.value, enabled=b.enabled, label=b.label, emoji=b.emoji, position=b.position
                )
                for b in buttons
            ],
        )

    # --- livro-razao ------------------------------------------------------

    async def _reserve(
        self, subscription: Subscription, reminder_type: str, period_end: datetime | None, now: datetime
    ) -> uuid.UUID | None:
        async with self._database.session() as session:
            return await SubscriptionReminderRepository(session).reserve(
                guild_id=subscription.guild_id,
                subscription_id=subscription.id,
                reminder_type=reminder_type,
                period_end=period_end,
                now=now,
            )

    async def finalize_reminder(self, reminder_id: uuid.UUID, *, delivery_status: str) -> None:
        async with self._database.session() as session:
            await SubscriptionReminderRepository(session).finalize(reminder_id, delivery_status=delivery_status)
