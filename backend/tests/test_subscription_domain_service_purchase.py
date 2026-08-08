from __future__ import annotations

import contextlib
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from database.models.payment import PaymentHistory, PaymentStatus
from database.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from services.subscription_domain_service import SubscriptionDomainService


def _database() -> MagicMock:
    database = MagicMock()

    @asynccontextmanager
    async def _session_cm():
        yield MagicMock()

    database.session = _session_cm
    return database


def _service(payment_service: AsyncMock) -> SubscriptionDomainService:
    return SubscriptionDomainService(
        _database(), payment_service, license_service=AsyncMock(), coupon_service=AsyncMock()
    )


class TestStartPurchaseIdempotency:
    @patch("services.subscription_domain_service.SubscriptionRepository")
    async def test_replays_existing_payment_without_charging_again(self, sub_repo_cls) -> None:
        """Retry HTTP da mesma tentativa (BackendClient reenvia com o MESMO
        idempotency_key apos timeout/5xx) nao pode gerar uma segunda cobranca
        no gateway — a chave ja usada devolve o resultado persistido."""
        idempotency_key = str(uuid.uuid4())
        subscription = Subscription(
            guild_id=1, user_id=2, plan_id=uuid.uuid4(), status=SubscriptionStatus.PENDING,
            billing_cycle=BillingCycle.MONTHLY, provider="manual", external_reference="ref",
        )
        subscription.id = uuid.uuid4()
        existing_payment = PaymentHistory(
            guild_id=1, user_id=2, plan_id=uuid.uuid4(), provider="manual", external_id="ext-existing",
            purchase_idempotency_key=idempotency_key, amount=1990, currency="BRL",
            status=PaymentStatus.PENDING,
        )
        existing_payment.id = uuid.uuid4()
        existing_payment.subscription_id = subscription.id

        payment_service = AsyncMock()
        payment_service.get_by_purchase_idempotency_key = AsyncMock(return_value=existing_payment)
        payment_service.charge = AsyncMock()  # nao pode ser chamado

        sub_repo_cls.return_value.get_by_id = AsyncMock(return_value=subscription)

        service = _service(payment_service)
        plan = MagicMock(price_monthly=1990, price_yearly=None, price_one_time=None)

        result_subscription, result_payment, result_charge = await service.start_purchase(
            1, 2, plan, BillingCycle.MONTHLY, idempotency_key=idempotency_key
        )

        assert result_subscription is subscription
        assert result_payment is existing_payment
        assert result_charge.external_id == "ext-existing"
        payment_service.charge.assert_not_called()

    async def test_no_idempotency_key_skips_replay_check(self) -> None:
        from services.subscription_domain_service import MissingPriceError

        payment_service = AsyncMock()
        payment_service.get_by_purchase_idempotency_key = AsyncMock()
        service = _service(payment_service)
        plan = MagicMock(price_monthly=None, price_yearly=None, price_one_time=None)

        with contextlib.suppress(MissingPriceError):
            await service.start_purchase(1, 2, plan, BillingCycle.MONTHLY, idempotency_key=None)

        payment_service.get_by_purchase_idempotency_key.assert_not_called()
