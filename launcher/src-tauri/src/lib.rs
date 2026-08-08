mod api_client;
mod auth;
mod device;
mod download;
mod environment;
mod game_launcher;
mod integrity;
mod keychain;
mod manifest;

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use uuid::Uuid;

use api_client::ApiClient;

const LAUNCHER_VERSION: &str = env!("CARGO_PKG_VERSION");
const PLAY_STATUS_EVENT: &str = "game://status";
/// `entry_type` unico usado hoje (ver bot/docs/LAUNCHER_API_CONTRACT.md
/// secao 5/7 — PATCH e suporte futuro de delta update, campo ja existe no
/// schema mas o backend so publica FULL por enquanto).
const ENTRY_TYPE_FULL: &str = "full";

/// Estado do processo, nunca persistido em disco alem do que
/// `keychain`/`device` ja gravam por conta propria. `access_token` fica so
/// em memoria — nunca escrito em arquivo (regra obrigatoria do fluxo de
/// login: token so vive na RAM do Launcher).
struct AppState {
    api: ApiClient,
    device_uuid: Uuid,
    access_token: Mutex<Option<String>>,
    refresh_token: Mutex<Option<String>>,
}

#[derive(Debug, Serialize)]
struct SessionInfo {
    logged_in: bool,
}

// Fase Final da migracao bot -> backend: destino padrao passa a ser o
// Backend (:8001), nao mais o Bot (:8000). Paridade confirmada pra todo
// endpoint que este client realmente chama (auth/device/*, auth/refresh,
// auth/logout, launcher/manifest, player/licenses, download, download/complete
// — os 8 usados por api_client.rs, todos com router equivalente no backend
// desde a Fase 4). `BACKEND_BASE_URL` e o nome novo/documentado; `LIMERENCE_API_BASE_URL`
// continua funcionando (compat com deploys existentes), igual prioridade.
fn api_base_url() -> String {
    std::env::var("BACKEND_BASE_URL")
        .or_else(|_| std::env::var("LIMERENCE_API_BASE_URL"))
        .unwrap_or_else(|_| "http://127.0.0.1:8001".to_string())
}

fn game_executable_path() -> Result<PathBuf, String> {
    std::env::var("LIMERENCE_GAME_EXECUTABLE")
        .map(PathBuf::from)
        .map_err(|_| "LIMERENCE_GAME_EXECUTABLE nao configurado — caminho do executavel do jogo ausente.".to_string())
}

/// `product_id` (UUID) do Base Game no catalogo do backend
/// (`Product.product_type=PERMANENT`, ver bot/docs/PRODUCTS_AND_LICENSES.md)
/// — precisa ser confirmado com `License` ACTIVE antes de qualquer "Jogar",
/// exatamente como qualquer DLC (nao ha caso especial pro base game na API).
fn base_game_product_id() -> Result<Uuid, String> {
    let raw = std::env::var("LIMERENCE_BASE_GAME_PRODUCT_ID")
        .map_err(|_| "LIMERENCE_BASE_GAME_PRODUCT_ID nao configurado — product_id do Base Game ausente.".to_string())?;
    Uuid::parse_str(&raw).map_err(|e| format!("LIMERENCE_BASE_GAME_PRODUCT_ID invalido ({raw:?}): {e}"))
}

/// Diretorio onde o conteudo baixado (base game + DLC) e instalado —
/// convencao padrao de builds distribuidos do Ren'Py: uma pasta `game/`
/// irma do executavel. Pode ser sobrescrito via `LIMERENCE_CONTENT_DIR`
/// (util em dev, quando o executavel nao esta ao lado de uma pasta `game/`
/// real ainda).
fn game_content_dir(executable_path: &Path) -> PathBuf {
    if let Ok(dir) = std::env::var("LIMERENCE_CONTENT_DIR") {
        return PathBuf::from(dir);
    }
    executable_path
        .parent()
        .map(|parent| parent.join("game"))
        .unwrap_or_else(|| PathBuf::from("game"))
}

#[tauri::command]
async fn check_session(state: State<'_, AppState>) -> Result<SessionInfo, String> {
    match auth::check_session(&state.api, state.device_uuid).await {
        Some(tokens) => {
            *state.access_token.lock().unwrap() = Some(tokens.access_token);
            *state.refresh_token.lock().unwrap() = Some(tokens.refresh_token);
            Ok(SessionInfo { logged_in: true })
        }
        None => Ok(SessionInfo { logged_in: false }),
    }
}

#[tauri::command]
async fn login_start(app: AppHandle, state: State<'_, AppState>) -> Result<SessionInfo, String> {
    let tokens = auth::start_login(
        app,
        state.api.clone(),
        state.device_uuid,
        LAUNCHER_VERSION.to_string(),
    )
    .await?;

    match tokens {
        Some(tokens) => {
            *state.access_token.lock().unwrap() = Some(tokens.access_token);
            *state.refresh_token.lock().unwrap() = Some(tokens.refresh_token);
            Ok(SessionInfo { logged_in: true })
        }
        None => Ok(SessionInfo { logged_in: false }),
    }
}

#[tauri::command]
async fn logout(state: State<'_, AppState>) -> Result<(), String> {
    let refresh_token = state.refresh_token.lock().unwrap().clone();
    auth::logout(&state.api, refresh_token).await;
    *state.access_token.lock().unwrap() = None;
    *state.refresh_token.lock().unwrap() = None;
    Ok(())
}

/// Progresso de `play_game`, emitido em `game://status` pro frontend mostrar
/// feedback (download em andamento, reparo, etc). Cada variante corresponde
/// a um dos 5 passos do pedido original: verificar licenca, baixar DLC,
/// validar arquivos, preparar ambiente, iniciar Ren'Py.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "stage", rename_all = "snake_case")]
enum PlayStatus {
    CheckingLicense { product_id: String },
    Downloading { product_id: String, attempt: u32 },
    Repairing { product_id: String, attempt: u32 },
    Validating { product_id: String },
    PreparingEnvironment,
    Launching,
    Started,
    Exited { success: bool, code: Option<i32> },
    Error { message: String },
}

fn emit_play_status(app: &AppHandle, status: PlayStatus) {
    let _ = app.emit(PLAY_STATUS_EVENT, status);
}

fn map_download_stage(product_id: Uuid, stage: download::Stage) -> PlayStatus {
    let product_id = product_id.to_string();
    match stage {
        download::Stage::CheckingLicense => PlayStatus::CheckingLicense { product_id },
        download::Stage::Downloading { attempt } => PlayStatus::Downloading { product_id, attempt },
        download::Stage::Repairing { attempt } => PlayStatus::Repairing { product_id, attempt },
        download::Stage::Validating => PlayStatus::Validating { product_id },
    }
}

/// Orquestra o fluxo completo de "Jogar": verificar licenca -> baixar DLC ->
/// validar arquivos -> preparar ambiente -> iniciar Ren'Py (ver
/// `docs/launcher-renpy-flow.md`). Toda chamada de rede acontece aqui, antes
/// do spawn — a partir do momento em que `game_launcher::spawn` roda, o
/// Ren'Py nao tem mais nenhum caminho de codigo de volta pro backend.
#[tauri::command]
async fn play_game(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let access_token = state
        .access_token
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "Sessao invalida — faca login antes de jogar.".to_string())?;

    let executable_path = game_executable_path()?;
    let base_product_id = base_game_product_id()?;
    let content_dir = game_content_dir(&executable_path);

    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("Nao foi possivel resolver o diretorio de config: {e}"))?;
    let state_path = manifest::state_file_path(&config_dir);

    // Base game sempre primeiro e obrigatorio; DLCs (demais Licenses ACTIVE
    // do player) sao sincronizadas em seguida, best-effort — uma falha numa
    // DLC nao impede jogar o base game (mesma logica de "owned" da tela de
    // Biblioteca: o que falhar fica pra proxima tentativa).
    let mut owned_product_ids = vec![base_product_id];
    match state.api.list_licenses(&access_token).await {
        Ok(licenses) => {
            for license in licenses {
                if license.status == "active" && license.product_id != base_product_id {
                    owned_product_ids.push(license.product_id);
                }
            }
        }
        Err(e) => {
            eprintln!("[play_game] falha ao listar licencas do player (DLCs nao serao sincronizadas agora): {e}");
        }
    }

    for (index, product_id) in owned_product_ids.iter().copied().enumerate() {
        let is_base_game = index == 0;
        let app_for_callback = app.clone();
        let result = download::ensure_installed(
            &state.api,
            &access_token,
            product_id,
            ENTRY_TYPE_FULL,
            Some(state.device_uuid),
            &content_dir,
            &state_path,
            |stage| emit_play_status(&app_for_callback, map_download_stage(product_id, stage)),
        )
        .await;

        if let Err(e) = result {
            let message = e.to_string();
            if is_base_game {
                emit_play_status(&app, PlayStatus::Error { message: message.clone() });
                return Err(message);
            }
            eprintln!("[play_game] DLC {product_id} nao pode ser sincronizada agora: {message}");
        }
    }

    emit_play_status(&app, PlayStatus::PreparingEnvironment);
    let prepared = environment::prepare(&executable_path, &content_dir).map_err(|e| {
        emit_play_status(&app, PlayStatus::Error { message: e.clone() });
        e
    })?;

    emit_play_status(&app, PlayStatus::Launching);
    let child = game_launcher::spawn(&prepared.executable_path, &prepared.working_dir)
        .await
        .map_err(|e| {
            emit_play_status(&app, PlayStatus::Error { message: e.clone() });
            e
        })?;
    emit_play_status(&app, PlayStatus::Started);

    // Espera o processo do Ren'Py fechar numa task separada, pra nao travar
    // outros comandos do Launcher (ex.: abrir configuracoes) enquanto o
    // jogador esta jogando. Resultado so e usado pra diagnostico local no
    // proprio Launcher — nunca reportado ao backend.
    let app_for_wait = app.clone();
    tokio::spawn(async move {
        match game_launcher::wait(child).await {
            Ok(exit) => emit_play_status(
                &app_for_wait,
                PlayStatus::Exited { success: exit.success, code: exit.code },
            ),
            Err(e) => emit_play_status(&app_for_wait, PlayStatus::Error { message: e }),
        }
    });

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            // Falha aqui e fatal de proposito: sem device_uuid persistente o
            // Launcher nao consegue amarrar sessao a device (proteção de
            // hijacking do backend depende disso) — melhor nao abrir do que
            // abrir sem identidade de dispositivo estavel.
            let device_uuid = device::get_or_create_device_uuid(app.handle())
                .expect("nao foi possivel obter/gerar o device_uuid local");
            app.manage(AppState {
                api: ApiClient::new(api_base_url()),
                device_uuid,
                access_token: Mutex::new(None),
                refresh_token: Mutex::new(None),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            check_session,
            login_start,
            logout,
            play_game
        ])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o Limerence Launcher");
}
