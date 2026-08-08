//! Orquestra "Verificar licenca" + "Baixar DLC" + "Validar arquivos" pra um
//! unico produto (base game ou DLC) — ver
//! bot/docs/LAUNCHER_API_CONTRACT.md secoes 5, 8 e 9 e
//! bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 7 (fluxo de
//! update/reparo).
//!
//! `ensure_installed` e chamado tanto no primeiro download quanto em toda
//! inicializacao do Launcher (antes de liberar "Jogar"): ele sempre
//! reconsulta o backend (nunca confia em cache local de licenca) e sempre
//! revalida o hash do arquivo em disco, baixando de novo só quando
//! necessario. Ren'Py nunca participa deste fluxo — só recebe o resultado
//! já pronto no diretorio de conteudo.

use futures_util::StreamExt;
use std::path::{Path, PathBuf};
use tokio::io::AsyncWriteExt;
use uuid::Uuid;

use crate::api_client::{ApiClient, ApiError};
use crate::integrity;
use crate::manifest::{self, InstalledEntry, LocalContentState};

const MAX_ATTEMPTS: u32 = 3;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stage {
    CheckingLicense,
    Downloading { attempt: u32 },
    Validating,
    Repairing { attempt: u32 },
}

#[derive(Debug, thiserror::Error)]
pub enum DownloadFlowError {
    #[error("licenca invalida ou ausente para este produto: {0}")]
    LicenseDenied(String),
    #[error("erro de comunicacao com o backend: {0}")]
    Backend(String),
    #[error("erro de rede ao baixar o arquivo: {0}")]
    Network(String),
    #[error("erro de arquivo local: {0}")]
    Io(String),
    #[error("checksum nao bateu apos {0} tentativa(s) — arquivo possivelmente corrompido no storage")]
    ChecksumExhausted(u32),
}

impl From<ApiError> for DownloadFlowError {
    fn from(err: ApiError) -> Self {
        match &err {
            ApiError::Rejected { code, .. } if code == "license_required" => {
                DownloadFlowError::LicenseDenied(err.to_string())
            }
            _ => DownloadFlowError::Backend(err.to_string()),
        }
    }
}

/// Passo 1 ("Verificar licenca"), isolado pra poder ser chamado sozinho
/// antes de decidir se vale a pena baixar qualquer coisa (ex.: manifest de
/// dependencia, checagem de "posso jogar" sem baixar nada nesta chamada).
pub async fn verify_license(
    api: &ApiClient,
    access_token: &str,
    product_id: Uuid,
    entry_type: &str,
) -> Result<crate::api_client::ManifestResponse, DownloadFlowError> {
    Ok(api.get_manifest(access_token, product_id, entry_type).await?)
}

/// Garante que `product_id` (base game ou DLC) esta instalado, integro e na
/// versao mais recente em `content_dir`. Chama `on_stage` a cada mudanca de
/// etapa, pra o caller (comando Tauri) repassar progresso ao frontend sem
/// este modulo depender de Tauri.
pub async fn ensure_installed(
    api: &ApiClient,
    access_token: &str,
    product_id: Uuid,
    entry_type: &str,
    device_uuid: Option<Uuid>,
    content_dir: &Path,
    state_path: &Path,
    mut on_stage: impl FnMut(Stage),
) -> Result<InstalledEntry, DownloadFlowError> {
    on_stage(Stage::CheckingLicense);
    let remote = verify_license(api, access_token, product_id, entry_type).await?;

    tokio::fs::create_dir_all(content_dir)
        .await
        .map_err(|e| DownloadFlowError::Io(format!("nao foi possivel criar {content_dir:?}: {e}")))?;

    let mut state = LocalContentState::load(state_path);

    // Ja instalado na mesma versao e com hash integro? Nada a fazer alem de
    // confirmar (evita re-baixar GBs de conteudo toda vez que o Launcher
    // abre).
    if manifest::is_same_version(state.get(product_id), &remote.version) {
        on_stage(Stage::Validating);
        let local = state.get(product_id).cloned().expect("checado acima");
        let local_path = PathBuf::from(&local.installed_path);
        if integrity::matches_expected(&local_path, &remote.sha256).await.map_err(DownloadFlowError::Io)? {
            return Ok(local);
        }
        // Mesma versao, hash divergente: arquivo corrompido — cai pro loop
        // de (re)download abaixo (repair), sem precisar re-baixar
        // dependencias que ja estavam ok.
    }

    let mut last_err: Option<DownloadFlowError> = None;
    for attempt in 1..=MAX_ATTEMPTS {
        let is_repair = state.get(product_id).is_some();
        on_stage(if is_repair {
            Stage::Repairing { attempt }
        } else {
            Stage::Downloading { attempt }
        });

        let authorization = api
            .authorize_download(access_token, product_id, entry_type, device_uuid)
            .await?;

        let dest = content_dir.join(manifest::local_file_name(product_id, &authorization.version, &authorization.url));

        if let Err(e) = stream_download(api.http_client(), &authorization.url, &dest).await {
            last_err = Some(DownloadFlowError::Network(e));
            continue;
        }

        on_stage(Stage::Validating);
        let actual_sha256 = match integrity::sha256_file_async(dest.clone()).await {
            Ok(hash) => hash,
            Err(e) => {
                last_err = Some(DownloadFlowError::Io(e));
                continue;
            }
        };

        let bytes_transferred = tokio::fs::metadata(&dest).await.ok().map(|m| m.len());
        let matches = actual_sha256.eq_ignore_ascii_case(&authorization.sha256);

        // Reporta o veredito ao backend independente do resultado — fecha a
        // trilha de auditoria (`Download.status`) mesmo quando falha.
        let _ = api
            .complete_download(access_token, authorization.download_id, &actual_sha256, bytes_transferred)
            .await;

        if !matches {
            let _ = tokio::fs::remove_file(&dest).await;
            last_err = Some(DownloadFlowError::ChecksumExhausted(attempt));
            continue;
        }

        let entry = InstalledEntry {
            version: authorization.version.clone(),
            sha256: authorization.sha256.clone(),
            size_bytes: authorization.size_bytes,
            entry_type: authorization.entry_type.clone(),
            installed_path: dest.to_string_lossy().into_owned(),
        };
        state.set(product_id, entry.clone());
        state.save(state_path).map_err(DownloadFlowError::Io)?;
        return Ok(entry);
    }

    Err(last_err.unwrap_or(DownloadFlowError::ChecksumExhausted(MAX_ATTEMPTS)))
}

/// Baixa `url` (ja assinada) para `dest`, em streaming — nunca carrega o
/// arquivo inteiro na RAM. Escreve num arquivo `.part` e so renomeia pro
/// destino final ao terminar, pra um download interrompido nunca deixar um
/// arquivo "final" parcial/corrompido no lugar que passaria despercebido
/// numa checagem de "arquivo existe".
async fn stream_download(client: &reqwest::Client, url: &str, dest: &Path) -> Result<(), String> {
    let tmp_path = dest.with_extension(format!(
        "{}.part",
        dest.extension().and_then(|e| e.to_str()).unwrap_or("download")
    ));

    let response = client
        .get(url)
        .send()
        .await
        .map_err(|e| format!("falha ao iniciar download: {e}"))?;
    let response = response
        .error_for_status()
        .map_err(|e| format!("storage recusou o download: {e}"))?;

    let mut file = tokio::fs::File::create(&tmp_path)
        .await
        .map_err(|e| format!("falha ao criar {tmp_path:?}: {e}"))?;

    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| format!("falha ao ler dados do download: {e}"))?;
        file.write_all(&chunk).await.map_err(|e| format!("falha ao gravar {tmp_path:?}: {e}"))?;
    }
    file.flush().await.map_err(|e| format!("falha ao finalizar {tmp_path:?}: {e}"))?;
    drop(file);

    tokio::fs::rename(&tmp_path, dest)
        .await
        .map_err(|e| format!("falha ao mover {tmp_path:?} para {dest:?}: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api_client::ApiClient;
    use serde_json::json;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn sha256_hex(data: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(data);
        hasher.finalize().iter().map(|b| format!("{b:02x}")).collect()
    }

    #[tokio::test]
    async fn ensure_installed_downloads_verifies_and_persists_state() {
        let backend = MockServer::start().await;
        let storage = MockServer::start().await;
        let content = b"conteudo de teste do pacote".to_vec();
        let sha = sha256_hex(&content);
        let product_id = Uuid::new_v4();
        let download_id = Uuid::new_v4();

        Mock::given(method("GET"))
            .and(path("/launcher/manifest"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "product_id": product_id,
                "entry_type": "full",
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": content.len(),
                "depends_on": [],
                "release_notes": null
            })))
            .mount(&backend)
            .await;

        Mock::given(method("POST"))
            .and(path("/download"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "url": format!("{}/pkg/1.0.0.pkg", storage.uri()),
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": content.len(),
                "entry_type": "full",
                "expires_at": "2026-08-06T15:40:00+00:00"
            })))
            .mount(&backend)
            .await;

        Mock::given(method("POST"))
            .and(path(format!("/download/{download_id}/complete")))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "status": "completed",
                "failure_reason": null
            })))
            .mount(&backend)
            .await;

        Mock::given(method("GET"))
            .and(path("/pkg/1.0.0.pkg"))
            .respond_with(ResponseTemplate::new(200).set_body_bytes(content.clone()))
            .mount(&storage)
            .await;

        let api = ApiClient::new(backend.uri());
        let dir = tempfile::tempdir().unwrap();
        let content_dir = dir.path().join("content");
        let state_path = dir.path().join("state.json");

        let mut stages = Vec::new();
        let entry = ensure_installed(
            &api,
            "fake-token",
            product_id,
            "full",
            None,
            &content_dir,
            &state_path,
            |s| stages.push(s),
        )
        .await
        .unwrap();

        assert_eq!(entry.version, "1.0.0");
        assert_eq!(entry.sha256, sha);
        assert!(PathBuf::from(&entry.installed_path).exists());
        assert_eq!(std::fs::read(&entry.installed_path).unwrap(), content);
        assert!(matches!(stages[0], Stage::CheckingLicense));

        // Estado persistido em disco pra proxima execucao do Launcher.
        let reloaded = LocalContentState::load(&state_path);
        assert_eq!(reloaded.get(product_id).unwrap().version, "1.0.0");
    }

    #[tokio::test]
    async fn ensure_installed_skips_download_when_already_current_and_intact() {
        let backend = MockServer::start().await;
        let content = b"ja instalado".to_vec();
        let sha = sha256_hex(&content);
        let product_id = Uuid::new_v4();

        Mock::given(method("GET"))
            .and(path("/launcher/manifest"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "product_id": product_id,
                "entry_type": "full",
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": content.len(),
                "depends_on": [],
                "release_notes": null
            })))
            .mount(&backend)
            .await;
        // Nenhum mock de /download montado — se o codigo tentar baixar de
        // novo, o teste falha porque o wiremock rejeita a chamada nao
        // configurada.

        let api = ApiClient::new(backend.uri());
        let dir = tempfile::tempdir().unwrap();
        let content_dir = dir.path().join("content");
        std::fs::create_dir_all(&content_dir).unwrap();
        let existing_path = content_dir.join("existing.pkg");
        std::fs::write(&existing_path, &content).unwrap();

        let state_path = dir.path().join("state.json");
        let mut state = LocalContentState::load(&state_path);
        state.set(
            product_id,
            InstalledEntry {
                version: "1.0.0".to_string(),
                sha256: sha.clone(),
                size_bytes: content.len() as u64,
                entry_type: "full".to_string(),
                installed_path: existing_path.to_string_lossy().into_owned(),
            },
        );
        state.save(&state_path).unwrap();

        let entry = ensure_installed(&api, "fake-token", product_id, "full", None, &content_dir, &state_path, |_| {})
            .await
            .unwrap();
        assert_eq!(entry.installed_path, existing_path.to_string_lossy());
    }

    #[tokio::test]
    async fn ensure_installed_repairs_when_local_file_is_corrupted() {
        let backend = MockServer::start().await;
        let storage = MockServer::start().await;
        let good_content = b"conteudo correto".to_vec();
        let sha = sha256_hex(&good_content);
        let product_id = Uuid::new_v4();
        let download_id = Uuid::new_v4();

        Mock::given(method("GET"))
            .and(path("/launcher/manifest"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "product_id": product_id,
                "entry_type": "full",
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": good_content.len(),
                "depends_on": [],
                "release_notes": null
            })))
            .mount(&backend)
            .await;
        Mock::given(method("POST"))
            .and(path("/download"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "url": format!("{}/pkg/1.0.0.pkg", storage.uri()),
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": good_content.len(),
                "entry_type": "full",
                "expires_at": "2026-08-06T15:40:00+00:00"
            })))
            .mount(&backend)
            .await;
        Mock::given(method("POST"))
            .and(path(format!("/download/{download_id}/complete")))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "status": "completed",
                "failure_reason": null
            })))
            .mount(&backend)
            .await;
        Mock::given(method("GET"))
            .and(path("/pkg/1.0.0.pkg"))
            .respond_with(ResponseTemplate::new(200).set_body_bytes(good_content.clone()))
            .mount(&storage)
            .await;

        let api = ApiClient::new(backend.uri());
        let dir = tempfile::tempdir().unwrap();
        let content_dir = dir.path().join("content");
        std::fs::create_dir_all(&content_dir).unwrap();
        let corrupted_path = content_dir.join("corrupted.pkg");
        std::fs::write(&corrupted_path, b"lixo corrompido").unwrap();

        let state_path = dir.path().join("state.json");
        let mut state = LocalContentState::load(&state_path);
        state.set(
            product_id,
            InstalledEntry {
                version: "1.0.0".to_string(),
                sha256: sha.clone(),
                size_bytes: good_content.len() as u64,
                entry_type: "full".to_string(),
                installed_path: corrupted_path.to_string_lossy().into_owned(),
            },
        );
        state.save(&state_path).unwrap();

        let mut stages = Vec::new();
        let entry = ensure_installed(
            &api,
            "fake-token",
            product_id,
            "full",
            None,
            &content_dir,
            &state_path,
            |s| stages.push(s),
        )
        .await
        .unwrap();

        assert_eq!(entry.sha256, sha);
        assert!(stages.iter().any(|s| matches!(s, Stage::Repairing { .. })));
        assert_eq!(std::fs::read(&entry.installed_path).unwrap(), good_content);
    }

    #[tokio::test]
    async fn ensure_installed_maps_license_required_to_license_denied() {
        let backend = MockServer::start().await;
        let product_id = Uuid::new_v4();

        Mock::given(method("GET"))
            .and(path("/launcher/manifest"))
            .respond_with(ResponseTemplate::new(403).set_body_json(json!({
                "detail": {"error": "license_required", "message": "Nenhuma licenca ativa."}
            })))
            .mount(&backend)
            .await;

        let api = ApiClient::new(backend.uri());
        let dir = tempfile::tempdir().unwrap();
        let err = ensure_installed(
            &api,
            "fake-token",
            product_id,
            "full",
            None,
            &dir.path().join("content"),
            &dir.path().join("state.json"),
            |_| {},
        )
        .await
        .unwrap_err();

        assert!(matches!(err, DownloadFlowError::LicenseDenied(_)));
    }

    #[tokio::test]
    async fn ensure_installed_fails_after_persistent_checksum_mismatch() {
        let backend = MockServer::start().await;
        let storage = MockServer::start().await;
        let good_content = b"conteudo correto".to_vec();
        let sha = sha256_hex(&good_content);
        let wrong_content = b"bytes errados vindo do storage".to_vec();
        let product_id = Uuid::new_v4();
        let download_id = Uuid::new_v4();

        Mock::given(method("GET"))
            .and(path("/launcher/manifest"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "product_id": product_id,
                "entry_type": "full",
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": good_content.len(),
                "depends_on": [],
                "release_notes": null
            })))
            .mount(&backend)
            .await;
        Mock::given(method("POST"))
            .and(path("/download"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "url": format!("{}/pkg/1.0.0.pkg", storage.uri()),
                "version": "1.0.0",
                "sha256": sha,
                "size_bytes": good_content.len(),
                "entry_type": "full",
                "expires_at": "2026-08-06T15:40:00+00:00"
            })))
            .mount(&backend)
            .await;
        Mock::given(method("POST"))
            .and(path(format!("/download/{download_id}/complete")))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "download_id": download_id,
                "status": "failed",
                "failure_reason": "checksum_mismatch"
            })))
            .mount(&backend)
            .await;
        Mock::given(method("GET"))
            .and(path("/pkg/1.0.0.pkg"))
            .respond_with(ResponseTemplate::new(200).set_body_bytes(wrong_content))
            .mount(&storage)
            .await;

        let api = ApiClient::new(backend.uri());
        let dir = tempfile::tempdir().unwrap();
        let mut stages = Vec::new();
        let err = ensure_installed(
            &api,
            "fake-token",
            product_id,
            "full",
            None,
            &dir.path().join("content"),
            &dir.path().join("state.json"),
            |s| stages.push(s),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, DownloadFlowError::ChecksumExhausted(MAX_ATTEMPTS)));
        let downloading_attempts = stages.iter().filter(|s| matches!(s, Stage::Downloading { .. })).count();
        assert_eq!(downloading_attempts, MAX_ATTEMPTS as usize);
    }
}
