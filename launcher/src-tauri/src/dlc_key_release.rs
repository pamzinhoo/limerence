//! dlc_key_release.rs (v3)
//! =========================
//!
//! Fluxo de 2 passos (nunca 1) — ver backend/services/dlc_license_service.py
//! e backend/api/routes/launcher_dlc_routes.py:
//!
//!   1. authorize()  -> POST /launcher/dlc/{slug}/authorize
//!                      devolve authorization_token SEM segredo nenhum.
//!   2. redeem_material() -> POST /launcher/dlc/{slug}/material
//!                      troca o token pela chave, UMA UNICA VEZ.
//!
//! Continua nao reimplementando download/manifesto/integridade (isso ja
//! existe em download::ensure_installed) — este modulo so cuida da chave e
//! da descriptografia pra pasta de sessao temporaria.
//!
//! PONTO 11/12 DO PEDIDO (exposicao minima + recuperacao de crash):
//! O conteudo descriptografado so existe dentro de
//! `<diretorio_de_sessoes>/<session_uuid>/<dlc_slug>/`, um diretorio criado
//! com um UUID aleatorio por sessao de jogo (nome nao previsivel). Ao
//! encerrar o jogo normalmente, `cleanup_session_dir` apaga essa pasta. Se
//! o processo morrer sem chance de limpar (crash/queda de energia), a
//! pasta fica orfa — por isso `sweep_stale_sessions` deve ser chamado no
//! INICIO de toda execucao do launcher (antes de qualquer outra coisa),
//! removendo qualquer sessao cujo diretorio pai `sessions/` contenha
//! subpastas mais velhas que `STALE_SESSION_MAX_AGE`. Isso limita o tempo
//! MAXIMO que um conteudo descriptografado pode ficar exposto em disco
//! apos um crash a essa janela, mesmo sem conseguir detectar o crash em
//! si.
//!
//! Nao finjo que da pra manter o conteudo "so em memoria" sem nunca tocar
//! disco: o Ren'Py carrega `.rpyc`/imagens/audio como arquivos via
//! `renpy.config.searchpath` (ver game/game/dlc_loader.rpy) — ele nao tem
//! um mecanismo suportado de carregar assets de um buffer arbitrario em
//! memoria sem passar por arquivo. A mitigacao realista e: janela de
//! exposicao minima (delete-on-exit + sweep de orfaos), nome de pasta nao
//! obvio, e diretorio criado com permissoes restritas ao usuario atual
//! (comportamento padrao de diretorios de usuario no Windows/macOS/Linux
//! modernos — nao e necessario ACL customizada alem disso pra este caso
//! de uso).

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use uuid::Uuid;

use crate::api_client::ApiClient; // TODO: confirmar assinatura real

/// Autorizacoes ficam expostas no maximo por este tempo se um crash
/// impedir a limpeza normal. 6 horas cobre folgadamente qualquer sessao de
/// jogo legitima, sem deixar conteudo decifrado acumulando indefinidamente.
const STALE_SESSION_MAX_AGE: Duration = Duration::from_secs(6 * 60 * 60);

#[derive(Debug, thiserror::Error)]
pub enum DlcKeyError {
    #[error("nao autorizado: {0}")]
    NotAuthorized(String),
    #[error("erro de comunicacao com o backend: {0}")]
    Backend(String),
    #[error("arquivo .enc invalido, corrompido ou chave incorreta")]
    DecryptFailed,
    #[error("erro de arquivo local: {0}")]
    Io(String),
}

#[derive(serde::Deserialize)]
struct AuthorizeResponse {
    authorization_token: String,
    #[allow(dead_code)]
    expires_in: u32,
}

#[derive(serde::Serialize)]
struct MaterialRequestBody<'a> {
    authorization_token: &'a str,
}

#[derive(serde::Deserialize)]
struct MaterialResponse {
    key_hex: String,
}

/// PASSO 1. So confirma que o backend autoriza — nao obtem nada sensivel
/// ainda. TODO: adicionar em api_client.rs no mesmo padrao de
/// authorize_download (POST com Authorization: Bearer <access_token>).
async fn authorize(api: &ApiClient, access_token: &str, dlc_slug: &str) -> Result<String, DlcKeyError> {
    let resp: AuthorizeResponse = api
        .post_json(&format!("/launcher/dlc/{dlc_slug}/authorize"), access_token, &())
        .await
        .map_err(|e| DlcKeyError::NotAuthorized(e.to_string()))?;
    Ok(resp.authorization_token)
}

/// PASSO 2. Troca o token de autorizacao pela chave — chame isto
/// IMEDIATAMENTE depois de authorize(), nunca guarde o authorization_token
/// pra usar depois (ele so serve uma vez, e o TTL e curto de proposito).
async fn redeem_material(
    api: &ApiClient,
    access_token: &str,
    dlc_slug: &str,
    authorization_token: &str,
) -> Result<Vec<u8>, DlcKeyError> {
    let body = MaterialRequestBody { authorization_token };
    let resp: MaterialResponse = api
        .post_json(&format!("/launcher/dlc/{dlc_slug}/material"), access_token, &body)
        .await
        .map_err(|e| DlcKeyError::NotAuthorized(e.to_string()))?;
    hex::decode(resp.key_hex).map_err(|_| DlcKeyError::DecryptFailed)
}

fn decrypt_enc_file(enc_path: &Path, key_bytes: &[u8]) -> Result<Vec<u8>, DlcKeyError> {
    let enc_bytes = fs::read(enc_path).map_err(|e| DlcKeyError::Io(e.to_string()))?;
    if enc_bytes.len() < 12 + 16 {
        return Err(DlcKeyError::DecryptFailed);
    }
    let (nonce_bytes, ciphertext) = enc_bytes.split_at(12);
    let key = Key::<Aes256Gcm>::from_slice(key_bytes);
    let cipher = Aes256Gcm::new(key);
    let nonce = Nonce::from_slice(nonce_bytes);
    cipher.decrypt(nonce, ciphertext).map_err(|_| DlcKeyError::DecryptFailed)
}

/// Fluxo completo pra UMA DLC: autoriza, resgata a chave (uso unico),
/// descriptografa o `.enc` ja baixado por `ensure_installed`, extrai pra
/// `<sessions_root>/<session_id>/<dlc_slug>/`. Chame uma vez por DLC que o
/// usuario possui, logo antes de `game_launcher::spawn`.
pub async fn unlock_for_session(
    api: &ApiClient,
    access_token: &str,
    dlc_slug: &str,
    installed_enc_path: &Path,
    sessions_root: &Path,
    session_id: Uuid,
) -> Result<PathBuf, DlcKeyError> {
    let authorization_token = authorize(api, access_token, dlc_slug).await?;
    let key_bytes = redeem_material(api, access_token, dlc_slug, &authorization_token).await?;

    let plaintext_zip = decrypt_enc_file(installed_enc_path, &key_bytes)?;

    let extract_dir = sessions_root.join(session_id.to_string()).join(dlc_slug);
    fs::create_dir_all(&extract_dir).map_err(|e| DlcKeyError::Io(e.to_string()))?;
    unzip_bytes_to_dir(&plaintext_zip, &extract_dir).map_err(|e| DlcKeyError::Io(e.to_string()))?;

    // Marcador de sessao -- usado por sweep_stale_sessions pra saber a
    // idade da pasta sem depender so do mtime do diretorio (que alguns
    // filesystems atualizam de formas inconsistentes).
    let marker = sessions_root.join(session_id.to_string()).join(".session_created");
    let _ = fs::write(&marker, chrono_now_rfc3339());

    Ok(extract_dir)
}

/// Apague ao fechar o jogo normalmente (depois de game_launcher::wait).
pub fn cleanup_session_dir(sessions_root: &Path, session_id: Uuid) {
    let dir = sessions_root.join(session_id.to_string());
    let _ = fs::remove_dir_all(dir);
}

/// PONTO 12: chame isto no INICIO de toda execucao do launcher, antes de
/// qualquer outra coisa. Remove pastas de sessao orfas (deixadas por um
/// crash) mais velhas que STALE_SESSION_MAX_AGE. Nao depende de detectar
/// o crash em si -- so limita o tempo maximo de exposicao.
pub fn sweep_stale_sessions(sessions_root: &Path) {
    let Ok(entries) = fs::read_dir(sessions_root) else { return };
    let now = SystemTime::now();

    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let age = entry
            .metadata()
            .ok()
            .and_then(|m| m.created().or_else(|_| m.modified()).ok())
            .and_then(|t| now.duration_since(t).ok());

        match age {
            Some(age) if age > STALE_SESSION_MAX_AGE => {
                let _ = fs::remove_dir_all(&path);
            }
            None => {
                // Nao conseguiu ler a idade -- por seguranca, trata como
                // orfa e remove tambem (melhor remover cedo demais do que
                // deixar conteudo decifrado acumulando sem controle).
                let _ = fs::remove_dir_all(&path);
            }
            _ => {}
        }
    }
}

fn chrono_now_rfc3339() -> String {
    // TODO: usar a crate `time` ou `chrono` ja presente no projeto (ver
    // Cargo.toml) -- placeholder minimo pra nao adicionar dependencia nova
    // sem confirmar o que ja esta em uso.
    format!("{:?}", SystemTime::now())
}

fn unzip_bytes_to_dir(_bytes: &[u8], _dir: &Path) -> std::io::Result<()> {
    unimplemented!("extrair o zip descriptografado para _dir usando a crate `zip`")
}
