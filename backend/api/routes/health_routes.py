from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from config.settings import Settings
from database.database import Database

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    database: Database = request.app.state.database
    try:
        await database.check_connection()
    except Exception as exc:  # noqa: BLE001 - health check reporta qualquer falha de conexao
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "degraded", "database": "unreachable", "error": str(exc)},
        ) from exc
    return {"status": "ok", "environment": settings.environment, "database": "ok"}


@router.get("/payments/status")
async def payments_status(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "webhook_enabled": settings.webhook_enabled,
        "payment_mode": settings.payment_mode,
    }
