"""
test_dlc_authorization_security.py
====================================

Testes do ponto 14 do pedido ("nao considerar anti-replay implementado se
existir so um comentario TODO") e do ponto 7 ("token de autorizacao nunca
carrega o segredo, e reuso de token de outra sessao deve ser rejeitado").

Convencao seguida (igual test_subscription_domain_service_purchase.py):
Database mockado com MagicMock + asynccontextmanager fake, e a classe do
Repository (`DlcAuthorizationRepository`) trocada via `@patch` pelo mock
que o teste controla -- assim testamos a LOGICA DO SERVICO (o service
respeita o resultado do repo?), nao a garantia de atomicidade do SQL em si.

Sobre a atomicidade do UPDATE ... WHERE status='issued' (consume_atomically
em database/repositories/dlc_authorization_repository.py): essa garantia e
uma propriedade do banco relacional (transacao + condicao no WHERE), nao
algo que um teste unitario com mock consiga provar sozinho. Recomendacao
HONESTA (nao finjo que isto cobre 100%): validar com um teste de integracao
contra Postgres de verdade disparando duas chamadas concorrentes pro mesmo
jti e conferindo que so uma teve rowcount=1 -- isso fica fora do escopo
deste arquivo porque exige infra de teste com banco real que o projeto
ainda nao tem configurada em backend/tests/ (nenhum dos testes existentes
aqui usa banco real, todos usam mock -- ver os 6 arquivos em backend/tests/).
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import base64
import os

import jwt
import pytest

from database.models.product import Product, ProductType
from services import crypto_service
from services.dlc_license_service import AUTHORIZATION_TTL_SECONDS, DlcLicenseService

_JWT_SECRET = "test-jwt-secret-nao-usar-em-producao"
_MASTER_KEY_B64 = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def _security_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
    monkeypatch.setenv("DLC_MASTER_KEY", _MASTER_KEY_B64)


def _database() -> MagicMock:
    database = MagicMock()

    @asynccontextmanager
    async def _session_cm():
        yield MagicMock()

    database.session = _session_cm
    return database


def _dlc_product(**overrides: object) -> Product:
    product = Product(
        slug="DLC_001", name="Capitulo Extra", product_type=ProductType.DLC,
        description=None, price_amount=None, currency="BRL", position=0, is_active=True,
    )
    product.id = uuid.uuid4()
    # Chave AES-256 real da DLC, "wrapped" com a master key de teste --
    # nao um placeholder inerte, pra unwrap_dlc_key() no servico funcionar
    # de verdade durante o teste (mesmo caminho de codigo que producao).
    product.encryption_key_encrypted = crypto_service.wrap_dlc_key(crypto_service.generate_dlc_key())
    for key, value in overrides.items():
        setattr(product, key, value)
    return product


def _service(*, license_service: AsyncMock, product_service: AsyncMock) -> DlcLicenseService:
    return DlcLicenseService(_database(), license_service, product_service)


def _authorized_mocks(product: Product) -> tuple[AsyncMock, AsyncMock]:
    license_service = AsyncMock()
    license_service.has_active_license = AsyncMock(return_value=True)
    product_service = AsyncMock()
    product_service.get_by_slug = AsyncMock(return_value=product)
    return license_service, product_service


class TestIssueAuthorizationCarriesNoSecret:
    async def test_authorization_token_never_contains_the_key(self) -> None:
        """Ponto 7: decodifica o token de autorizacao e confirma que NAO
        existe campo de chave nele -- so prova de autorizacao (sub, dlc,
        jti, exp)."""
        product = _dlc_product()
        license_service, product_service = _authorized_mocks(product)
        service = _service(license_service=license_service, product_service=product_service)

        with patch("services.dlc_license_service.DlcAuthorizationRepository") as repo_cls:
            repo_cls.return_value.add = AsyncMock()
            token = await service.issue_authorization(uuid.uuid4(), "DLC_001")

        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
        assert set(payload.keys()) == {"sub", "dlc", "jti", "iat", "exp"}
        assert "key" not in payload
        assert payload["exp"] - payload["iat"] == AUTHORIZATION_TTL_SECONDS


class TestReplayIsRejected:
    async def test_second_redeem_with_same_token_is_rejected(self) -> None:
        """Ponto 14, ataque 7: consume_atomically simula EXATAMENTE o
        comportamento real -- True na primeira chamada, False na segunda
        (porque o UPDATE...WHERE status='issued' so afeta linha na primeira
        vez). O servico tem que respeitar isso e recusar a segunda."""
        product = _dlc_product()
        license_service, product_service = _authorized_mocks(product)
        player_id = uuid.uuid4()
        service = _service(license_service=license_service, product_service=product_service)

        with patch("services.dlc_license_service.DlcAuthorizationRepository") as repo_cls:
            repo_cls.return_value.add = AsyncMock()
            token = await service.issue_authorization(player_id, "DLC_001")

            # primeira tentativa: consome com sucesso
            repo_cls.return_value.consume_atomically = AsyncMock(return_value=True)
            key = await service.redeem_key_material(token, requesting_player_id=player_id)
            assert isinstance(key, bytes)

            # segunda tentativa com o MESMO token: consume_atomically agora
            # devolve False (jti ja consumido) -- e o unico jeito real do
            # banco expressar "isso ja foi usado".
            repo_cls.return_value.consume_atomically = AsyncMock(return_value=False)
            with pytest.raises(PermissionError, match="ja utilizada ou expirada"):
                await service.redeem_key_material(token, requesting_player_id=player_id)


class TestExpiredTokenIsRejected:
    async def test_expired_authorization_token_is_rejected(self) -> None:
        """Token com exp no passado -- PyJWT recusa antes mesmo de chegar
        no banco."""
        expired_payload = {
            "sub": str(uuid.uuid4()),
            "dlc": "DLC_001",
            "jti": "whatever",
            "iat": int(time.time()) - 1000,
            "exp": int(time.time()) - 500,
        }
        expired_token = jwt.encode(expired_payload, _JWT_SECRET, algorithm="HS256")

        product = _dlc_product()
        license_service, product_service = _authorized_mocks(product)
        service = _service(license_service=license_service, product_service=product_service)

        with pytest.raises(PermissionError, match="expirada"):
            await service.redeem_key_material(
                expired_token, requesting_player_id=uuid.UUID(expired_payload["sub"])
            )


class TestTokenCannotBeRedeemedByAnotherSession:
    async def test_redeem_rejects_when_requesting_player_differs_from_token_subject(self) -> None:
        """Ponto 6/ataque 5: um token de autorizacao emitido pro player A,
        apresentado por uma sessao autenticada como player B, tem que ser
        recusado -- mesmo que o token em si seja valido e nao tenha
        expirado. Isso e checado ANTES de tentar consumir o jti (o jti do
        player A continua disponivel pra ele mesmo depois dessa tentativa
        falha de B)."""
        product = _dlc_product()
        license_service, product_service = _authorized_mocks(product)
        player_a = uuid.uuid4()
        player_b = uuid.uuid4()
        service = _service(license_service=license_service, product_service=product_service)

        with patch("services.dlc_license_service.DlcAuthorizationRepository") as repo_cls:
            repo_cls.return_value.add = AsyncMock()
            token = await service.issue_authorization(player_a, "DLC_001")

            repo_cls.return_value.consume_atomically = AsyncMock()
            with pytest.raises(PermissionError, match="nao pertence a sessao atual"):
                await service.redeem_key_material(token, requesting_player_id=player_b)

            # nunca deve ter tentado consumir o jti pra uma sessao errada
            repo_cls.return_value.consume_atomically.assert_not_called()


class TestRevocationBetweenStepsIsRespected:
    async def test_license_revoked_between_authorize_and_redeem_blocks_material(self) -> None:
        """Ponto 6 da secao 8 (a checagem tem que ser AO VIVO): mesmo com
        um token de autorizacao valido e nao expirado, se a licenca foi
        revogada depois do passo 1, o passo 2 tem que recusar -- e sem
        consumir o jti (pra nao desperdicar a tentativa caso a revogacao
        seja temporaria/erro administrativo corrigido depois)."""
        product = _dlc_product()
        license_service, product_service = _authorized_mocks(product)
        player_id = uuid.uuid4()
        service = _service(license_service=license_service, product_service=product_service)

        with patch("services.dlc_license_service.DlcAuthorizationRepository") as repo_cls:
            repo_cls.return_value.add = AsyncMock()
            token = await service.issue_authorization(player_id, "DLC_001")

            # revogacao acontece "entre os passos"
            license_service.has_active_license = AsyncMock(return_value=False)
            repo_cls.return_value.consume_atomically = AsyncMock()

            with pytest.raises(PermissionError, match="Sem licenca ativa"):
                await service.redeem_key_material(token, requesting_player_id=player_id)

            repo_cls.return_value.consume_atomically.assert_not_called()
