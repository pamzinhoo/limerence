from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from core.events import (
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_CHARGEBACK,
    SUBSCRIPTION_CREATED,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_PAYMENT_CANCELED,
    SUBSCRIPTION_PAYMENT_EXPIRED,
    SUBSCRIPTION_PAYMENT_PENDING,
    SUBSCRIPTION_PAYMENT_REJECTED,
    SUBSCRIPTION_REFUNDED,
    SUBSCRIPTION_RENEWED,
)
from core.logger import get_logger
from database.database import Database
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.plan import Plan
from database.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from database.models.subscription_history import SubscriptionEventType, SubscriptionHistory
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository
from database.repositories.plan_repository import PlanRepository
from database.repositories.player_repository import PlayerRepository
from database.repositories.subscription_history_repository import SubscriptionHistoryRepository
from database.repositories.subscription_repository import SubscriptionRepository
from providers.base import ChargeRequest, ChargeResult
from services.coupon_service import CouponService
from services.license_service import LicenseService
from services.payment_service import PaymentService
from services.subscription_notification_publisher import SubscriptionNotificationPublisher

logger = get_logger("subscription_service")

_CYCLE_LENGTH: dict[BillingCycle, timedelta | None] = {
    BillingCycle.MONTHLY: timedelta(days=30),
    BillingCycle.YEARLY: timedelta(days=365),
    BillingCycle.ONE_TIME: None,
}


class DuplicateSubscriptionError(ValueError):
    pass


class MissingPriceError(ValueError):
    pass


def _price_for_cycle(plan: Plan, cycle: BillingCycle) -> int | None:
    return {
        BillingCycle.MONTHLY: plan.price_monthly,
        BillingCycle.YEARLY: plan.price_yearly,
        BillingCycle.ONE_TIME: plan.price_one_time,
    }[cycle]


class SubscriptionDomainService:
    """Transicao de estado pura do dominio de assinaturas — compra,
    confirmacao/rejeicao de pagamento, cancelamento, renovacao, expiracao,
    reembolso/chargeback, concessao/revogacao de License. Zero Discord: nada
    aqui manda DM, entrega cargo ou escreve audit log de guild — isso e
    responsabilidade do bot (SubscriptionNotificationHandler, Fase 3D-2),
    reagindo aos eventos que este servico publica via
    `SubscriptionNotificationPublisher` depois de cada transicao confirmada.

    Historico da extracao (bot/services/subscription_service.py):
    `_deliver_role`/`_remove_role`/`_send_plan_message`/`_send_payment_dm`/
    `_log` (I/O de Discord) e `_notify_renewed` (chamada direta a
    SubscriptionReminderService) saem inteiros — viram evento. `_audit`/
    `_audit_subscription` (audit log do Discord guild) viram log estruturado
    aqui (mesmo padrao de PlanService/CouponService) — o audit log real,
    quando fizer sentido, e escrito pelo Handler ao consumir o evento.
    `_grant_license`/`_revoke_license` ficam, mas com LicenseService injetado
    direto no construtor em vez de `getattr(self._bot, "license_service",
    None)` — fecha o acoplamento oculto via instancia do bot encontrado na
    revisao da Fase 3A/3B."""

    def __init__(
        self,
        database: Database,
        payment_service: PaymentService,
        license_service: LicenseService,
        coupon_service: CouponService,
        publisher: SubscriptionNotificationPublisher | None = None,
    ) -> None:
        self._database = database
        self._payments = payment_service
        self._licenses = license_service
        self._coupons = coupon_service
        self._publisher = publisher or SubscriptionNotificationPublisher()

    def _audit(
        self,
        action: str,
        subscription: Subscription,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """No bot, isto gravava no audit log do Discord guild
        (audit_log_service). O backend nao fala com Discord — audita via log
        estruturado (mesma decisao de PlanService/CouponService)."""
        logger.info(
            "subscription_audit",
            extra={
                "action": action,
                "guild_id": subscription.guild_id,
                "subscription_id": str(subscription.id),
                "executor_id": executor_id,
                "executor_name": executor_name,
                "reason": reason,
                "details": details or {},
            },
        )

    # --- configuracao ---------------------------------------------------

    async def get_settings(self, guild_id: int):
        async with self._database.session() as session:
            return await MonetizationSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object):
        async with self._database.session() as session:
            repo = MonetizationSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings

    # --- compra -----------------------------------------------------------

    async def start_purchase(
        self,
        guild_id: int,
        user_id: int,
        plan: Plan,
        billing_cycle: BillingCycle,
        *,
        renewal: bool = False,
        coupon_code: str | None = None,
        payer_information: str | None = None,
        member_role_ids: set[int] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Subscription, PaymentHistory, ChargeResult]:
        """`renewal=True` (botao "Renovar" das mensagens de renovacao) permite
        cobrar uma assinatura ATIVA que ja passou do vencimento (esta em
        carencia). `member_role_ids` substitui o antigo `discord.Member` — so
        e usado se `coupon_code` tiver `required_role_id` configurado
        (CouponService.validate_and_price ja decoupled desde a Fase 3B).

        `idempotency_key`: gerada pelo chamador (bot, um valor por tentativa
        de compra — sobrevive a retry HTTP da mesma tentativa) ANTES de
        chamar este metodo. Protege contra duplo clique/timeout/retry criando
        DUAS cobrancas no gateway pro mesmo pedido — o UNIQUE `provider`+
        `external_id` em `PaymentHistory` so pega depois que o gateway ja
        respondeu; isto pega antes. Reenviar a mesma chave devolve o mesmo
        resultado (subscription, payment, e um `ChargeResult` reconstruido a
        partir do `PaymentHistory` ja persistido), sem gerar nova cobranca."""
        if idempotency_key:
            existing_payment = await self._payments.get_by_purchase_idempotency_key(idempotency_key)
            if existing_payment is not None:
                async with self._database.session() as session:
                    subscription = await SubscriptionRepository(session).get_by_id(
                        existing_payment.subscription_id
                    )
                if subscription is None:
                    raise MissingPriceError(
                        "Pedido anterior com esta chave nao encontrado — tente novamente."
                    )
                replay_result = ChargeResult(
                    external_id=existing_payment.external_id,
                    status=existing_payment.status,
                    checkout_url=existing_payment.checkout_url,
                    qr_code=existing_payment.pix_qr_code,
                    qr_code_base64=existing_payment.pix_qr_code_base64,
                    expires_at=existing_payment.expires_at,
                )
                return subscription, existing_payment, replay_result

        amount = _price_for_cycle(plan, billing_cycle)
        if amount is None:
            raise MissingPriceError("Este plano não tem preço configurado para esse ciclo de cobrança.")

        coupon_application = None
        if coupon_code:
            coupon_application = await self._coupons.validate_and_price(
                guild_id, coupon_code, user_id, plan, billing_cycle, amount,
                member_role_ids=member_role_ids,
            )
            amount = coupon_application.final_amount

        provider = await self._payments.resolve_provider(guild_id)
        gateway_settings = await self._payments.get_gateway_settings(guild_id)

        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            active_or_pending = await sub_repo.get_active_for_user_plan(guild_id, user_id, plan.id)
            renewing_row = (
                active_or_pending
                if renewal
                and active_or_pending is not None
                and active_or_pending.status == SubscriptionStatus.ACTIVE
                and active_or_pending.current_period_end is not None
                and active_or_pending.current_period_end <= datetime.now(UTC)
                else None
            )
            if active_or_pending is not None and renewing_row is None:
                raise DuplicateSubscriptionError(
                    "Você já possui uma assinatura ativa ou pendente para este plano."
                )
            external_reference = f"{guild_id}:{user_id}:{plan.id}:{uuid.uuid4()}"

            if renewing_row is not None:
                renewing_row.billing_cycle = billing_cycle
                renewing_row.provider = provider.name
                renewing_row.external_reference = external_reference
                await session.flush()
                subscription = renewing_row
            else:
                existing_row = await sub_repo.get_by_user_plan(guild_id, user_id, plan.id)
                if existing_row is not None:
                    existing_row.status = SubscriptionStatus.PENDING
                    existing_row.billing_cycle = billing_cycle
                    existing_row.provider = provider.name
                    existing_row.external_reference = external_reference
                    existing_row.started_at = None
                    existing_row.current_period_end = None
                    existing_row.canceled_at = None
                    await session.flush()
                    subscription = existing_row
                else:
                    subscription = await sub_repo.add(
                        Subscription(
                            guild_id=guild_id,
                            user_id=user_id,
                            plan_id=plan.id,
                            status=SubscriptionStatus.PENDING,
                            billing_cycle=billing_cycle,
                            provider=provider.name,
                            external_reference=external_reference,
                        )
                    )

        request = ChargeRequest(
            guild_id=guild_id,
            user_id=user_id,
            plan_id=str(plan.id),
            plan_name=plan.name,
            amount=amount,
            currency=plan.currency,
            billing_cycle=billing_cycle,
            external_reference=external_reference,
            expires_in_minutes=gateway_settings.pix_expiration_minutes,
        )
        result, payment = await self._payments.charge(
            request, provider, payer_information=payer_information, idempotency_key=idempotency_key
        )
        await self._payments.link_subscription(payment.id, subscription.id)
        if coupon_application is not None:
            await self._coupons.record_redemption(
                coupon_application.coupon.id,
                guild_id,
                user_id,
                payment.id,
                coupon_application.original_amount,
                coupon_application.discount_amount,
                coupon_application.final_amount,
            )
        self._audit(
            "Cobrança criada", subscription,
            executor_id=user_id, executor_name=None,
            details={"plano": plan.name},
        )
        return subscription, payment, result

    # --- confirmacao (aprovacao manual ou webhook de gateway) --------------

    async def confirm_payment(
        self,
        payment_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> Subscription | None:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.subscription_id is None:
            return None
        if payment.status == PaymentStatus.APPROVED:
            async with self._database.session() as session:
                return await SubscriptionRepository(session).get_by_id(payment.subscription_id)
        if payment.status != PaymentStatus.PENDING:
            return None

        now = datetime.now(UTC)
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.APPROVED, paid_at=now,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            return None

        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return None
            cycle_length = _CYCLE_LENGTH[subscription.billing_cycle]
            was_renewal = subscription.started_at is not None
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.started_at = now
            subscription.current_period_end = now + cycle_length if cycle_length else None
            await session.flush()
            await session.refresh(subscription)

            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CREATED,
                    to_plan_id=subscription.plan_id,
                )
            )

        if plan is not None:
            if plan.product_id is not None:
                await self._grant_license(subscription, plan, payment)
            self._audit(
                "Pagamento aprovado", subscription,
                executor_id=executor_id, executor_name=executor_name,
            )
            await self._publisher.publish(
                SUBSCRIPTION_RENEWED if was_renewal else SUBSCRIPTION_CREATED,
                subscription,
                payment_id=payment.id,
                executor_id=executor_id,
                executor_name=executor_name,
                metadata={
                    "plan_id": str(plan.id),
                    "plan_name": plan.name,
                    "product_id": str(plan.product_id) if plan.product_id else None,
                    "role_id": plan.role_id,
                    "was_renewal": was_renewal,
                },
            )
        return subscription

    async def reject_payment(
        self,
        payment_id: uuid.UUID,
        *,
        reason: str | None = None,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> bool:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return False
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.REJECTED,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            return False
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            self._audit(
                "Pagamento rejeitado", subscription,
                executor_id=executor_id, executor_name=executor_name, reason=reason,
            )
            await self._publisher.publish(
                SUBSCRIPTION_PAYMENT_REJECTED, subscription,
                payment_id=payment.id, executor_id=executor_id, executor_name=executor_name,
                reason=reason,
                metadata={
                    "plan_id": str(plan.id), "plan_name": plan.name,
                    "renewal_in_flight": renewal_in_flight,
                },
            )
        return True

    async def mark_payment_pending(
        self,
        payment_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> PaymentHistory | None:
        """Botao "Marcar como Pendente" do painel de aprovacao — reverte um
        pagamento de volta pra fila de analise, sem mexer no cargo/assinatura."""
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status not in (PaymentStatus.PROCESSING, PaymentStatus.REJECTED):
            return None
        payment = await self._payments.set_status(
            payment.id, PaymentStatus.PENDING,
            expected_statuses=(PaymentStatus.PROCESSING, PaymentStatus.REJECTED),
        )
        if payment is None or payment.subscription_id is None:
            return payment
        async with self._database.session() as session:
            subscription = await SubscriptionRepository(session).get_by_id(payment.subscription_id)
            if subscription is None:
                return payment
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
        if plan is not None:
            self._audit(
                "Pagamento marcado como pendente", subscription,
                executor_id=executor_id, executor_name=executor_name,
            )
            await self._publisher.publish(
                SUBSCRIPTION_PAYMENT_PENDING, subscription,
                payment_id=payment.id, executor_id=executor_id, executor_name=executor_name,
                metadata={"plan_id": str(plan.id), "plan_name": plan.name},
            )
        return payment

    async def cancel_payment(
        self,
        payment_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> bool:
        """Botao "Cancelar Pedido" do painel de aprovacao."""
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
            return False
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.CANCELED,
            expected_statuses=(PaymentStatus.PENDING, PaymentStatus.PROCESSING),
        )
        if updated is None:
            return False
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            self._audit(
                "Pedido cancelado pela equipe", subscription,
                executor_id=executor_id, executor_name=executor_name,
            )
            await self._publisher.publish(
                SUBSCRIPTION_PAYMENT_CANCELED, subscription,
                payment_id=payment.id, executor_id=executor_id, executor_name=executor_name,
                metadata={
                    "plan_id": str(plan.id), "plan_name": plan.name,
                    "renewal_in_flight": renewal_in_flight,
                },
            )
        return True

    # --- cancelamento -----------------------------------------------------

    async def cancel_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        remove_role: bool = True,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> Subscription | None:
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status not in (
                SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING,
            ):
                return subscription
            was_active = subscription.status == SubscriptionStatus.ACTIVE
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(subscription)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CANCELED,
                    from_plan_id=subscription.plan_id,
                )
            )

        if plan is None:
            return subscription

        if not was_active:
            # pendente nunca chegou a entregar cargo/DM de boas-vindas — so cancela,
            # nada pro bot fazer, so log de auditoria
            self._audit(
                "Assinatura cancelada (ainda pendente)", subscription,
                executor_id=executor_id, executor_name=executor_name,
            )
            return subscription

        # recompensas permanentes (pagamento unico) nunca sao removidas no cancelamento
        if subscription.billing_cycle != BillingCycle.ONE_TIME and plan.product_id is not None:
            await self._revoke_license(subscription, plan, reason="Assinatura cancelada")

        self._audit(
            "Assinatura cancelada", subscription,
            executor_id=executor_id, executor_name=executor_name,
        )
        await self._publisher.publish(
            SUBSCRIPTION_CANCELLED, subscription,
            executor_id=executor_id, executor_name=executor_name,
            metadata={
                "plan_id": str(plan.id), "plan_name": plan.name, "was_active": was_active,
                "product_id": str(plan.product_id) if plan.product_id else None,
                "role_id": plan.role_id, "remove_role": remove_role,
                "billing_cycle": subscription.billing_cycle.value,
            },
        )
        return subscription

    # --- renovacao (chamada quando o gateway confirmar cobranca recorrente) ---

    async def renew_subscription(self, subscription_id: uuid.UUID) -> Subscription | None:
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return subscription
            cycle_length = _CYCLE_LENGTH[subscription.billing_cycle]
            if cycle_length is None:
                return subscription
            base = subscription.current_period_end or datetime.now(UTC)
            subscription.current_period_end = base + cycle_length
            await session.flush()
            await session.refresh(subscription)
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.RENEWED,
                    to_plan_id=subscription.plan_id,
                )
            )

        if plan is not None:
            self._audit("Assinatura renovada", subscription)
            await self._publisher.publish(
                SUBSCRIPTION_RENEWED, subscription,
                metadata={
                    "plan_id": str(plan.id), "plan_name": plan.name,
                    "current_period_end": (
                        subscription.current_period_end.isoformat()
                        if subscription.current_period_end else None
                    ),
                },
            )
        return subscription

    # --- expiracao (fim de periodo/carencia) -------------------------------

    async def expire_subscription(
        self, subscription_id: uuid.UUID, *, remove_role: bool = True, end_subscription: bool = True
    ) -> Subscription | None:
        """Encerra uma assinatura vencida — marca EXPIRED e revoga License se
        houver Product vinculado. Nao manda mensagem — quem avisa o usuario e
        o SubscriptionReminderService (fica no bot, Fase 3D-3), com o texto
        que a guild configurou. Idempotente: so age sobre assinatura ATIVA."""
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return subscription
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            if end_subscription:
                subscription.status = SubscriptionStatus.EXPIRED
                await session.flush()
                await session.refresh(subscription)
                await SubscriptionHistoryRepository(session).add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        event_type=SubscriptionEventType.EXPIRED,
                        from_plan_id=subscription.plan_id,
                    )
                )

        if plan is None:
            return subscription
        if subscription.billing_cycle != BillingCycle.ONE_TIME and plan.product_id is not None:
            await self._revoke_license(subscription, plan, reason="Assinatura expirada")
        await self._publisher.publish(
            SUBSCRIPTION_EXPIRED, subscription,
            metadata={
                "plan_id": str(plan.id), "plan_name": plan.name,
                "product_id": str(plan.product_id) if plan.product_id else None,
                "role_id": plan.role_id, "remove_role": remove_role,
                "end_subscription": end_subscription,
                "billing_cycle": subscription.billing_cycle.value,
            },
        )
        return subscription

    async def get_subscription(self, subscription_id: uuid.UUID) -> Subscription | None:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).get_by_id(subscription_id)

    # --- expiracao (loop de PIX vencido) -----------------------------------

    async def expire_payment(self, payment_id: uuid.UUID) -> bool:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return False
        updated = await self._payments.set_status(
            payment.id, PaymentStatus.EXPIRED,
            expected_statuses=(PaymentStatus.PENDING,),
        )
        if updated is None:
            return False
        if payment.subscription_id is None:
            return True
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None:
                return True
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            renewal_in_flight = subscription.status == SubscriptionStatus.ACTIVE
            if not renewal_in_flight:
                if subscription.status != SubscriptionStatus.PENDING:
                    return True
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(UTC)
                await session.flush()

        if plan is not None:
            self._audit("Pagamento expirado", subscription)
            await self._publisher.publish(
                SUBSCRIPTION_PAYMENT_EXPIRED, subscription,
                payment_id=payment.id,
                metadata={
                    "plan_id": str(plan.id), "plan_name": plan.name,
                    "renewal_in_flight": renewal_in_flight,
                },
            )
        return True

    # --- reembolso/chargeback (webhook) ------------------------------------

    async def handle_refund_or_chargeback(self, payment_id: uuid.UUID, *, chargeback: bool = False) -> None:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.subscription_id is None:
            return
        async with self._database.session() as session:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(payment.subscription_id)
            if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
                return
            plan = await PlanRepository(session).get_by_id(subscription.plan_id)
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(subscription)
            await SubscriptionHistoryRepository(session).add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.CANCELED,
                    from_plan_id=subscription.plan_id,
                    note="chargeback" if chargeback else "refund",
                )
            )

        if plan is None:
            return

        label = "Chargeback recebido" if chargeback else "Reembolso realizado"
        if plan.product_id is not None:
            await self._revoke_license(subscription, plan, reason=label)
        self._audit(label, subscription)
        await self._publisher.publish(
            SUBSCRIPTION_CHARGEBACK if chargeback else SUBSCRIPTION_REFUNDED, subscription,
            payment_id=payment.id,
            metadata={
                "plan_id": str(plan.id), "plan_name": plan.name,
                "product_id": str(plan.product_id) if plan.product_id else None,
                "role_id": plan.role_id,
            },
        )

    # --- consulta (base pra API/integracao com jogos) ----------------------

    async def list_active_subscriptions(self, guild_id: int, user_id: int) -> list[Subscription]:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_active_by_user(guild_id, user_id)

    async def list_guild_subscriptions(self, guild_id: int) -> list[Subscription]:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_by_guild(guild_id)

    async def list_cancelable_subscriptions(self, guild_id: int, user_id: int) -> list[Subscription]:
        async with self._database.session() as session:
            return await SubscriptionRepository(session).list_active_or_pending_by_user(guild_id, user_id)

    # --- licenca (Product vinculado ao plano) ------------------------------

    async def _grant_license(self, subscription: Subscription, plan: Plan, payment: PaymentHistory) -> None:
        """Concede/renova a License do Product vinculado ao plano (se algum).
        Falha aqui nunca derruba o fluxo de pagamento — License e beneficio
        adicional sobre o cargo Discord, nunca requisito pra aprovar
        pagamento (mesma resiliencia do codigo original, so que agora com
        LicenseService injetado direto, sem getattr(self._bot, ...))."""
        if plan.product_id is None:
            return
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get_or_create_by_discord_id(
                    subscription.user_id, discord_username=None, linked_at=datetime.now(UTC)
                )
            await self._licenses.grant_or_renew(
                player.id,
                plan.product_id,
                purchase_source=f"subscription:{plan.name}",
                external_reference=str(payment.id),
                expires_at=subscription.current_period_end,
                auto_renew=subscription.billing_cycle != BillingCycle.ONE_TIME,
            )
        except Exception:
            logger.exception("Falha ao conceder licenca da assinatura %s.", subscription.id)

    async def _revoke_license(self, subscription: Subscription, plan: Plan, *, reason: str) -> None:
        if plan.product_id is None:
            return
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get_by_discord_id(subscription.user_id)
            if player is None:
                return
            await self._licenses.revoke_by_player_product(player.id, plan.product_id, reason=reason)
        except Exception:
            logger.exception("Falha ao revogar licenca da assinatura %s.", subscription.id)
