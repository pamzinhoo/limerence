from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from api.dependencies import enforce_rate_limit, get_current_player
from api.schemas.launcher import LicenseResponse, ProductCatalogItemResponse
from core.rate_limiter_factory import create_rate_limiter
from database.models.license import LicenseStatus

if TYPE_CHECKING:
    from database.models.player import Player
    from providers.internal_events_client import InternalEventsClient
    from services.license_service import LicenseService
    from services.product_service import ProductService

router = APIRouter(prefix="/player", tags=["player"])

_read_limiter = create_rate_limiter(max_hits=60, window_seconds=60, key_prefix='player_read')

# Mais apertado que o limiter geral de leitura -- essa rota, diferente das
# outras deste arquivo, faz uma chamada de rede pro bot (nao so uma query no
# banco), entao custa mais caro por request e vale um teto proprio.
_verified_limiter = create_rate_limiter(max_hits=20, window_seconds=60, key_prefix='player_verified')


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[union-attr]


@router.get("/licenses", response_model=list[LicenseResponse])
async def licenses(request: Request, player: Player = Depends(get_current_player)) -> list[LicenseResponse]:
    """Inventario completo do player — inclui licenca revogada/expirada
    (historico), nao so ativa. `/player/products` e que filtra por posse."""
    await enforce_rate_limit(_read_limiter, str(player.id))
    license_service: LicenseService = request.app.state.license_service
    product_service: ProductService = request.app.state.product_service

    license_rows = await license_service.list_by_player(player.id)
    responses: list[LicenseResponse] = []
    for lic in license_rows:
        product = await product_service.get(lic.product_id, include_deleted=True)
        responses.append(
            LicenseResponse(
                id=lic.id,
                product_id=lic.product_id,
                product_slug=product.slug if product else None,
                product_name=product.name if product else None,
                status=lic.status.value,
                purchase_source=lic.purchase_source,
                activated_at=_iso(lic.activated_at),
                expires_at=_iso(lic.expires_at),
                auto_renew=lic.auto_renew,
                revoked_at=_iso(lic.revoked_at),
                revoked_reason=lic.revoked_reason,
            )
        )
    return responses


@router.get("/products", response_model=list[ProductCatalogItemResponse])
async def products(
    request: Request, player: Player = Depends(get_current_player)
) -> list[ProductCatalogItemResponse]:
    """Catalogo ativo (loja/biblioteca) anotado com posse do player — `owned`
    reflete License ACTIVE, nao so a existencia de uma linha (revogada/
    expirada conta como nao-owned aqui)."""
    await enforce_rate_limit(_read_limiter, str(player.id))
    license_service: LicenseService = request.app.state.license_service
    product_service: ProductService = request.app.state.product_service

    catalog = await product_service.list_catalog(only_active=True)
    license_rows = await license_service.list_by_player(player.id)
    license_by_product = {lic.product_id: lic for lic in license_rows}

    responses: list[ProductCatalogItemResponse] = []
    for product in catalog:
        lic = license_by_product.get(product.id)
        responses.append(
            ProductCatalogItemResponse(
                id=product.id,
                slug=product.slug,
                name=product.name,
                product_type=product.product_type.value,
                description=product.description,
                price_amount=product.price_amount,
                currency=product.currency,
                owned=lic is not None and lic.status == LicenseStatus.ACTIVE,
                license_status=lic.status.value if lic else None,
            )
        )
    return responses


@router.get("/verified")
async def verified_status(
    request: Request, player: Player = Depends(get_current_player)
) -> dict[str, bool]:
    """Checagem AO VIVO do cargo 'Verificado' no Discord — deliberadamente
    diferente de /player/products (que reflete License, nossa fonte de
    verdade de posse). 'Verificado' nunca foi modelado como License: e' so
    um cargo que o bot concede no login e nunca revoga sozinho (ver
    role_sync_service.handle_player_verified no bot). Por isso a fonte de
    verdade AQUI e' o proprio cargo do Discord, checado na hora — se o
    jogador tirar o cargo manualmente, esta rota reflete isso no proximo
    pedido, sem esperar reconciliacao nenhuma (nao existe reconciliacao pra
    este cargo, de proposito).

    Chamado pelo jogo (game/game/discord_auth.rpy) pra decidir se mostra a
    carta de DLC liberada na tela de selecao de genero — NUNCA decida isso
    so com `persistent.discord_access_token` local (esse token so prova que
    o jogador logou uma vez, nao que ainda tem o cargo agora).

    Fail-closed de proposito: qualquer erro ao consultar o bot (offline,
    timeout, guild sem cargo configurado) devolve `verified=False` — mais
    seguro tratar como "nao verificado" numa falha do que liberar contudo
    sem confirmacao positiva.
    """
    await enforce_rate_limit(_verified_limiter, str(player.id))
    internal_events_client: InternalEventsClient | None = getattr(
        request.app.state, "internal_events_client", None
    )
    if internal_events_client is None:
        return {"verified": False}

    is_verified = await internal_events_client.check_player_verified(player.discord_id)
    return {"verified": is_verified}
