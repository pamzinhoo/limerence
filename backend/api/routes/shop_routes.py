from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import enforce_rate_limit, get_client_ip, verify_internal_signature
from api.schemas.shop import (
    ChangedResponse,
    ConfirmPaymentResponse,
    MarkPendingResponse,
    PaymentExecutorRequest,
    PaymentProviderInfoResponse,
    PurchasePaymentResponse,
    RefreshPaymentResponse,
    ShopApprovalSettingsResponse,
    ShopCatalogResponse,
    ShopCouponsAvailableResponse,
    ShopPlanResponse,
    ShopSubscriptionResponse,
    StartPurchaseRequest,
    StartPurchaseResponse,
    ValidateCouponRequest,
    ValidateCouponResponse,
)
from core.logger import get_logger
from core.rate_limiter_factory import create_rate_limiter
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.subscription import BillingCycle
from providers.base import PaymentGatewayError
from providers.manual import ManualProvider
from services.coupon_service import CouponError
from services.subscription_domain_service import DuplicateSubscriptionError, MissingPriceError

if TYPE_CHECKING:
    from services.coupon_service import CouponService
    from services.payment_service import PaymentService
    from services.plan_service import PlanService
    from services.subscription_domain_service import SubscriptionDomainService

logger = get_logger("shop_routes")

_shop_limiter = create_rate_limiter(max_hits=120, window_seconds=60, key_prefix="shop")


async def _enforce_shop_rate_limit(request: Request) -> None:
    await enforce_rate_limit(_shop_limiter, get_client_ip(request) or "unknown")


router = APIRouter(
    prefix="/internal/shop",
    tags=["shop"],
    dependencies=[Depends(verify_internal_signature), Depends(_enforce_shop_rate_limit)],
)

# Fase Shop: o Bot deixa de decidir preco/cupom/pagamento/assinatura/licenca
# no fluxo de compra (`bot/views/shop_view.py`) — vira cliente puro deste
# router. Toda a logica de negocio ja existia migrada desde a Fase 3A/3B/3D-1
# (PlanService/CouponService/PaymentService/SubscriptionDomainService); este
# router so a expoe pro canal Bot -> Backend, mesmo padrao de internal_routes.py.


def _payment_response(payment: PaymentHistory) -> PurchasePaymentResponse:
    return PurchasePaymentResponse(
        id=payment.id,
        provider=payment.provider,
        status=payment.status.value,
        amount=payment.amount,
        currency=payment.currency,
        external_id=payment.external_id,
        checkout_url=payment.checkout_url,
        qr_code=payment.pix_qr_code,
        qr_code_base64=payment.pix_qr_code_base64,
        expires_at=payment.expires_at,
        payer_information=payment.payer_information,
        created_at=payment.created_at,
    )


def _parse_billing_cycle(value: str) -> BillingCycle:
    try:
        return BillingCycle(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_billing_cycle", "message": f"Ciclo de cobranca invalido: {value}"},
        ) from None


@router.get("/catalog", response_model=ShopCatalogResponse)
async def shop_catalog(request: Request, guild_id: int) -> ShopCatalogResponse:
    plan_service: PlanService = request.app.state.plan_service
    plans = await plan_service.list_plans(guild_id, only_active=True)
    responses = []
    for plan in plans:
        benefits = await plan_service.list_benefits(plan.id)
        responses.append(
            ShopPlanResponse(
                id=plan.id, name=plan.name, emoji=plan.emoji, color=plan.color,
                description=plan.description, currency=plan.currency,
                price_monthly=plan.price_monthly, price_yearly=plan.price_yearly,
                price_one_time=plan.price_one_time, role_id=plan.role_id,
                product_id=plan.product_id, position=plan.position,
                is_recommended=plan.is_recommended, is_active=plan.is_active,
                benefits=[b.text for b in benefits],
            )
        )
    return ShopCatalogResponse(plans=responses)


@router.get("/plans/{plan_id}", response_model=ShopPlanResponse)
async def shop_plan(request: Request, plan_id: uuid.UUID) -> ShopPlanResponse:
    plan_service: PlanService = request.app.state.plan_service
    plan = await plan_service.get_plan(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "plan_not_found", "message": "Plano nao encontrado."},
        )
    benefits = await plan_service.list_benefits(plan.id)
    return ShopPlanResponse(
        id=plan.id, name=plan.name, emoji=plan.emoji, color=plan.color,
        description=plan.description, currency=plan.currency,
        price_monthly=plan.price_monthly, price_yearly=plan.price_yearly,
        price_one_time=plan.price_one_time, role_id=plan.role_id,
        product_id=plan.product_id, position=plan.position,
        is_recommended=plan.is_recommended, is_active=plan.is_active,
        benefits=[b.text for b in benefits],
    )


@router.get("/subscriptions/{subscription_id}", response_model=ShopSubscriptionResponse)
async def shop_subscription(request: Request, subscription_id: uuid.UUID) -> ShopSubscriptionResponse:
    """Leitura pontual por id — usada pelo botao "Renovar" das mensagens de
    renovacao (`bot/views/subscription_renewal_buttons.py::RenewSubscriptionButton`),
    que precisa confirmar o dono da assinatura antes de reabrir o fluxo de
    compra com `renewal=True`."""
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    subscription = await subscription_domain_service.get_subscription(subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "subscription_not_found", "message": "Assinatura nao encontrada."},
        )
    return ShopSubscriptionResponse(
        id=subscription.id, guild_id=subscription.guild_id, user_id=subscription.user_id,
        plan_id=subscription.plan_id, billing_cycle=subscription.billing_cycle.value,
        status=subscription.status.value,
    )


@router.get("/payments/{payment_id}", response_model=PurchasePaymentResponse)
async def shop_payment(request: Request, payment_id: uuid.UUID) -> PurchasePaymentResponse:
    payment_service: PaymentService = request.app.state.payment_service
    payment = await payment_service.get(payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "payment_not_found", "message": "Pagamento nao encontrado."},
        )
    return _payment_response(payment)


@router.post("/payments/{payment_id}/refresh", response_model=RefreshPaymentResponse)
async def shop_refresh_payment(request: Request, payment_id: uuid.UUID) -> RefreshPaymentResponse:
    """Botao "Atualizar status" do embed de compra — consulta o gateway de
    verdade (nunca confia so no banco), persiste se mudou, e confirma o
    pagamento (entrega cargo/licenca) se aprovado. Mesma logica que vivia em
    `bot/views/payment_view.py::PaymentEmbedView.refresh_button`, so os
    services locais do bot trocados pelos do backend."""
    payment_service: PaymentService = request.app.state.payment_service
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service

    payment = await payment_service.get(payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "payment_not_found", "message": "Pagamento nao encontrado."},
        )

    confirmed = False
    provider = await payment_service.resolve_provider(payment.guild_id)
    if not isinstance(provider, ManualProvider):
        try:
            remote = await provider.get_payment(payment.external_id)
        except PaymentGatewayError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "gateway_unavailable",
                    "message": "Nao foi possivel consultar o gateway agora, tente de novo.",
                },
            ) from None
        if remote.status != payment.status:
            await payment_service.set_status(payment.id, remote.status, provider_payload=dict(remote.raw))
            if remote.status == PaymentStatus.APPROVED:
                await subscription_domain_service.confirm_payment(payment.id)
                confirmed = True
            payment = await payment_service.get(payment.id)
            assert payment is not None

    return RefreshPaymentResponse(payment=_payment_response(payment), confirmed=confirmed)


@router.get("/coupons/available", response_model=ShopCouponsAvailableResponse)
async def shop_coupons_available(request: Request, guild_id: int) -> ShopCouponsAvailableResponse:
    coupon_service: CouponService = request.app.state.coupon_service
    coupons = await coupon_service.list_coupons(guild_id, only_active=True)
    return ShopCouponsAvailableResponse(has_active_coupons=bool(coupons))


@router.get("/payment-provider", response_model=PaymentProviderInfoResponse)
async def shop_payment_provider(request: Request, guild_id: int) -> PaymentProviderInfoResponse:
    payment_service: PaymentService = request.app.state.payment_service
    provider = await payment_service.resolve_provider(guild_id)
    return PaymentProviderInfoResponse(is_manual=isinstance(provider, ManualProvider))


@router.get("/approval-settings", response_model=ShopApprovalSettingsResponse)
async def shop_approval_settings(request: Request, guild_id: int) -> ShopApprovalSettingsResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    settings_row = await subscription_domain_service.get_settings(guild_id)
    return ShopApprovalSettingsResponse(approval_channel_id=settings_row.approval_channel_id)


@router.post("/coupons/validate", response_model=ValidateCouponResponse)
async def shop_validate_coupon(request: Request, body: ValidateCouponRequest) -> ValidateCouponResponse:
    plan_service: PlanService = request.app.state.plan_service
    coupon_service: CouponService = request.app.state.coupon_service

    plan = await plan_service.get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "plan_not_found", "message": "Plano nao encontrado."},
        )
    billing_cycle = _parse_billing_cycle(body.billing_cycle)
    original_amount = {
        BillingCycle.MONTHLY: plan.price_monthly,
        BillingCycle.YEARLY: plan.price_yearly,
        BillingCycle.ONE_TIME: plan.price_one_time,
    }[billing_cycle]
    if original_amount is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "missing_price",
                "message": "Este plano nao tem preco configurado para esse ciclo de cobranca.",
            },
        )

    try:
        application = await coupon_service.validate_and_price(
            body.guild_id, body.code, body.member_id, plan, billing_cycle, original_amount,
            member_role_ids=set(body.member_role_ids) or None,
        )
    except CouponError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "coupon_rejected", "message": str(exc)},
        ) from None

    return ValidateCouponResponse(
        coupon_code=application.coupon.code,
        original_amount=application.original_amount,
        discount_amount=application.discount_amount,
        final_amount=application.final_amount,
        currency=plan.currency,
    )


@router.post("/purchase/start", response_model=StartPurchaseResponse)
async def shop_start_purchase(request: Request, body: StartPurchaseRequest) -> StartPurchaseResponse:
    plan_service: PlanService = request.app.state.plan_service
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service

    plan = await plan_service.get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "plan_not_found", "message": "Plano nao encontrado."},
        )
    billing_cycle = _parse_billing_cycle(body.billing_cycle)

    try:
        subscription, payment, _result = await subscription_domain_service.start_purchase(
            body.guild_id, body.user_id, plan, billing_cycle,
            renewal=body.renewal, coupon_code=body.coupon_code,
            payer_information=body.payer_information,
            member_role_ids=set(body.member_role_ids) or None,
            idempotency_key=body.idempotency_key,
        )
    except CouponError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "coupon_rejected", "message": str(exc)},
        ) from None
    except (DuplicateSubscriptionError, MissingPriceError) as exc:
        # mensagem ja pronta pro usuario final (mesmo texto que o bot exibia
        # antes, so que decidido aqui agora).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "purchase_rejected", "message": str(exc)},
        ) from None

    return StartPurchaseResponse(
        subscription_id=subscription.id,
        subscription_status=subscription.status.value,
        payment=_payment_response(payment),
    )


@router.post("/payments/{payment_id}/confirm", response_model=ConfirmPaymentResponse)
async def shop_confirm_payment(
    request: Request, payment_id: uuid.UUID, body: PaymentExecutorRequest
) -> ConfirmPaymentResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    subscription = await subscription_domain_service.confirm_payment(
        payment_id, executor_id=body.executor_id, executor_name=body.executor_name
    )
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "payment_not_confirmable",
                "message": "Esse pagamento nao pode mais ser aprovado.",
            },
        )
    return ConfirmPaymentResponse(subscription_id=subscription.id, subscription_status=subscription.status.value)


@router.post("/payments/{payment_id}/reject", response_model=ChangedResponse)
async def shop_reject_payment(
    request: Request, payment_id: uuid.UUID, body: PaymentExecutorRequest
) -> ChangedResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    changed = await subscription_domain_service.reject_payment(
        payment_id, executor_id=body.executor_id, executor_name=body.executor_name
    )
    return ChangedResponse(changed=changed)


@router.post("/payments/{payment_id}/mark-pending", response_model=MarkPendingResponse)
async def shop_mark_payment_pending(
    request: Request, payment_id: uuid.UUID, body: PaymentExecutorRequest
) -> MarkPendingResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    payment = await subscription_domain_service.mark_payment_pending(
        payment_id, executor_id=body.executor_id, executor_name=body.executor_name
    )
    return MarkPendingResponse(payment=_payment_response(payment) if payment is not None else None)


@router.post("/payments/{payment_id}/cancel", response_model=ChangedResponse)
async def shop_cancel_payment(
    request: Request, payment_id: uuid.UUID, body: PaymentExecutorRequest
) -> ChangedResponse:
    subscription_domain_service: SubscriptionDomainService = request.app.state.subscription_domain_service
    changed = await subscription_domain_service.cancel_payment(
        payment_id, executor_id=body.executor_id, executor_name=body.executor_name
    )
    return ChangedResponse(changed=changed)
