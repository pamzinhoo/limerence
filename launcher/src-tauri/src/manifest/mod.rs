//! Estado local de conteudo instalado (base game + DLC). Espelha, por
//! `product_id`, a ultima versao/sha256 que o Launcher confirmou instalada
//! com sucesso — usado por `download::ensure_installed` pra decidir "ja
//! tenho, so validar" vs "preciso baixar" (ver
//! bot/docs/LAUNCHER_API_CONTRACT.md secao 5, fluxo de update/reparo).
//!
//! Isto NAO e uma fonte de verdade de licenca: e so um cache de "o que esta
//! no disco", sempre revalidado contra `GET /launcher/manifest` antes de
//! liberar o jogo. Nenhuma decisao de posse é tomada a partir deste arquivo.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstalledEntry {
    pub version: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub entry_type: String,
    /// Caminho absoluto do artefato instalado (dentro do diretorio de
    /// conteudo do jogo), pra `integrity::matches_expected` revalidar sem
    /// precisar reconstruir a convencao de nome de arquivo.
    pub installed_path: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
pub struct LocalContentState {
    /// Chave = `product_id` (string, pra serializar em JSON sem custom map key type).
    #[serde(default)]
    entries: HashMap<String, InstalledEntry>,
}

impl LocalContentState {
    pub fn load(path: &Path) -> Self {
        match std::fs::read_to_string(path) {
            Ok(raw) => serde_json::from_str(&raw).unwrap_or_default(),
            Err(_) => Self::default(),
        }
    }

    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| format!("Falha ao criar {parent:?}: {e}"))?;
        }
        let contents = serde_json::to_string_pretty(self).map_err(|e| format!("Falha ao serializar estado local: {e}"))?;
        std::fs::write(path, contents).map_err(|e| format!("Falha ao gravar {path:?}: {e}"))
    }

    pub fn get(&self, product_id: Uuid) -> Option<&InstalledEntry> {
        self.entries.get(&product_id.to_string())
    }

    pub fn set(&mut self, product_id: Uuid, entry: InstalledEntry) {
        self.entries.insert(product_id.to_string(), entry);
    }

    pub fn remove(&mut self, product_id: Uuid) {
        self.entries.remove(&product_id.to_string());
    }
}

/// `true` se o estado local ja registra a mesma versao publicada pelo
/// manifest (ainda precisa validar o hash em disco separadamente — versao
/// igual nao implica arquivo integro, ver `integrity::matches_expected`).
pub fn is_same_version(local: Option<&InstalledEntry>, remote_version: &str) -> bool {
    local.is_some_and(|entry| entry.version == remote_version)
}

/// Nome de arquivo local para um produto/versao, extraindo a extensao real
/// da URL assinada quando possivel (o formato exato do artefato nao é
/// definido pelo contrato do backend — ver nota em `download::mod`).
pub fn local_file_name(product_id: Uuid, version: &str, download_url: &str) -> String {
    let no_query = download_url.split('?').next().unwrap_or(download_url);
    let last_segment = no_query.rsplit('/').next().unwrap_or(no_query);
    let ext = last_segment
        .rsplit_once('.')
        .map(|(_, ext)| ext)
        .filter(|ext| !ext.is_empty() && ext.len() <= 8 && ext.chars().all(|c| c.is_ascii_alphanumeric()))
        .unwrap_or("pkg");
    format!("{product_id}-{version}.{ext}")
}

pub fn state_file_path(app_config_dir: &Path) -> PathBuf {
    app_config_dir.join("content_state.json")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_through_disk() {
        let dir = tempfile::tempdir().unwrap();
        let path = state_file_path(dir.path());
        let product_id = Uuid::new_v4();

        let mut state = LocalContentState::load(&path);
        assert!(state.get(product_id).is_none());

        state.set(
            product_id,
            InstalledEntry {
                version: "1.0.0".to_string(),
                sha256: "a".repeat(64),
                size_bytes: 123,
                entry_type: "full".to_string(),
                installed_path: "C:/content/base.pkg".to_string(),
            },
        );
        state.save(&path).unwrap();

        let reloaded = LocalContentState::load(&path);
        let entry = reloaded.get(product_id).unwrap();
        assert_eq!(entry.version, "1.0.0");
        assert_eq!(entry.size_bytes, 123);
    }

    #[test]
    fn load_missing_file_returns_default() {
        let dir = tempfile::tempdir().unwrap();
        let state = LocalContentState::load(&dir.path().join("missing.json"));
        assert!(state.get(Uuid::new_v4()).is_none());
    }

    #[test]
    fn load_corrupted_file_returns_default_instead_of_panicking() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("content_state.json");
        std::fs::write(&path, "{ not json").unwrap();
        let state = LocalContentState::load(&path);
        assert!(state.get(Uuid::new_v4()).is_none());
    }

    #[test]
    fn is_same_version_false_when_absent() {
        assert!(!is_same_version(None, "1.0.0"));
    }

    #[test]
    fn is_same_version_true_when_equal() {
        let entry = InstalledEntry {
            version: "1.0.0".to_string(),
            sha256: "a".repeat(64),
            size_bytes: 1,
            entry_type: "full".to_string(),
            installed_path: "x".to_string(),
        };
        assert!(is_same_version(Some(&entry), "1.0.0"));
        assert!(!is_same_version(Some(&entry), "1.0.1"));
    }

    #[test]
    fn local_file_name_extracts_extension_from_url() {
        let product_id = Uuid::new_v4();
        let name = local_file_name(product_id, "1.0.0", "https://bucket.r2.dev/products/x/1.0.0.pkg?X-Amz-Sig=abc");
        assert_eq!(name, format!("{product_id}-1.0.0.pkg"));
    }

    #[test]
    fn local_file_name_falls_back_when_last_segment_has_no_extension() {
        let product_id = Uuid::new_v4();
        let name = local_file_name(product_id, "1.0.0", "https://bucket.r2.dev/products/x/package?sig=abc");
        assert_eq!(name, format!("{product_id}-1.0.0.pkg"));
    }
}
