"""
launcher_dlc_routes.py (v3)
=============================

Duas rotas sensiveis, DELIBERADAMENTE separadas (ponto 7):

  POST /launcher/dlc/{slug}/authorize   -> devolve token de AUTORIZACAO
                                            (sem segredo nenhum)
  POST /launcher/dlc/{slug}/material    -> troca esse token por material
                                            criptografico, UMA UNICA VEZ

Nao existe (e nunca deve existir) um GET /dlc/key sem autenticacao —
ponto 18 do pedido e explicito sobre isso.

Recomendacao operacional (documentar no deploy, ver ponto 24 do README):
desabilitar log de corpo de resposta especificamente na rota /material — a
maioria dos frameworks de observabilidade (Sentry, logs de acesso
customizados) loga status/latencia por padrao mas alguns tambem capturam
body; garanta que este endpoint especifico esta na lista de exclusao.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from core.rate_limiter import RateLimitExceeded
from core.rate_limiter_factory import create_rate_limiter
from services.dlc_license_service import AUTHORIZATION_TTL_SECONDS, DlcLicenseService

launcher_dlc_router = APIRouter()

# Rate limit por player_id (nao por IP -- um player autenticado ja tem
# identidade estavel, e' a chave certa aqui). Motivo de ter DOIS limiters
# separados, mais apertado no /material: /authorize sozinho e barato
# (so grava uma linha), mas /material desembrulha a chave da DLC -- e o
# unico lugar do sistema que faz isso, entao e' o que mais vale limitar
# contra tentativa de forca bruta/varredura de jti (mesmo o jti sendo
# imprevisivel, defesa em profundidade nao custa nada aqui).
# TODO(producao): mesma ressalva ja documentada em core/rate_limiter.py --
# sem REDIS_URL configurado isso e' em memoria, por processo. Se o backend
# rodar com mais de uma instancia, configure REDIS_URL antes de contar com
# isso pra seguranca real (nao so UX).
_authorize_limiter = create_rate_limiter(max_hits=20, window_seconds=60, key_prefix="dlc-authorize")
_material_limiter = create_rate_limiter(max_hits=10, window_seconds=60, key_prefix="dlc-material")


# TODO integrar: trocar pelas dependencies reais ja existentes em
# api/dependencies.py (mesma sessao/token usados por launcher_routes.py).
# NUNCA aceite player_id vindo do corpo da requisicao.
async def get_current_player_id() -> uuid.UUID:
    raise NotImplementedError("Ligar na dependency real de sessao do launcher.")


async def get_dlc_license_service() -> DlcLicenseService:
    raise NotImplementedError("Instanciar com Database/LicenseService/ProductService reais.")


class DlcAuthorizedList(BaseModel):
    dlc_slugs: list[str]


@launcher_dlc_router.get("/dlcs/authorized", response_model=DlcAuthorizedList)
async def list_authorized_dlcs(
    player_id: uuid.UUID = Depends(get_current_player_id),
    service: DlcLicenseService = Depends(get_dlc_license_service),
):
    """So pra UI. Nunca decide liberacao de material sozinha."""
    slugs = await service.list_authorized_dlc_slugs(player_id)
    return DlcAuthorizedList(dlc_slugs=slugs)


class AuthorizeResponse(BaseModel):
    authorization_token: str
    expires_in: int


@launcher_dlc_router.post("/dlc/{dlc_slug}/authorize", response_model=AuthorizeResponse)
async def authorize_dlc(
    dlc_slug: str,
    player_id: uuid.UUID = Depends(get_current_player_id),
    service: DlcLicenseService = Depends(get_dlc_license_service),
    x_launcher_session_id: str | None = Header(default=None),
):
    """PASSO 1. Confirma que o player pode acessar esta DLC agora e grava a
    autorizacao no banco (DlcAuthorization, status=ISSUED). O token
    devolvido NAO contem nenhum segredo criptografico -- so prova "fui
    autorizado, aqui esta o jti pra provar isso no passo 2"."""
    try:
        await _authorize_limiter.hit(str(player_id))
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        token = await service.issue_authorization(player_id, dlc_slug, session_id=x_launcher_session_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="DLC nao autorizada.")
    return AuthorizeResponse(authorization_token=token, expires_in=AUTHORIZATION_TTL_SECONDS)


class MaterialRequest(BaseModel):
    authorization_token: str


class MaterialResponse(BaseModel):
    key_hex: str


@launcher_dlc_router.post("/dlc/{dlc_slug}/material", response_model=MaterialResponse)
async def redeem_dlc_material(
    dlc_slug: str,
    body: MaterialRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    service: DlcLicenseService = Depends(get_dlc_license_service),
):
    """PASSO 2. Troca o token de autorizacao pela chave real -- SO UMA VEZ
    (consumo atomico no banco, ver DlcAuthorizationRepository.
    consume_atomically). Uma segunda chamada com o mesmo token, de
    qualquer origem, recebe 403 -- nao importa se veio do mesmo launcher
    ou de uma copia do token levada pra outra maquina (ataque 3 e 7)."""
    try:
        await _material_limiter.hit(str(player_id))
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    try:
        key_bytes = await service.redeem_key_material(
            body.authorization_token, requesting_player_id=player_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return MaterialResponse(key_hex=key_bytes.hex())
