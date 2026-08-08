use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::{AppHandle, Manager};
use uuid::Uuid;

#[derive(Debug, Serialize, Deserialize)]
struct DeviceFile {
    device_uuid: Uuid,
}

fn device_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("Nao foi possivel resolver o diretorio de config: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("Nao foi possivel criar {dir:?}: {e}"))?;
    Ok(dir.join("device.json"))
}

/// Le o `device_uuid` persistido localmente ou gera um novo na primeira
/// execucao. Nao deriva de fingerprint de hardware — trocar peca/formatar o
/// Windows nao invalida o dispositivo (ver
/// bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 2.2).
pub fn get_or_create_device_uuid(app: &AppHandle) -> Result<Uuid, String> {
    let path = device_file_path(app)?;

    if path.exists() {
        let raw = fs::read_to_string(&path).map_err(|e| format!("Falha ao ler {path:?}: {e}"))?;
        if let Ok(parsed) = serde_json::from_str::<DeviceFile>(&raw) {
            return Ok(parsed.device_uuid);
        }
        // arquivo corrompido/formato antigo — regenera em vez de travar o launcher
    }

    let device_uuid = Uuid::new_v4();
    let contents = serde_json::to_string_pretty(&DeviceFile { device_uuid })
        .map_err(|e| format!("Falha ao serializar device_uuid: {e}"))?;
    fs::write(&path, contents).map_err(|e| format!("Falha ao gravar {path:?}: {e}"))?;
    Ok(device_uuid)
}
