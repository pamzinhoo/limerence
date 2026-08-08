from __future__ import annotations

import html
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

# Logo do Discord (mesmo icone usado no botao do launcher), embutida em base64
# pra pagina de callback nao depender de asset externo/hosting a parte.
_DISCORD_LOGO_B64 = (
    "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"
    "ICa1U5MjPJoAAAAASUVORK5CYII="
)


def _render_page(heading: str, message: str, *, tone: str = "success") -> str:
    """Pagina de resultado do login, estilo Limerence (fundo escuro, acento
    roxo/blurple), aberta no navegador do sistema pelo launcher."""
    accent = "#5865F2" if tone == "success" else "#ED4245"
    if tone == "success":
        icon_html = f'<img src="data:image/png;base64,{_DISCORD_LOGO_B64}" alt="Discord">'
    else:
        icon_html = (
            '<svg viewBox="0 0 24 24"><path d="M12 2 1 21h22L12 2zm0 15h-.01M11 10h2v5h-2z"/></svg>'
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
    width: 72px; height: 72px; margin: 0 auto 20px;
    background: {accent}22; border-radius: 20px;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }}
  .icon img {{ width: 100%; height: 100%; object-fit: contain; }}
  .icon svg {{ width: 32px; height: 32px; fill: {accent}; }}
  h1 {{ color: #f2f0f7; font-size: 22px; margin: 0 0 10px; }}
  p {{ color: #a8a3b8; font-size: 15px; line-height: 1.5; margin: 0; }}
  .brand {{ margin-top: 28px; color: #524d63; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon_html}</div>
    <h1>{html.escape(heading)}</h1>
    <p>{html.escape(message)}</p>
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
