from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from database.models.subscription_renewal import SubscriptionMessageType
from services.subscription_renewal_engine_service import (
    REMINDER_TYPE_EXPIRED,
    SubscriptionRenewalEngineService,
    days_left_until,
)


def test_days_left_rounds_up_so_a_daily_cycle_never_skips_a_reminder() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    # faltando 6 dias e 23h ainda conta como "7 dias antes"
    assert days_left_until(now + timedelta(days=6, hours=23), now) == 7
    assert days_left_until(now + timedelta(days=1), now) == 1
    assert days_left_until(now + timedelta(hours=1), now) == 1
    assert days_left_until(now - timedelta(hours=1), now) == 0


def _database() -> MagicMock:
    database = MagicMock()

    @asynccontextmanager
    async def _session_cm():
        yield MagicMock()

    database.session = _session_cm
    return database


def _settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.enabled = True
    settings.grace_period_days = 0
    settings.continue_reminders_during_grace = False
    settings.remove_roles_on_expire = True
    settings.remove_benefits_on_expire = True
    settings.end_subscription_on_expire = True
    settings.send_dm_on_removal = True
    settings.notify_via_dm = True
    settings.notify_via_channel = False
    settings.renewal_channel_id = None
    settings.log_audit = True
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _subscription(*, period_end: datetime, guild_id: int = 1) -> MagicMock:
    sub = MagicMock()
    sub.id = uuid.uuid4()
    sub.guild_id = guild_id
    sub.user_id = 999
    sub.plan_id = uuid.uuid4()
    sub.current_period_end = period_end
    return sub


def _plan(plan_id: uuid.UUID) -> MagicMock:
    plan = MagicMock()
    plan.id = plan_id
    plan.name = "VIP"
    plan.role_id = 555
    plan.emoji = "💎"
    plan.price_monthly = 1990
    plan.price_yearly = None
    plan.price_one_time = None
    return plan


def _engine(config_service, subscription_domain_service) -> SubscriptionRenewalEngineService:
    return SubscriptionRenewalEngineService(_database(), config_service, subscription_domain_service)


class TestRunCheckCycle:
    async def test_disabled_settings_returns_no_notifications(self) -> None:
        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings(enabled=False))
        engine = _engine(config, AsyncMock())

        notifications = await engine.run_check_cycle(1)

        assert notifications == []

    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_sends_day_reminder_when_days_left_matches(
        self, sub_repo_cls, plan_repo_cls, reminder_repo_cls
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now + timedelta(days=7))
        plan = _plan(subscription.plan_id)

        sub_repo_cls.return_value.list_active_with_period = AsyncMock(return_value=[subscription])
        plan_repo_cls.return_value.list_by_guild = AsyncMock(return_value=[plan])
        reminder_repo_cls.return_value.reserve = AsyncMock(return_value=uuid.uuid4())

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings())
        reminder_day = MagicMock(days_before=7, enabled=True)
        config.list_reminder_days = AsyncMock(return_value=[reminder_day])
        config.get_message_content = AsyncMock(return_value="Faltam {days_left} dias")
        config.list_buttons = AsyncMock(return_value=[])

        engine = _engine(config, AsyncMock())
        notifications = await engine.run_check_cycle(1, now=now)

        assert len(notifications) == 1
        assert notifications[0].message_type == SubscriptionMessageType.LAST_REMINDER.value
        assert notifications[0].days_left == 7
        reminder_repo_cls.return_value.reserve.assert_awaited_once()

    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_duplicate_reservation_skips_notification(
        self, sub_repo_cls, plan_repo_cls, reminder_repo_cls
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now + timedelta(days=7))
        plan = _plan(subscription.plan_id)

        sub_repo_cls.return_value.list_active_with_period = AsyncMock(return_value=[subscription])
        plan_repo_cls.return_value.list_by_guild = AsyncMock(return_value=[plan])
        reminder_repo_cls.return_value.reserve = AsyncMock(return_value=None)  # ja reservado

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings())
        config.list_reminder_days = AsyncMock(return_value=[MagicMock(days_before=7, enabled=True)])

        engine = _engine(config, AsyncMock())
        notifications = await engine.run_check_cycle(1, now=now)

        assert notifications == []

    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_expired_subscription_calls_expire_and_returns_notification(
        self, sub_repo_cls, plan_repo_cls, reminder_repo_cls
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now - timedelta(days=1))
        plan = _plan(subscription.plan_id)

        sub_repo_cls.return_value.list_active_with_period = AsyncMock(return_value=[subscription])
        plan_repo_cls.return_value.list_by_guild = AsyncMock(return_value=[plan])
        reminder_repo_cls.return_value.reserve = AsyncMock(return_value=uuid.uuid4())

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings(grace_period_days=0))
        config.list_reminder_days = AsyncMock(return_value=[])
        config.get_message_content = AsyncMock(return_value="Sua assinatura expirou")
        config.list_buttons = AsyncMock(return_value=[])

        subscription_domain_service = AsyncMock()
        engine = _engine(config, subscription_domain_service)

        notifications = await engine.run_check_cycle(1, now=now)

        assert len(notifications) == 1
        assert notifications[0].message_type == SubscriptionMessageType.EXPIRED.value
        assert notifications[0].reason == REMINDER_TYPE_EXPIRED
        assert notifications[0].benefits_removed is True
        subscription_domain_service.expire_subscription.assert_awaited_once_with(
            subscription.id, remove_role=True, end_subscription=True
        )

    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_grace_period_starts_without_expiring(
        self, sub_repo_cls, plan_repo_cls, reminder_repo_cls
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now - timedelta(hours=1))
        plan = _plan(subscription.plan_id)

        sub_repo_cls.return_value.list_active_with_period = AsyncMock(return_value=[subscription])
        plan_repo_cls.return_value.list_by_guild = AsyncMock(return_value=[plan])
        reminder_repo_cls.return_value.reserve = AsyncMock(return_value=uuid.uuid4())

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings(grace_period_days=3))
        config.list_reminder_days = AsyncMock(return_value=[])
        config.get_message_content = AsyncMock(return_value="Periodo de carencia")
        config.list_buttons = AsyncMock(return_value=[])

        subscription_domain_service = AsyncMock()
        engine = _engine(config, subscription_domain_service)

        notifications = await engine.run_check_cycle(1, now=now)

        assert len(notifications) == 1
        assert notifications[0].message_type == SubscriptionMessageType.GRACE_PERIOD.value
        subscription_domain_service.expire_subscription.assert_not_called()


class TestHandleRenewed:
    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_builds_notification_when_not_already_sent(
        self, sub_repo_cls, plan_repo_cls, reminder_repo_cls
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now + timedelta(days=30))
        plan = _plan(subscription.plan_id)

        sub_repo_cls.return_value.get_by_id = AsyncMock(return_value=subscription)
        plan_repo_cls.return_value.get_by_id = AsyncMock(return_value=plan)
        reminder_repo_cls.return_value.exists = AsyncMock(return_value=False)
        reminder_repo_cls.return_value.reserve = AsyncMock(return_value=uuid.uuid4())

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings())
        config.get_message_content = AsyncMock(return_value="Renovado!")
        config.list_buttons = AsyncMock(return_value=[])

        engine = _engine(config, AsyncMock())
        notification = await engine.handle_renewed(subscription.id, now=now)

        assert notification is not None
        assert notification.message_type == SubscriptionMessageType.RENEWED.value

    @patch("services.subscription_renewal_engine_service.SubscriptionReminderRepository")
    @patch("services.subscription_renewal_engine_service.PlanRepository")
    @patch("services.subscription_renewal_engine_service.SubscriptionRepository")
    async def test_idempotent_when_already_sent(self, sub_repo_cls, plan_repo_cls, reminder_repo_cls) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        subscription = _subscription(period_end=now + timedelta(days=30))

        sub_repo_cls.return_value.get_by_id = AsyncMock(return_value=subscription)
        reminder_repo_cls.return_value.exists = AsyncMock(return_value=True)

        config = AsyncMock()
        config.get_settings = AsyncMock(return_value=_settings())

        engine = _engine(config, AsyncMock())
        notification = await engine.handle_renewed(subscription.id, now=now)

        assert notification is None
        reminder_repo_cls.return_value.reserve.assert_not_called()
