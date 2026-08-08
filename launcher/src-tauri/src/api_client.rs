use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Cliente HTTP do backend (`bot/api`, rotas `/auth/*` — ver
/// bot/docs/AUTH_API_CONTRACT.md). So conhece o contrato JSON das rotas de
/// auth; nunca fala com o Discord diretamente.
#[derive(Clone)]
pub struct ApiClient {
    http: reqwest::Client,
    base_url: String,
}

#[derive(Debug, Serialize)]
struct DeviceCodeRequest {
    device_uuid: Uuid,
    os_info: Option<String>,
    launcher_version: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DeviceCodeResponse {
    pub device_code: String,
    pub user_code: String,
    pub verification_uri: String,
    pub expires_in: u64,
    pub interval: u64,
}

#[derive(Debug, Serialize)]
struct DeviceTokenRequest<'a> {
    device_code: &'a str,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DeviceTokenResponse {
    pub status: String,
    pub access_token: Option<String>,
    pub refresh_token: Option<String>,
    pub expires_in: Option<u64>,
    pub interval: Option<u64>,
}

#[derive(Debug, Serialize)]
struct RefreshRequest {
    refresh_token: String,
    device_uuid: Uuid,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub refresh_token: String,
    pub expires_in: u64,
}

#[derive(Debug, Serialize)]
struct LogoutRequest {
    refresh_token: String,
}

/// Espelha `ManifestResponse` de `bot/api/schemas/launcher.py` — retornado
/// por `GET /launcher/manifest` (ver bot/docs/LAUNCHER_API_CONTRACT.md secao
/// 5). O backend so devolve isso se o player tiver `License` ACTIVE no
/// `product_id` pedido (403 `license_required` caso contrario) — por isso
/// este e o metodo usado pela "Verificar licenca" do Launcher.
#[derive(Debug, Clone, Deserialize)]
pub struct ManifestResponse {
    pub product_id: Uuid,
    pub entry_type: String,
    pub version: String,
    pub sha256: String,
    pub size_bytes: u64,
    #[serde(default)]
    pub depends_on: Vec<String>,
    pub release_notes: Option<String>,
}

/// Espelha `LicenseResponse` de `bot/api/schemas/launcher.py` — retornado
/// por `GET /player/licenses`. Usado pelo Launcher pra descobrir quais
/// produtos (base game + DLCs) o player possui antes de tentar baixar cada
/// um.
#[derive(Debug, Clone, Deserialize)]
pub struct LicenseResponse {
    pub id: Uuid,
    pub product_id: Uuid,
    pub product_slug: Option<String>,
    pub product_name: Option<String>,
    pub status: String,
    pub purchase_source: String,
    pub activated_at: Option<String>,
    pub expires_at: Option<String>,
    pub auto_renew: bool,
    pub revoked_at: Option<String>,
    pub revoked_reason: Option<String>,
}

#[derive(Debug, Serialize)]
struct DownloadRequest {
    product_id: Uuid,
    entry_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    device_uuid: Option<Uuid>,
}

/// Espelha `DownloadResponse` — retornado por `POST /download`. `url` e uma
/// URL assinada de curta duracao (`expires_at`) apontando direto pro storage
/// (R2/S3/B2) — o Launcher baixa os bytes de la, nunca do processo do bot.
#[derive(Debug, Clone, Deserialize)]
pub struct DownloadResponse {
    pub download_id: Uuid,
    pub url: String,
    pub version: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub entry_type: String,
    pub expires_at: String,
}

#[derive(Debug, Serialize)]
struct DownloadCompleteRequest {
    client_sha256: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    bytes_transferred: Option<u64>,
}

/// Espelha `DownloadCompleteResponse` — retornado por
/// `POST /download/{id}/complete`. `status` e `"completed"` ou `"failed"`
/// (com `failure_reason: "checksum_mismatch"`); o backend so confirma o que
/// o Launcher ja verificou localmente antes de instalar.
#[derive(Debug, Clone, Deserialize)]
pub struct DownloadCompleteResponse {
    pub download_id: Uuid,
    pub status: String,
    pub failure_reason: Option<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("erro de rede: {0}")]
    Network(#[from] reqwest::Error),
    #[error("backend recusou ({status}): {code}")]
    Rejected { status: u16, code: String },
}

impl ApiClient {
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            http: reqwest::Client::new(),
            base_url: base_url.into(),
        }
    }

    /// Cliente HTTP reqwest cru, reaproveitado (pool de conexoes) pelo
    /// modulo `download` pra baixar bytes diretamente da URL assinada
    /// (storage — R2/S3/B2), que e um host totalmente diferente de
    /// `base_url` (o processo do bot nunca serve os bytes, ver
    /// bot/docs/LAUNCHER_API_CONTRACT.md secao 1).
    pub fn http_client(&self) -> &reqwest::Client {
        &self.http
    }

    async fn parse_or_error<T: for<'de> Deserialize<'de>>(
        resp: reqwest::Response,
    ) -> Result<T, ApiError> {
        let status = resp.status();
        if status.is_success() {
            Ok(resp.json::<T>().await?)
        } else {
            #[derive(Deserialize)]
            struct ErrorDetail {
                error: Option<String>,
            }
            #[derive(Deserialize)]
            struct ErrorBody {
                detail: Option<ErrorDetail>,
            }
            let code = resp
                .json::<ErrorBody>()
                .await
                .ok()
                .and_then(|b| b.detail)
                .and_then(|d| d.error)
                .unwrap_or_else(|| "unknown_error".to_string());
            Err(ApiError::Rejected {
                status: status.as_u16(),
                code,
            })
        }
    }

    pub async fn device_code(
        &self,
        device_uuid: Uuid,
        os_info: Option<String>,
        launcher_version: Option<String>,
    ) -> Result<DeviceCodeResponse, ApiError> {
        let resp = self
            .http
            .post(format!("{}/auth/device/code", self.base_url))
            .json(&DeviceCodeRequest {
                device_uuid,
                os_info,
                launcher_version,
            })
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    pub async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenResponse, ApiError> {
        let resp = self
            .http
            .post(format!("{}/auth/device/token", self.base_url))
            .json(&DeviceTokenRequest { device_code })
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    pub async fn refresh(&self, refresh_token: &str, device_uuid: Uuid) -> Result<TokenResponse, ApiError> {
        let resp = self
            .http
            .post(format!("{}/auth/refresh", self.base_url))
            .json(&RefreshRequest {
                refresh_token: refresh_token.to_string(),
                device_uuid,
            })
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    pub async fn logout(&self, refresh_token: &str) -> Result<(), ApiError> {
        let resp = self
            .http
            .post(format!("{}/auth/logout", self.base_url))
            .json(&LogoutRequest {
                refresh_token: refresh_token.to_string(),
            })
            .send()
            .await?;
        if resp.status().is_success() {
            Ok(())
        } else {
            Err(ApiError::Rejected {
                status: resp.status().as_u16(),
                code: "logout_failed".to_string(),
            })
        }
    }

    /// `GET /launcher/manifest?product_id=&entry_type=` — "Verificar
    /// licenca": o backend so responde 200 se houver `License` ACTIVE do
    /// player pro `product_id` pedido (403 `license_required` caso
    /// contrario, mapeado para `ApiError::Rejected` como qualquer outro
    /// erro). Nao existe checagem local de licenca — este e o unico lugar
    /// que decide "o player pode isso".
    pub async fn get_manifest(
        &self,
        access_token: &str,
        product_id: Uuid,
        entry_type: &str,
    ) -> Result<ManifestResponse, ApiError> {
        let resp = self
            .http
            .get(format!("{}/launcher/manifest", self.base_url))
            .bearer_auth(access_token)
            .query(&[("product_id", product_id.to_string()), ("entry_type", entry_type.to_string())])
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    /// `GET /player/licenses` — inventario completo (inclui
    /// REVOKED/EXPIRED). O Launcher filtra `status == "active"` pra decidir
    /// quais produtos (base game + DLC) tentar sincronizar.
    pub async fn list_licenses(&self, access_token: &str) -> Result<Vec<LicenseResponse>, ApiError> {
        let resp = self
            .http
            .get(format!("{}/player/licenses", self.base_url))
            .bearer_auth(access_token)
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    /// `POST /download` — "Baixar DLC". Reconfirma `License` ACTIVE no
    /// backend (nunca reaproveita a checagem de `get_manifest`) e devolve
    /// uma URL assinada de curta duracao pro storage — o Launcher baixa
    /// direto de la, o processo do bot nunca serve os bytes.
    pub async fn authorize_download(
        &self,
        access_token: &str,
        product_id: Uuid,
        entry_type: &str,
        device_uuid: Option<Uuid>,
    ) -> Result<DownloadResponse, ApiError> {
        let resp = self
            .http
            .post(format!("{}/download", self.base_url))
            .bearer_auth(access_token)
            .json(&DownloadRequest {
                product_id,
                entry_type: entry_type.to_string(),
                device_uuid,
            })
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }

    /// `POST /download/{id}/complete` — fecha o ciclo de "Validar
    /// arquivos": o Launcher ja calculou o SHA-256 do arquivo baixado
    /// localmente e reporta aqui pro backend confirmar contra o manifest
    /// que autorizou aquele download. Idempotente do lado do backend.
    pub async fn complete_download(
        &self,
        access_token: &str,
        download_id: Uuid,
        client_sha256: &str,
        bytes_transferred: Option<u64>,
    ) -> Result<DownloadCompleteResponse, ApiError> {
        let resp = self
            .http
            .post(format!("{}/download/{download_id}/complete", self.base_url))
            .bearer_auth(access_token)
            .json(&DownloadCompleteRequest {
                client_sha256: client_sha256.to_string(),
                bytes_transferred,
            })
            .send()
            .await?;
        Self::parse_or_error(resp).await
    }
}
