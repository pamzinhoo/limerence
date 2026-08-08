from __future__ import annotations

from config.settings import Settings
from core.logger import get_logger
from database.database import Database
from database.models.payment import PaymentStatus
from database.repositories.payment_repository import PaymentRepository
from providers.base import PaymentGatewayError
from providers.mercadopago import MercadoPagoProvider
from services.payment_service import PaymentService
from services.subscription_domain_service import SubscriptionDomainService

logger = get_logger("webhook_service")


class WebhookService:
    """Recebe notificacoes de gateway (hoje so Mercado Pago), valida
    assinatura e confirma o status real via API do gateway antes de decidir
    qualquer coisa (nunca confia so no payload) — depois despacha pro
    `SubscriptionDomainService` (Fase 5.5, `ProcessPaymentWebhookUseCase`).

    Mesma logica de `bot/services/webhook_service.py` (nao duplica regra
    nova, so troca `SubscriptionService`/`PaymentService` locais do bot
    pelos equivalentes do backend) — mantida ate a Fase 6 decidir qual dos
    dois processos recebe o webhook real do Mercado Pago (hoje e o bot,
    `bot/api` roda em paralelo; este endpoint e "preparacao", sem trafego
    real ainda)."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        payment_service: PaymentService,
        subscription_domain_service: SubscriptionDomainService,
    ) -> None:
        self._database = database
        self._settings = settings
        self._payments = payment_service
        self._subscriptions = subscription_domain_service

    async def validate_signature(self, headers: dict[str, str], raw_body: bytes, data_id: str) -> bool:
        secret = self._settings.mercadopago_webhook_secret
        provider = MercadoPagoProvider(
            access_token=self._settings.mercadopago_access_token or "placeholder",
            webhook_secret=secret,
        )
        headers_with_id = dict(headers)
        headers_with_id["x-data-id"] = data_id
        return await provider.validate_webhook(headers_with_id, raw_body, secret)

    async def handle_mercadopago_notification(
        self, payload: dict[str, object], headers: dict[str, str], raw_body: bytes
    ) -> None:
        event_type = payload.get("type")
        if event_type != "payment":
            logger.info("Webhook ignorado: tipo nao suportado (%s).", event_type)
            return

        data = payload.get("data")
        payment_id = data.get("id") if isinstance(data, dict) else None
        if not payment_id:
            logger.warning("Webhook de pagamento recebido sem data.id — ignorado.")
            return
        payment_id = str(payment_id)

        signature_ok = await self.validate_signature(headers, raw_body, payment_id)
        if not signature_ok:
            if self._settings.mercadopago_webhook_secret:
                logger.warning("Webhook com assinatura invalida para pagamento %s — ignorado.", payment_id)
                return
            logger.warning(
                "Webhook sem WEBHOOK_SECRET configurado (modo dev) — assinatura nao verificada, "
                "processando pagamento %s mesmo assim.", payment_id,
            )

        access_token = self._settings.mercadopago_access_token
        if not access_token:
            logger.error("Webhook recebido mas Mercado Pago nao esta configurado neste backend.")
            return
        provider = MercadoPagoProvider(access_token=access_token, webhook_secret=self._settings.mercadopago_webhook_secret)

        try:
            remote = await provider.get_payment(payment_id)
        except PaymentGatewayError:
            logger.exception("Falha ao confirmar pagamento %s via API do Mercado Pago.", payment_id)
            raise

        async with self._database.session() as session:
            payment = await PaymentRepository(session).get_by_provider_external_id("mercadopago", payment_id)
        if payment is None:
            logger.info("Webhook recebido para pagamento desconhecido (%s) — ignorado.", payment_id)
            return

        if payment.status == remote.status:
            logger.info("Webhook ignorado: pagamento %s ja esta em %s.", payment_id, remote.status.value)
            return

        # A transicao de status e feita DENTRO de cada metodo abaixo (SELECT
        # ... FOR UPDATE + guarda de status esperado) — nunca aqui de
        # antemao, mesma ordem de bot/services/webhook_service.py (setar o
        # status antes faria confirm_payment/reject_payment/expire_payment
        # encontrar o pagamento ja fora de PENDING e pular a transicao real).
        if remote.status == PaymentStatus.APPROVED:
            await self._subscriptions.confirm_payment(payment.id)
        elif remote.status in (PaymentStatus.REJECTED, PaymentStatus.CANCELED):
            await self._subscriptions.reject_payment(payment.id)
        elif remote.status == PaymentStatus.EXPIRED:
            await self._subscriptions.expire_payment(payment.id)
        elif remote.status == PaymentStatus.REFUNDED:
            # handle_refund_or_chargeback nao mexe no status do pagamento (so
            # da assinatura) — precisa ser setado aqui, nao ha outro lugar.
            await self._payments.set_status(payment.id, PaymentStatus.REFUNDED, provider_payload=dict(remote.raw))
            await self._subscriptions.handle_refund_or_chargeback(payment.id, chargeback=False)
        elif remote.status == PaymentStatus.CHARGEBACK:
            await self._payments.set_status(payment.id, PaymentStatus.CHARGEBACK, provider_payload=dict(remote.raw))
            await self._subscriptions.handle_refund_or_chargeback(payment.id, chargeback=True)
        else:
            logger.info("Webhook processado sem acao adicional (status %s).", remote.status.value)
