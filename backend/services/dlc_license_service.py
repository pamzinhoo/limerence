"""
dlc_license_service.py (v3)
=============================

MUDANCA DE DESIGN em relacao a v2 (motivo: ponto 7 do pedido do usuario —
"nao coloque a chave AES diretamente no JWT").

v2 (ERRADO, corrigido aqui): 1 endpoint devolvia um JWT que ja carregava a
chave AES em texto (`payload["key"]`). Isso mistura duas coisas que devem
ser separadas:
  - AUTORIZACAO: "este player pode, agora, acessar o material desta DLC?"
  - SEGREDO CRIPTOGRAFICO: a chave em si.

Por que isso importa de verdade (nao e so estetica):
  - um JWT de autorizacao pode circular por logs de proxy/CDN, ferramentas
    de observabilidade, mensagens de erro — nenhum desses lugares deveria
    jamais conter uma chave AES em texto claro;
  - separar os dois passos permite que o passo de ENTREGA DA CHAVE seja o
    unico ponto do sistema que precisa de tratamento especial (nao logar
    corpo da resposta, TTL ainda mais curto, consumo atomico de uso unico)
    sem precisar aplicar essas restricoes em toda rota que so verifica
    autorizacao.

v3 (este arquivo): dois metodos.
  1. `issue_authorization()` -> cria uma linha em DlcAuthorization
     (status=ISSUED) e devolve um JWT curto que representa SO a
     autorizacao (player, dlc, jti, expiracao) — sem nenhum segredo.
  2. `redeem_key_material()` -> recebe esse JWT, RECHECA licenca (pode ter
     mudado entre os dois passos), e so entao tenta consumir o jti de forma
     ATOMICA (DlcAuthorizationRepository.consume_atomically). So se
     conseguir consumir (primeira e unica vez) e que desembrulha e devolve
     a chave real.

Isso implementa o ponto 14 (anti-replay) com codigo de banco de verdade,
nao um TODO — ver dlc_authorization_repository.py.
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt  # PyJWT

from services import crypto_service
from database.database import Database
from database.models.dlc_authorization import DlcAuthorization
from database.models.product import ProductType
from database.repositories.dlc_authorization_repository import DlcAuthorizationRepository

if TYPE_CHECKING:
    # So pra tipagem -- LicenseService/ProductService sao recebidos prontos
    # no construtor (injecao de dependencia), este modulo nunca instancia
    # nenhum dos dois. Evita puxar em cascata os imports profundos de
    # LicenseService (core.events, database.repositories.license_repository,
    # providers.internal_events_client) so pra rodar este arquivo/testar.
    from services.license_service import LicenseService
    from services.product_service import ProductService

# Janela da AUTORIZACAO (nao do tempo de jogo — ver ponto 8 do pedido).
# 120s e tempo suficiente pro launcher: pedir autorizacao -> pedir material
# -> descriptografar -> preparar pasta. Depois disso o jogo roda livremente;
# nada nesta janela controla quanto tempo o usuario pode jogar.
AUTHORIZATION_TTL_SECONDS = 120


def _load_signing_secret() -> str:
    import os
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY nao configurado no backend.")
    return secret


@dataclass
class AuthorizationResult:
    authorized: bool
    reason: str


class DlcLicenseService:
    def __init__(
        self,
        database: Database,
        license_service: LicenseService,
        product_service: ProductService,
    ):
        self._database = database
        self._licenses = license_service
        self._products = product_service

    # ------------------------------------------------------------------
    async def list_authorized_dlc_slugs(self, player_id: uuid.UUID) -> list[str]:
        """So pra UI (loja do launcher). Nunca usado pra decidir liberacao
        de material — essa decisao sempre repassa pelos dois metodos
        abaixo, com checagem nova."""
        active_licenses = await self._licenses.list_active_by_player(player_id)
        slugs: list[str] = []
        for lic in active_licenses:
            product = await self._products.get(lic.product_id)
            if product is not None and product.product_type == ProductType.DLC:
                slugs.append(product.slug)
        return slugs

    async def _check_authorization(self, player_id: uuid.UUID, dlc_slug: str):
        """Checagem compartilhada pelos dois passos — cada um chama isto
        de novo, do zero, sem reaproveitar resultado do outro."""
        product = await self._products.get_by_slug(dlc_slug)
        if product is None or not product.is_active:
            return None, AuthorizationResult(False, "DLC inexistente ou inativa.")
        if product.product_type != ProductType.DLC:
            return None, AuthorizationResult(False, "Produto nao e uma DLC.")

        has_license = await self._licenses.has_active_license(player_id, product.id)
        if not has_license:
            return None, AuthorizationResult(False, "Sem licenca ativa para esta DLC.")

        return product, AuthorizationResult(True, "ok")

    # ------------------------------------------------------------------
    # PASSO 1: autorizacao (sem segredo nenhum no token)
    # ------------------------------------------------------------------
    async def issue_authorization(
        self, player_id: uuid.UUID, dlc_slug: str, *, session_id: str | None = None
    ) -> str:
        """Levanta PermissionError se nao autorizado. Se autorizado, grava
        uma linha DlcAuthorization(status=ISSUED) e devolve um JWT contendo
        SO: player, dlc, jti, expiracao. Nenhuma chave aqui."""
        product, result = await self._check_authorization(player_id, dlc_slug)
        if not result.authorized or product is None:
            raise PermissionError(result.reason)

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=AUTHORIZATION_TTL_SECONDS)
        jti = secrets.token_hex(16)

        async with self._database.session() as session:
            await DlcAuthorizationRepository(session).add(
                DlcAuthorization(
                    player_id=player_id,
                    product_id=product.id,
                    jti=jti,
                    expires_at=expires_at,
                    session_id=session_id,
                )
            )

        payload = {
            "sub": str(player_id),
            "dlc": dlc_slug,
            "jti": jti,
            "iat": int(time.time()),
            "exp": int(expires_at.timestamp()),
        }
        return jwt.encode(payload, _load_signing_secret(), algorithm="HS256")

    # ------------------------------------------------------------------
    # PASSO 2: entrega do material criptografico (uso unico, atomico)
    # ------------------------------------------------------------------
    async def redeem_key_material(self, authorization_token: str, *, requesting_player_id: uuid.UUID) -> bytes:
        """Levanta PermissionError se: token invalido/expirado, o `sub` do
        token nao bate com o player da sessao atual (ataque 5: alguem tenta
        reusar um token de outra pessoa), ou o jti ja foi consumido/expirou
        no banco (ataque 7: replay). SO retorna a chave real (bytes) se a
        transicao atomica ISSUED->CONSUMED tiver sucesso E a licenca ainda
        estiver ativa NESTE EXATO MOMENTO (pode ter sido revogada entre o
        passo 1 e o passo 2, por menor que seja essa janela)."""
        try:
            payload = jwt.decode(authorization_token, _load_signing_secret(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise PermissionError("Autorizacao expirada. Solicite novamente.")
        except jwt.InvalidTokenError:
            raise PermissionError("Autorizacao invalida.")

        token_player_id = uuid.UUID(payload["sub"])
        if token_player_id != requesting_player_id:
            # Nunca confie em qual player o TOKEN diz ser sem comparar com
            # quem esta autenticado NESTA chamada (sessao atual). Impede
            # reuso de um token de autorizacao de outra conta.
            raise PermissionError("Token nao pertence a sessao atual.")

        dlc_slug = payload["dlc"]
        jti = payload["jti"]

        # Recheca a licenca do zero -- o passo 1 pode ter acontecido ha
        # segundos, mas "segundos" ainda e tempo suficiente pra uma
        # revogacao administrativa acontecer nesse meio tempo.
        product, result = await self._check_authorization(token_player_id, dlc_slug)
        if not result.authorized or product is None:
            raise PermissionError(result.reason)

        now = datetime.now(UTC)
        async with self._database.session() as session:
            consumed = await DlcAuthorizationRepository(session).consume_atomically(jti, now=now)

        if not consumed:
            # Ou o jti nunca existiu, ou ja foi consumido antes (replay),
            # ou expirou. Em qualquer caso: NUNCA libera a chave.
            raise PermissionError("Autorizacao ja utilizada ou expirada.")

        encrypted_key_b64 = getattr(product, "encryption_key_encrypted", None)
        if not encrypted_key_b64:
            raise RuntimeError(
                f"Product {dlc_slug} sem encryption_key_encrypted. "
                "Rode backend/scripts/package_dlc.py e grave a chave no Product."
            )
        return crypto_service.unwrap_dlc_key(encrypted_key_b64)

    # ------------------------------------------------------------------
    # Administrativo (chamado pelo bot via rota /internal/*, nunca pelo
    # launcher diretamente)
    # ------------------------------------------------------------------
    async def revoke_dlc_license(self, player_id: uuid.UUID, dlc_slug: str, *, reason: str) -> None:
        product = await self._products.get_by_slug(dlc_slug)
        if product is None:
            return
        await self._licenses.revoke_by_player_product(player_id, product.id, reason=reason)
