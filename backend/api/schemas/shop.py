from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

# --- catalogo -----------------------------------------------------------


class ShopPlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    emoji: str | None
    color: int | None
    description: str | None
    currency: str
    price_monthly: int | None
    price_yearly: int | None
    price_one_time: int | None
    role_id: int | None
    product_id: uuid.UUID | None
    position: int
    is_recommended: bool
    is_active: bool
    benefits: list[str]


class ShopCatalogResponse(BaseModel):
    plans: list[ShopPlanResponse]


class ShopCouponsAvailableResponse(BaseModel):
    has_active_coupons: bool


class PaymentProviderInfoResponse(BaseModel):
    is_manual: bool


class ShopApprovalSettingsResponse(BaseModel):
    approval_channel_id: int | None


# --- cupom ----------------------------------------------------------------


class ValidateCouponRequest(BaseModel):
    guild_id: int
    code: str
    member_id: int
    plan_id: uuid.UUID
    billing_cycle: str
    member_role_ids: list[int] = []


class ValidateCouponResponse(BaseModel):
    coupon_code: str
    original_amount: int
    discount_amount: int
    final_amount: int
    currency: str


# --- compra -----------------------------------------------------------------


class StartPurchaseRequest(BaseModel):
    guild_id: int
    user_id: int
    plan_id: uuid.UUID
    billing_cycle: str
    renewal: bool = False
    coupon_code: str | None = None
    payer_information: str | None = None
    member_role_ids: list[int] = []
    idempotency_key: str


class PurchasePaymentResponse(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    amount: int
    currency: str
    external_id: str
    checkout_url: str | None
    qr_code: str | None
    qr_code_base64: str | None
    expires_at: datetime | None
    payer_information: str | None
    created_at: datetime


class StartPurchaseResponse(BaseModel):
    subscription_id: uuid.UUID
    subscription_status: str
    payment: PurchasePaymentResponse


# --- aprovacao manual ------------------------------------------------------


class PaymentExecutorRequest(BaseModel):
    executor_id: int | None = None
    executor_name: str | None = None


class ConfirmPaymentResponse(BaseModel):
    subscription_id: uuid.UUID
    subscription_status: str


class ChangedResponse(BaseModel):
    changed: bool


class MarkPendingResponse(BaseModel):
    payment: PurchasePaymentResponse | None


class RefreshPaymentResponse(BaseModel):
    payment: PurchasePaymentResponse
    confirmed: bool


class ShopSubscriptionResponse(BaseModel):
    id: uuid.UUID
    guild_id: int
    user_id: int
    plan_id: uuid.UUID
    billing_cycle: str
    status: str
