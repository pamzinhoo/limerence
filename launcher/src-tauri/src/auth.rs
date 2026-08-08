use serde::Serialize;
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use uuid::Uuid;

use crate::api_client::{ApiClient, TokenResponse};
use crate::keychain;

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LoginStatus {
    WaitingBrowser { user_code: String, verification_uri: String },
    Success,
    Expired,
    Denied,
    Error { message: String },
}

const STATUS_EVENT: &str = "auth://status";

fn emit_status(app: &AppHandle, status: LoginStatus) {
    let _ = app.emit(STATUS_EVENT, status);
}

/// Orquestra o Device Authorization Flow (simulado, ver
/// bot/docs/AUTH_API_CONTRACT.md) do lado do Launcher: pede device_code,
/// abre o navegador do sistema, e faz poll ate o backend confirmar o login
/// (ou expirar/ser negado). O Launcher nunca fala com o Discord diretamente
/// — so abre a pagina do backend.
pub async fn start_login(
    app: AppHandle,
    api: ApiClient,
    device_uuid: Uuid,
    launcher_version: String,
) -> Result<Option<TokenResponse>, String> {
    let issued = match api
        .device_code(device_uuid, Some(os_info()), Some(launcher_version))
        .await
    {
        Ok(issued) => issued,
        Err(e) => {
            emit_status(&app, LoginStatus::Error { message: e.to_string() });
            return Err(e.to_string());
        }
    };

    emit_status(
        &app,
        LoginStatus::WaitingBrowser {
            user_code: issued.user_code.clone(),
            verification_uri: issued.verification_uri.clone(),
        },
    );

    if let Err(e) = open::that(&issued.verification_uri) {
        emit_status(
            &app,
            LoginStatus::Error {
                message: format!("Nao foi possivel abrir o navegador: {e}"),
            },
        );
        return Err(e.to_string());
    }

    let mut interval = Duration::from_secs(issued.interval.max(1));
    let deadline = tokio::time::Instant::now() + Duration::from_secs(issued.expires_in);

    loop {
        if tokio::time::Instant::now() >= deadline {
            emit_status(&app, LoginStatus::Expired);
            return Ok(None);
        }
        tokio::time::sleep(interval).await;

        let poll = match api.poll_device_token(&issued.device_code).await {
            Ok(poll) => poll,
            Err(e) => {
                emit_status(&app, LoginStatus::Error { message: e.to_string() });
                return Err(e.to_string());
            }
        };

        match poll.status.as_str() {
            "authorization_pending" => continue,
            "slow_down" => {
                interval = Duration::from_secs(poll.interval.unwrap_or(interval.as_secs() * 2).max(1));
                continue;
            }
            "success" => {
                let refresh_token = poll.refresh_token.ok_or("resposta de sucesso sem refresh_token")?;
                let access_token = poll.access_token.ok_or("resposta de sucesso sem access_token")?;
                keychain::save_refresh_token(&refresh_token)?;
                emit_status(&app, LoginStatus::Success);
                return Ok(Some(TokenResponse {
                    access_token,
                    refresh_token,
                    expires_in: poll.expires_in.unwrap_or(900),
                }));
            }
            "expired_token" => {
                emit_status(&app, LoginStatus::Expired);
                return Ok(None);
            }
            "access_denied" => {
                emit_status(&app, LoginStatus::Denied);
                return Ok(None);
            }
            other => {
                emit_status(
                    &app,
                    LoginStatus::Error {
                        message: format!("status de poll desconhecido: {other}"),
                    },
                );
                return Ok(None);
            }
        }
    }
}

/// Rodado na abertura do Launcher: se ha refresh token no keychain, tenta
/// validar/rotacionar contra o backend. Qualquer falha (revogado, expirado,
/// reuso detectado) e tratada como "nao logado" — limpa o keychain e deixa o
/// fluxo de login normal assumir, nunca trava o app.
pub async fn check_session(api: &ApiClient, device_uuid: Uuid) -> Option<TokenResponse> {
    let refresh_token = keychain::load_refresh_token()?;
    match api.refresh(&refresh_token, device_uuid).await {
        Ok(tokens) => {
            if let Err(e) = keychain::save_refresh_token(&tokens.refresh_token) {
                eprintln!("[auth] falha ao persistir refresh token rotacionado: {e}");
            }
            Some(tokens)
        }
        Err(_) => {
            keychain::clear_refresh_token();
            None
        }
    }
}

pub async fn logout(api: &ApiClient, refresh_token: Option<String>) {
    if let Some(token) = refresh_token {
        // best-effort: se a rede cair aqui, o keychain local ainda e limpo —
        // pior caso e a sessao no backend expirar sozinha pelo TTL.
        let _ = api.logout(&token).await;
    }
    keychain::clear_refresh_token();
}

fn os_info() -> String {
    format!("{} {}", std::env::consts::OS, std::env::consts::ARCH)
}
