from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from api.dependencies import get_client_ip, get_current_player
from api.schemas.auth import (
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceTokenRequest,
    DeviceTokenResponse,
    LogoutAllResponse,
    LogoutRequest,
    PlayerResponse,
    RefreshRequest,
    TokenResponse,
)
from core.logger import get_logger
from core.rate_limiter import RateLimitExceeded
from services.auth_service import AuthError

if TYPE_CHECKING:
    from database.models.player import Player
    from services.auth_service import AuthService

logger = get_logger("auth_routes")

router = APIRouter(prefix="/auth", tags=["auth"])


def _render_page(heading: str, message: str, *, tone: str = "success") -> str:
    """Pagina de resultado do login, estilo Limerence (fundo escuro, acento
    roxo/blurple), aberta no navegador do sistema pelo launcher."""
    accent = "#5865F2" if tone == "success" else "#ED4245"
    icon = (
        "<path d=\"M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z\"/>"
        if tone == "success"
        else "<path d=\"M12 2 1 21h22L12 2zm0 15h-.01M11 10h2v5h-2z\"/>"
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Limerence</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body {{
    height: 100%; margin: 0;
    background: radial-gradient(circle at 50% 20%, #1a1625 0%, #0c0a12 65%);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 48px 56px;
    text-align: center;
    max-width: 420px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }}
  .icon {{
    width: 56px; height: 56px; margin: 0 auto 20px;
    background: {accent}22; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
  }}
  .icon svg {{ width: 28px; height: 28px; fill: {accent}; }}
  h1 {{ color: #f2f0f7; font-size: 22px; margin: 0 0 10px; }}
  p {{ color: #a8a3b8; font-size: 15px; line-height: 1.5; margin: 0; }}
  .brand {{ margin-top: 28px; color: #524d63; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon"><svg viewBox="0 0 24 24">{icon}</svg></div>
    <h1>{heading}</h1>
    <p>{message}</p>
    <div class="brand">Limerence</div>
  </div>
</body>
</html>"""

_ERROR_STATUS: dict[str, int] = {
    "invalid_user_code": status.HTTP_404_NOT_FOUND,
    "invalid_state": status.HTTP_400_BAD_REQUEST,
    "discord_exchange_failed": status.HTTP_502_BAD_GATEWAY,
    "discord_token_exchange_failed": status.HTTP_502_BAD_GATEWAY,
    "discord_user_fetch_failed": status.HTTP_502_BAD_GATEWAY,
    "device_revoked": status.HTTP_403_FORBIDDEN,
    "invalid_refresh_token": status.HTTP_401_UNAUTHORIZED,
    "session_hijack_suspected": status.HTTP_401_UNAUTHORIZED,
    "refresh_token_expired": status.HTTP_401_UNAUTHORIZED,
    "player_banned": status.HTTP_403_FORBIDDEN,
    "invalid_token": status.HTTP_401_UNAUTHORIZED,
}


def _raise_from_auth_error(exc: AuthError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"error": exc.code, "message": str(exc)},
    ) from exc


async def _enforce_rate_limit(auth_service: AuthService, bucket: str, key: str) -> None:
    try:
        await auth_service.enforce_rate_limit(bucket, key)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "message": str(exc)},
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc


@router.post("/device/code", response_model=DeviceCodeResponse)
async def device_code(request: Request, body: DeviceCodeRequest) -> DeviceCodeResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "device_code", ip or "unknown")

    issued = await auth_service.create_device_login(
        device_uuid=body.device_uuid, os_info=body.os_info, launcher_version=body.launcher_version
    )
    return DeviceCodeResponse(
        device_code=issued.device_code,
        user_code=issued.user_code,
        verification_uri=issued.verification_uri,
        expires_in=issued.expires_in,
        interval=issued.interval,
    )


@router.get("/device/authorize")
async def device_authorize(request: Request, user_code: str) -> RedirectResponse:
    auth_service: AuthService = request.app.state.auth_service
    try:
        discord_url = await auth_service.build_discord_authorize_url(user_code=user_code)
    except AuthError as exc:
        return HTMLResponse(
            _render_page("Código inválido ou expirado", str(exc), tone="error"), status_code=404
        )
    return RedirectResponse(discord_url)


@router.get("/discord/callback")
async def discord_callback(request: Request, code: str, state: str) -> HTMLResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "callback", ip or "unknown")

    try:
        await auth_service.handle_discord_callback(code=code, state=state, ip=ip)
    except AuthError as exc:
        return HTMLResponse(
            _render_page("Não foi possível completar o login", str(exc), tone="error"), status_code=400
        )
    return HTMLResponse(
        _render_page("Login concluído!", "Pode fechar esta aba e voltar pro jogo.", tone="success")
    )


@router.get("/discord/already-linked")
async def discord_already_linked() -> HTMLResponse:
    return HTMLResponse(
        _render_page(
            "Login já efetuado",
            "Sua conta do Discord já está conectada a este jogo. Pode fechar esta aba.",
            tone="success",
        )
    )


@router.post("/device/token", response_model=DeviceTokenResponse)
async def device_token(request: Request, body: DeviceTokenRequest) -> DeviceTokenResponse:
    auth_service: AuthService = request.app.state.auth_service
    await _enforce_rate_limit(auth_service, "poll", body.device_code)

    result = await auth_service.poll_device_token(device_code=body.device_code)
    if result.status == "success" and result.tokens is not None:
        return DeviceTokenResponse(
            status=result.status,
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            token_type=result.tokens.token_type,
            expires_in=result.tokens.expires_in,
        )
    return DeviceTokenResponse(status=result.status, interval=result.interval)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, body: RefreshRequest) -> TokenResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "refresh", f"{ip}:{body.device_uuid}")

    try:
        tokens = await auth_service.refresh(refresh_token=body.refresh_token, device_uuid=body.device_uuid, ip=ip)
    except AuthError as exc:
        _raise_from_auth_error(exc)
        raise  # pragma: no cover - _raise_from_auth_error sempre levanta
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, body: LogoutRequest) -> None:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "logout", ip or "unknown")
    await auth_service.logout(refresh_token=body.refresh_token, ip=ip)


@router.post("/logout/all", response_model=LogoutAllResponse)
async def logout_all(
    request: Request, player: Player = Depends(get_current_player)
) -> LogoutAllResponse:
    auth_service: AuthService = request.app.state.auth_service
    ip = get_client_ip(request)
    await _enforce_rate_limit(auth_service, "logout", ip or "unknown")
    revoked = await auth_service.logout_all(player_id=player.id, ip=ip)
    return LogoutAllResponse(sessions_revoked=revoked)


@router.get("/me", response_model=PlayerResponse)
async def me(player: Player = Depends(get_current_player)) -> PlayerResponse:
    return PlayerResponse(
        id=player.id,
        discord_id=player.discord_id,
        discord_username=player.discord_username,
        linked_at=player.linked_at.isoformat(),
        last_login_at=player.last_login_at.isoformat() if player.last_login_at else None,
    )
