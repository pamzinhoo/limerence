from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from api.routes.internal_routes import router as internal_router
from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.product import Product, ProductType

_SECRET = "test-internal-secret"


def _sign(body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    manifest = f"{ts}.".encode() + body
    signature = hmac.new(_SECRET.encode(), manifest, hashlib.sha256).hexdigest()
    return {"X-Internal-Timestamp": ts, "X-Internal-Signature": signature}


def _product(**overrides: object) -> Product:
    product = Product(
        slug="the-empress", name="The Empress", product_type=ProductType.DLC,
        description=None, price_amount=None, currency="BRL", position=0, is_active=True,
    )
    product.id = uuid.uuid4()
    for key, value in overrides.items():
        setattr(product, key, value)
    return product


def _plan(**overrides: object) -> MagicMock:
    plan = MagicMock()
    plan.id = uuid.uuid4()
    plan.name = "The Empress"
    plan.guild_id = 1
    plan.role_id = None
    plan.product_id = None
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


def _manifest_entry(**overrides: object) -> GameManifestEntry:
    entry = GameManifestEntry(
        product_id=uuid.uuid4(), version="1.0.0", sha256="a" * 64, size_bytes=1024,
        storage_path="products/the-empress/1.0.0.pkg", entry_type=ManifestEntryType.FULL,
        depends_on=[], is_current=True,
    )
    entry.id = uuid.uuid4()
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


class _App:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.app.state.settings = MagicMock(internal_api_secret=_SECRET)
        self.app.state.product_service = AsyncMock()
        self.app.state.plan_service = AsyncMock()
        self.app.state.launcher_content_service = AsyncMock()
        # rotas do router que este teste nao exercita, mas que o modulo
        # importa em TYPE_CHECKING; nao precisam de app.state real aqui.
        self.app.include_router(internal_router)

    async def request(self, method: str, path: str, json_body: dict | None = None) -> httpx.Response:
        body = json.dumps(json_body).encode() if json_body is not None else b""
        headers = _sign(body)
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                method, path, content=body, headers={**headers, "Content-Type": "application/json"}
            )


@pytest.fixture
def api() -> _App:
    return _App()


class TestCreateDlc:
    async def test_creates_product_and_plan(self, api: _App) -> None:
        product = _product()
        plan = _plan()
        updated_plan = _plan(id=plan.id, role_id=999, product_id=product.id)
        api.app.state.product_service.get_by_slug = AsyncMock(return_value=None)
        api.app.state.product_service.create = AsyncMock(return_value=product)
        api.app.state.plan_service.create_plan = AsyncMock(return_value=plan)
        api.app.state.plan_service.update_plan = AsyncMock(return_value=updated_plan)

        response = await api.request(
            "POST", "/internal/products/dlc",
            {"guild_id": 1, "slug": "the-empress", "name": "The Empress", "role_id": 999},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["product_id"] == str(product.id)
        assert body["plan_id"] == str(plan.id)
        assert body["role_id"] == 999
        api.app.state.plan_service.update_plan.assert_awaited_once()
        _, kwargs = api.app.state.plan_service.update_plan.call_args
        assert kwargs["product_id"] == product.id
        assert kwargs["role_id"] == 999

    async def test_slug_conflict_returns_409(self, api: _App) -> None:
        api.app.state.product_service.get_by_slug = AsyncMock(return_value=_product())

        response = await api.request(
            "POST", "/internal/products/dlc",
            {"guild_id": 1, "slug": "the-empress", "name": "The Empress", "role_id": 999},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "dlc_slug_taken"
        api.app.state.product_service.create.assert_not_called()

    async def test_plan_name_conflict_rolls_back_product(self, api: _App) -> None:
        product = _product()
        api.app.state.product_service.get_by_slug = AsyncMock(return_value=None)
        api.app.state.product_service.create = AsyncMock(return_value=product)
        api.app.state.product_service.soft_delete = AsyncMock(return_value=product)
        api.app.state.plan_service.create_plan = AsyncMock(side_effect=ValueError("Ja existe um plano..."))

        response = await api.request(
            "POST", "/internal/products/dlc",
            {"guild_id": 1, "slug": "the-empress", "name": "The Empress", "role_id": 999},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "dlc_plan_name_taken"
        api.app.state.product_service.soft_delete.assert_awaited_once_with(product.id)

    async def test_does_not_touch_license_or_role_grant(self, api: _App) -> None:
        """Confirma a separacao pedida: criar DLC nao chama nada de
        License/role grant — so Product + Plan."""
        product = _product()
        plan = _plan()
        api.app.state.product_service.get_by_slug = AsyncMock(return_value=None)
        api.app.state.product_service.create = AsyncMock(return_value=product)
        api.app.state.plan_service.create_plan = AsyncMock(return_value=plan)
        api.app.state.plan_service.update_plan = AsyncMock(return_value=plan)

        await api.request(
            "POST", "/internal/products/dlc",
            {"guild_id": 1, "slug": "the-empress", "name": "The Empress", "role_id": 999},
        )

        assert not hasattr(api.app.state, "license_service") or not api.app.state.license_service.method_calls


class TestPublishManifestEntry:
    async def test_publishes_and_marks_current(self, api: _App) -> None:
        product = _product()
        entry = _manifest_entry(product_id=product.id)
        api.app.state.product_service.get = AsyncMock(return_value=product)
        api.app.state.launcher_content_service.publish_manifest_entry = AsyncMock(return_value=entry)

        response = await api.request(
            "POST", f"/internal/products/{product.id}/manifest",
            {
                "version": "1.0.0", "sha256": "a" * 64, "size_bytes": 1024,
                "storage_path": "products/the-empress/1.0.0.pkg",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["version"] == "1.0.0"
        assert body["is_current"] is True

    async def test_product_not_found_returns_404(self, api: _App) -> None:
        api.app.state.product_service.get = AsyncMock(return_value=None)

        response = await api.request(
            "POST", f"/internal/products/{uuid.uuid4()}/manifest",
            {
                "version": "1.0.0", "sha256": "a" * 64, "size_bytes": 1024,
                "storage_path": "products/x/1.0.0.pkg",
            },
        )

        assert response.status_code == 404

    async def test_invalid_sha256_returns_400(self, api: _App) -> None:
        product = _product()
        api.app.state.product_service.get = AsyncMock(return_value=product)

        response = await api.request(
            "POST", f"/internal/products/{product.id}/manifest",
            {
                "version": "1.0.0", "sha256": "too-short", "size_bytes": 1024,
                "storage_path": "products/x/1.0.0.pkg",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_sha256"

    async def test_invalid_entry_type_returns_400(self, api: _App) -> None:
        product = _product()
        api.app.state.product_service.get = AsyncMock(return_value=product)

        response = await api.request(
            "POST", f"/internal/products/{product.id}/manifest",
            {
                "version": "1.0.0", "sha256": "a" * 64, "size_bytes": 1024,
                "storage_path": "products/x/1.0.0.pkg", "entry_type": "bogus",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_entry_type"
