from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from api.routes.shop_routes import router as shop_router
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from providers.base import ChargeResult
from providers.manual import ManualProvider
from services.coupon_service import CouponError
from services.subscription_domain_service import DuplicateSubscriptionError, MissingPriceError

_SECRET = "test-internal-secret"


def _sign(body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    manifest = f"{ts}.".encode() + body
    signature = hmac.new(_SECRET.encode(), manifest, hashlib.sha256).hexdigest()
    return {"X-Internal-Timestamp": ts, "X-Internal-Signature": signature}


def _plan(**overrides: object) -> MagicMock:
    plan = MagicMock()
    plan.id = uuid.uuid4()
    plan.name = "VIP"
    plan.emoji = "💎"
    plan.color = None
    plan.description = None
    plan.currency = "BRL"
    plan.price_monthly = 1990
    plan.price_yearly = None
    plan.price_one_time = None
    plan.role_id = 555
    plan.product_id = None
    plan.position = 0
    plan.is_recommended = False
    plan.is_active = True
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


def _payment(**overrides: object) -> PaymentHistory:
    payment = PaymentHistory(
        guild_id=1, user_id=2, plan_id=uuid.uuid4(), provider="manual", external_id="ext-1",
        amount=1990, currency="BRL", status=PaymentStatus.PENDING,
    )
    payment.id = uuid.uuid4()
    payment.created_at = datetime.now(UTC)
    payment.subscription_id = uuid.uuid4()
    for key, value in overrides.items():
        setattr(payment, key, value)
    return payment


def _subscription(**overrides: object) -> Subscription:
    sub = Subscription(
        guild_id=1, user_id=2, plan_id=uuid.uuid4(), status=SubscriptionStatus.PENDING,
        billing_cycle=BillingCycle.MONTHLY, provider="manual", external_reference="ref",
    )
    sub.id = uuid.uuid4()
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


class _App:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.app.state.settings = MagicMock(internal_api_secret=_SECRET)
        self.app.state.plan_service = AsyncMock()
        self.app.state.coupon_service = AsyncMock()
        self.app.state.payment_service = AsyncMock()
        self.app.state.subscription_domain_service = AsyncMock()
        self.app.include_router(shop_router)

    async def request(self, method: str, path: str, json_body: dict | None = None) -> httpx.Response:
        import json as jsonlib

        body = jsonlib.dumps(json_body).encode() if json_body is not None else b""
        headers = _sign(body)
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                method, path, content=body, headers={**headers, "Content-Type": "application/json"}
            )


@pytest.fixture
def api() -> _App:
    return _App()


class TestCatalog:
    async def test_returns_plans_with_benefits(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.list_plans = AsyncMock(return_value=[plan])
        api.app.state.plan_service.list_benefits = AsyncMock(return_value=[MagicMock(text="Acesso VIP")])

        response = await api.request("GET", "/internal/shop/catalog?guild_id=1")

        assert response.status_code == 200
        body = response.json()
        assert body["plans"][0]["name"] == "VIP"
        assert body["plans"][0]["benefits"] == ["Acesso VIP"]


class TestValidateCoupon:
    async def test_plan_not_found(self, api: _App) -> None:
        api.app.state.plan_service.get_plan = AsyncMock(return_value=None)

        response = await api.request(
            "POST", "/internal/shop/coupons/validate",
            {"guild_id": 1, "code": "X", "member_id": 2, "plan_id": str(uuid.uuid4()), "billing_cycle": "monthly"},
        )

        assert response.status_code == 404

    async def test_missing_price_for_cycle(self, api: _App) -> None:
        plan = _plan(price_monthly=None)
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)

        response = await api.request(
            "POST", "/internal/shop/coupons/validate",
            {"guild_id": 1, "code": "X", "member_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly"},
        )

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "missing_price"

    async def test_coupon_rejected_surfaces_message(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        api.app.state.coupon_service.validate_and_price = AsyncMock(
            side_effect=CouponError("Cupom expirado.")
        )

        response = await api.request(
            "POST", "/internal/shop/coupons/validate",
            {"guild_id": 1, "code": "X", "member_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly"},
        )

        assert response.status_code == 422
        assert response.json()["detail"]["message"] == "Cupom expirado."

    async def test_valid_coupon_returns_pricing(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        application = MagicMock(
            coupon=MagicMock(code="PROMO10"), original_amount=1990, discount_amount=199, final_amount=1791
        )
        api.app.state.coupon_service.validate_and_price = AsyncMock(return_value=application)

        response = await api.request(
            "POST", "/internal/shop/coupons/validate",
            {"guild_id": 1, "code": "promo10", "member_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["coupon_code"] == "PROMO10"
        assert body["final_amount"] == 1791


class TestStartPurchase:
    async def test_plan_not_found(self, api: _App) -> None:
        api.app.state.plan_service.get_plan = AsyncMock(return_value=None)

        response = await api.request(
            "POST", "/internal/shop/purchase/start",
            {
                "guild_id": 1, "user_id": 2, "plan_id": str(uuid.uuid4()), "billing_cycle": "monthly",
                "idempotency_key": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 404

    async def test_duplicate_subscription_returns_422(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        api.app.state.subscription_domain_service.start_purchase = AsyncMock(
            side_effect=DuplicateSubscriptionError("Você já possui uma assinatura ativa ou pendente para este plano.")
        )

        response = await api.request(
            "POST", "/internal/shop/purchase/start",
            {
                "guild_id": 1, "user_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly",
                "idempotency_key": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "purchase_rejected"

    async def test_missing_price_returns_422(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        api.app.state.subscription_domain_service.start_purchase = AsyncMock(
            side_effect=MissingPriceError("sem preco")
        )

        response = await api.request(
            "POST", "/internal/shop/purchase/start",
            {
                "guild_id": 1, "user_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly",
                "idempotency_key": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 422

    async def test_coupon_error_returns_422(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        api.app.state.subscription_domain_service.start_purchase = AsyncMock(
            side_effect=CouponError("Cupom invalido.")
        )

        response = await api.request(
            "POST", "/internal/shop/purchase/start",
            {
                "guild_id": 1, "user_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly",
                "coupon_code": "X", "idempotency_key": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "coupon_rejected"

    async def test_successful_purchase_returns_payment(self, api: _App) -> None:
        plan = _plan()
        api.app.state.plan_service.get_plan = AsyncMock(return_value=plan)
        subscription = _subscription(plan_id=plan.id)
        payment = _payment(plan_id=plan.id, subscription_id=subscription.id)
        result = ChargeResult(external_id="ext-1", status=PaymentStatus.PENDING)
        api.app.state.subscription_domain_service.start_purchase = AsyncMock(
            return_value=(subscription, payment, result)
        )

        response = await api.request(
            "POST", "/internal/shop/purchase/start",
            {
                "guild_id": 1, "user_id": 2, "plan_id": str(plan.id), "billing_cycle": "monthly",
                "idempotency_key": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["subscription_id"] == str(subscription.id)
        assert body["payment"]["id"] == str(payment.id)


class TestPaymentApproval:
    async def test_confirm_not_confirmable_returns_409(self, api: _App) -> None:
        api.app.state.subscription_domain_service.confirm_payment = AsyncMock(return_value=None)

        response = await api.request(
            "POST", f"/internal/shop/payments/{uuid.uuid4()}/confirm",
            {"executor_id": 1, "executor_name": "staff"},
        )

        assert response.status_code == 409

    async def test_confirm_success(self, api: _App) -> None:
        subscription = _subscription(status=SubscriptionStatus.ACTIVE)
        api.app.state.subscription_domain_service.confirm_payment = AsyncMock(return_value=subscription)

        response = await api.request(
            "POST", f"/internal/shop/payments/{uuid.uuid4()}/confirm",
            {"executor_id": 1, "executor_name": "staff"},
        )

        assert response.status_code == 200
        assert response.json()["subscription_status"] == "active"

    async def test_reject_returns_changed_flag(self, api: _App) -> None:
        api.app.state.subscription_domain_service.reject_payment = AsyncMock(return_value=False)

        response = await api.request(
            "POST", f"/internal/shop/payments/{uuid.uuid4()}/reject", {"executor_id": None, "executor_name": None}
        )

        assert response.status_code == 200
        assert response.json()["changed"] is False

    async def test_cancel_returns_changed_flag(self, api: _App) -> None:
        api.app.state.subscription_domain_service.cancel_payment = AsyncMock(return_value=True)

        response = await api.request(
            "POST", f"/internal/shop/payments/{uuid.uuid4()}/cancel", {"executor_id": None, "executor_name": None}
        )

        assert response.status_code == 200
        assert response.json()["changed"] is True

    async def test_mark_pending_returns_none_when_not_eligible(self, api: _App) -> None:
        api.app.state.subscription_domain_service.mark_payment_pending = AsyncMock(return_value=None)

        response = await api.request(
            "POST", f"/internal/shop/payments/{uuid.uuid4()}/mark-pending",
            {"executor_id": None, "executor_name": None},
        )

        assert response.status_code == 200
        assert response.json()["payment"] is None


class TestRefreshPayment:
    async def test_manual_provider_skips_gateway_check(self, api: _App) -> None:
        payment = _payment(provider="manual")
        api.app.state.payment_service.get = AsyncMock(return_value=payment)
        api.app.state.payment_service.resolve_provider = AsyncMock(return_value=ManualProvider())

        response = await api.request("POST", f"/internal/shop/payments/{payment.id}/refresh")

        assert response.status_code == 200
        assert response.json()["confirmed"] is False

    async def test_status_change_to_approved_confirms_payment(self, api: _App) -> None:
        payment = _payment(provider="mercadopago", status=PaymentStatus.PENDING)
        refreshed_payment = _payment(
            id=payment.id, provider="mercadopago", status=PaymentStatus.APPROVED,
            subscription_id=payment.subscription_id,
        )
        api.app.state.payment_service.get = AsyncMock(side_effect=[payment, refreshed_payment])
        provider = AsyncMock()
        remote = MagicMock(status=PaymentStatus.APPROVED, raw={})
        provider.get_payment = AsyncMock(return_value=remote)
        api.app.state.payment_service.resolve_provider = AsyncMock(return_value=provider)
        api.app.state.payment_service.set_status = AsyncMock()
        api.app.state.subscription_domain_service.confirm_payment = AsyncMock()

        response = await api.request("POST", f"/internal/shop/payments/{payment.id}/refresh")

        assert response.status_code == 200
        body = response.json()
        assert body["confirmed"] is True
        assert body["payment"]["status"] == "approved"
        api.app.state.subscription_domain_service.confirm_payment.assert_awaited_once_with(payment.id)


class TestPlanAndPaymentLookup:
    async def test_plan_not_found_returns_404(self, api: _App) -> None:
        api.app.state.plan_service.get_plan = AsyncMock(return_value=None)

        response = await api.request("GET", f"/internal/shop/plans/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_payment_not_found_returns_404(self, api: _App) -> None:
        api.app.state.payment_service.get = AsyncMock(return_value=None)

        response = await api.request("GET", f"/internal/shop/payments/{uuid.uuid4()}")

        assert response.status_code == 404
