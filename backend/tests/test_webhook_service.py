from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models.payment import PaymentStatus
from services.webhook_service import WebhookService


def _settings(*, webhook_secret: str | None = None) -> MagicMock:
    settings = MagicMock()
    settings.mercadopago_webhook_secret = webhook_secret
    settings.mercadopago_access_token = "token"
    return settings


def _database() -> MagicMock:
    database = MagicMock()

    @asynccontextmanager
    async def _session_cm():
        yield MagicMock()

    database.session = _session_cm
    return database


def _service() -> tuple[WebhookService, AsyncMock, AsyncMock]:
    payments = AsyncMock()
    subscriptions = AsyncMock()
    service = WebhookService(_database(), _settings(), payments, subscriptions)
    return service, payments, subscriptions


def _payment(status: PaymentStatus) -> MagicMock:
    payment = MagicMock()
    payment.id = uuid.uuid4()
    payment.status = status
    payment.subscription_id = uuid.uuid4()
    return payment


def _remote(status: PaymentStatus) -> MagicMock:
    remote = MagicMock()
    remote.status = status
    remote.raw = {}
    return remote


def _patched_gateway(*, payment: MagicMock | None, remote_status: PaymentStatus):
    repo_patch = patch("services.webhook_service.PaymentRepository")
    provider_patch = patch("services.webhook_service.MercadoPagoProvider")
    repo_cls = repo_patch.start()
    provider_cls = provider_patch.start()
    repo_cls.return_value.get_by_provider_external_id = AsyncMock(return_value=payment)
    provider_cls.return_value.get_payment = AsyncMock(return_value=_remote(remote_status))
    provider_cls.return_value.validate_webhook = AsyncMock(return_value=True)
    return repo_patch, provider_patch


_BODY = {"type": "payment", "data": {"id": "123"}}


class TestDispatch:
    @pytest.mark.parametrize(
        ("remote_status", "expected_call"),
        [
            (PaymentStatus.APPROVED, "confirm_payment"),
            (PaymentStatus.REJECTED, "reject_payment"),
            (PaymentStatus.CANCELED, "reject_payment"),
            (PaymentStatus.EXPIRED, "expire_payment"),
        ],
    )
    async def test_simple_transitions_dispatch_to_subscription_domain_service(
        self, remote_status: PaymentStatus, expected_call: str
    ) -> None:
        service, _payments, subscriptions = _service()
        payment = _payment(PaymentStatus.PENDING)
        repo_patch, provider_patch = _patched_gateway(payment=payment, remote_status=remote_status)
        try:
            await service.handle_mercadopago_notification(_BODY, {}, b"{}")
        finally:
            repo_patch.stop()
            provider_patch.stop()

        getattr(subscriptions, expected_call).assert_awaited_once_with(payment.id)

    async def test_refunded_sets_payment_status_then_dispatches(self) -> None:
        service, payments, subscriptions = _service()
        payment = _payment(PaymentStatus.APPROVED)
        repo_patch, provider_patch = _patched_gateway(payment=payment, remote_status=PaymentStatus.REFUNDED)
        try:
            await service.handle_mercadopago_notification(_BODY, {}, b"{}")
        finally:
            repo_patch.stop()
            provider_patch.stop()

        payments.set_status.assert_awaited_once()
        assert payments.set_status.await_args.args[1] == PaymentStatus.REFUNDED
        subscriptions.handle_refund_or_chargeback.assert_awaited_once_with(payment.id, chargeback=False)

    async def test_chargeback_sets_payment_status_then_dispatches(self) -> None:
        service, payments, subscriptions = _service()
        payment = _payment(PaymentStatus.APPROVED)
        repo_patch, provider_patch = _patched_gateway(payment=payment, remote_status=PaymentStatus.CHARGEBACK)
        try:
            await service.handle_mercadopago_notification(_BODY, {}, b"{}")
        finally:
            repo_patch.stop()
            provider_patch.stop()

        payments.set_status.assert_awaited_once()
        assert payments.set_status.await_args.args[1] == PaymentStatus.CHARGEBACK
        subscriptions.handle_refund_or_chargeback.assert_awaited_once_with(payment.id, chargeback=True)


class TestIdempotencyAndGuards:
    async def test_same_status_is_no_op(self) -> None:
        service, payments, subscriptions = _service()
        payment = _payment(PaymentStatus.APPROVED)
        repo_patch, provider_patch = _patched_gateway(payment=payment, remote_status=PaymentStatus.APPROVED)
        try:
            await service.handle_mercadopago_notification(_BODY, {}, b"{}")
        finally:
            repo_patch.stop()
            provider_patch.stop()

        subscriptions.confirm_payment.assert_not_called()
        payments.set_status.assert_not_called()

    async def test_unknown_payment_is_ignored(self) -> None:
        service, payments, subscriptions = _service()
        repo_patch, provider_patch = _patched_gateway(payment=None, remote_status=PaymentStatus.APPROVED)
        try:
            await service.handle_mercadopago_notification(_BODY, {}, b"{}")
        finally:
            repo_patch.stop()
            provider_patch.stop()

        subscriptions.confirm_payment.assert_not_called()

    async def test_non_payment_event_type_is_ignored(self) -> None:
        service, _payments, subscriptions = _service()
        await service.handle_mercadopago_notification({"type": "merchant_order"}, {}, b"{}")
        subscriptions.confirm_payment.assert_not_called()

    async def test_missing_data_id_is_ignored(self) -> None:
        service, _payments, subscriptions = _service()
        await service.handle_mercadopago_notification({"type": "payment", "data": {}}, {}, b"{}")
        subscriptions.confirm_payment.assert_not_called()
