from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.auth_routes import router as auth_router
from api.routes.download_routes import router as download_router
from api.routes.health_routes import router as health_router
from api.routes.internal_routes import router as internal_router
from api.routes.launcher_routes import router as launcher_router
from api.routes.player_routes import router as player_router
from api.routes.shop_routes import router as shop_router
from api.routes.webhook_routes import router as webhook_router
from config.settings import Settings, get_settings
from core.logger import get_logger, setup_logging
from database.database import Database, init_database
from providers.internal_events_client import InternalEventsClient
from providers.storage.base import StorageProvider
from services.auth_service import AuthService
from services.coupon_service import CouponService
from services.download_service import DownloadService
from services.launcher_content_service import LauncherContentService
from services.license_service import LicenseService
from services.payment_service import PaymentService
from services.plan_service import PlanService
from services.player_service import PlayerService
from services.product_service import ProductService
from services.subscription_domain_service import SubscriptionDomainService
from services.subscription_notification_publisher import SubscriptionNotificationPublisher
from services.subscription_renewal_config_service import SubscriptionRenewalConfigService
from services.subscription_renewal_engine_service import SubscriptionRenewalEngineService
from services.webhook_service import WebhookService

logger = get_logger("api")


def _build_storage_provider(settings: Settings) -> StorageProvider | None:
    if not settings.storage_configured:
        logger.warning(
            "Storage (STORAGE_BUCKET/STORAGE_ACCESS_KEY_ID/STORAGE_SECRET_ACCESS_KEY) nao "
            "configurado — /download e /update responderao 503 ate configurar."
        )
        return None
    from providers.storage.s3_compatible import S3CompatibleStorageProvider

    return S3CompatibleStorageProvider(
        name=settings.storage_provider,
        bucket=settings.storage_bucket,  # type: ignore[arg-type]
        access_key_id=settings.storage_access_key_id,  # type: ignore[arg-type]
        secret_access_key=settings.storage_secret_access_key,  # type: ignore[arg-type]
        endpoint_url=settings.storage_endpoint_url,
        region_name=settings.storage_region,
    )


def _build_internal_events_client(settings: Settings) -> InternalEventsClient | None:
    if not settings.internal_api_secret or not settings.bot_internal_base_url:
        logger.warning(
            "INTERNAL_API_SECRET/BOT_INTERNAL_BASE_URL nao configurados — eventos internos "
            "(licenca/assinatura) nao serao notificados ao bot ate configurar."
        )
        return None
    return InternalEventsClient(
        settings.bot_internal_base_url,
        settings.internal_api_secret,
        timeout_seconds=settings.internal_events_timeout_seconds,
    )


_STARTUP_MIGRATION_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audit_log_launcher_action') THEN
    CREATE TYPE audit_log_launcher_action AS ENUM (
      'LOGIN_SUCCESS','LOGIN_FAILED','REFRESH_ROTATED','REFRESH_REUSE_DETECTED',
      'LOGOUT','LOGOUT_ALL','DEVICE_REVOKED','RATE_LIMITED'
    );
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS audit_log_launcher (
  player_id UUID,
  device_id UUID,
  action audit_log_launcher_action NOT NULL,
  ip_address INET,
  audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL,
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_audit_log_launcher_player_id ON audit_log_launcher (player_id);

CREATE INDEX IF NOT EXISTS ix_audit_log_launcher_device_id ON audit_log_launcher (device_id);

CREATE INDEX IF NOT EXISTS ix_audit_log_launcher_action ON audit_log_launcher (action);

ALTER TABLE plans ADD COLUMN IF NOT EXISTS product_id UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_plans_product_id_products'
  ) THEN
    ALTER TABLE plans ADD CONSTRAINT fk_plans_product_id_products
      FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL;
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_plans_product_id ON plans (product_id);

ALTER TABLE payment_history ADD COLUMN IF NOT EXISTS purchase_idempotency_key VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_history_purchase_idempotency_key
  ON payment_history (purchase_idempotency_key);

UPDATE alembic_version SET version_num = 'd4f8a1c6b9e3'
  WHERE version_num <> 'd4f8a1c6b9e3';
"""


async def _run_startup_migrations(database: Database) -> None:
    """Fix pontual: o alembic_version de producao ficou apontando pra uma
    revisao orfa (de um branch descartado no force-push do repo bot), entao
    `alembic upgrade head` normal nao roda mais. Aplica direto (idempotente,
    mesmo SQL das migrations a7d3f9c2b1e6/c2f5e8a1d4b7/d4f8a1c6b9e3) e realinha
    o ponteiro. Seguro rodar toda subida (tudo IF NOT EXISTS)."""
    from sqlalchemy import text

    try:
        async with database.engine.begin() as conn:
            for statement in _STARTUP_MIGRATION_SQL.strip().split(";\n\n"):
                statement = statement.strip().rstrip(";")
                if statement:
                    await conn.execute(text(statement))
        logger.info("Startup migrations (audit_log_launcher/plan_product_link/idempotency_key) OK.")
    except Exception:
        logger.exception("Falha ao rodar startup migrations — verificar schema manualmente.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.internal_api_configured:
        logger.warning(
            "INTERNAL_API_SECRET nao configurado — /internal/* responderao 503 ate configurar."
        )

    database = init_database(settings.database_url, echo=settings.log_level == "DEBUG")
    await database.check_connection()
    await _run_startup_migrations(database)

    internal_events_client = _build_internal_events_client(settings)

    app.state.settings = settings
    app.state.database = database
    app.state.internal_events_client = internal_events_client

    app.state.auth_service = AuthService(database, settings, internal_events_client)
    app.state.license_service = LicenseService(database, internal_events_client)
    app.state.product_service = ProductService(database)
    app.state.coupon_service = CouponService(database)
    app.state.payment_service = PaymentService(database, settings)
    app.state.plan_service = PlanService(database)
    app.state.player_service = PlayerService(database)
    app.state.launcher_content_service = LauncherContentService(database)
    app.state.download_service = DownloadService(
        database, app.state.license_service, _build_storage_provider(settings), settings
    )
    app.state.subscription_renewal_config_service = SubscriptionRenewalConfigService(database)

    # SubscriptionDomainService — primeiro consumidor real (Fase 5, prova de
    # conceito de bot/cogs/subscriptions.py). Publisher usa o mesmo
    # InternalEventsClient acima; se nao configurado, publisher fica inerte
    # (mesmo fallback gracioso das Fases 3C-1/3D-1).
    subscription_publisher = SubscriptionNotificationPublisher(internal_events_client)
    app.state.subscription_domain_service = SubscriptionDomainService(
        database,
        app.state.payment_service,
        app.state.license_service,
        app.state.coupon_service,
        subscription_publisher,
    )

    # WebhookService precisa do SubscriptionDomainService pra completar o
    # ProcessPaymentWebhookUseCase (Fase 5.5) — validar/confirmar no gateway
    # e so despachar a transicao de estado real. Endpoint continua "so
    # preparacao": o Mercado Pago ainda aponta pro webhook do bot em
    # producao (bot/api roda em paralelo ate a Fase 6), entao ligar isto
    # aqui nao muda nenhum comportamento observavel hoje.
    app.state.webhook_service = WebhookService(
        database, settings, app.state.payment_service, app.state.subscription_domain_service
    )

    # Motor de renovacao (Fase Final) — extraido inteiro de
    # bot/services/subscription_reminder_service.py. Depende do mesmo
    # SubscriptionDomainService acima (expire_subscription).
    app.state.subscription_renewal_engine_service = SubscriptionRenewalEngineService(
        database, app.state.subscription_renewal_config_service, app.state.subscription_domain_service
    )

    logger.info("Backend iniciado (environment=%s, port=%s)", settings.environment, settings.api_port)
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    """Monta a API oficial do sistema. A partir da Fase 4, o Backend passa a
    ser a fonte de verdade da API HTTP — `bot/api` continua rodando em
    paralelo ate a Fase 6 (descomissionamento), sem nenhuma alteracao."""
    app = FastAPI(title="Limerence Backend API", docs_url=None, redoc_url=None, lifespan=lifespan)

    settings = get_settings()

    # CORS explicito, negando toda origem por padrao (Launcher/Tauri fala
    # Bearer token, nao navegador/cookie). CORS_ALLOWED_ORIGINS so existe pra
    # um eventual frontend web (ex.: painel staff) chamando esta API direto
    # do navegador.
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(auth_router)
    app.include_router(launcher_router)
    app.include_router(player_router)
    app.include_router(download_router)
    app.include_router(internal_router)
    app.include_router(shop_router)
    return app
