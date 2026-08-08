//! "Validar arquivos": calculo de SHA-256 de arquivos locais pra comparar
//! contra o manifest do backend (`ManifestResponse.sha256` /
//! `DownloadResponse.sha256`). Roda tanto logo apos um download quanto a
//! cada início do Launcher, antes de liberar o Ren'Py — ver
//! `download::ensure_installed` e `bot/docs/LAUNCHER_API_CONTRACT.md` secao 9.

use sha2::{Digest, Sha256};
use std::io::Read;
use std::path::{Path, PathBuf};

const CHUNK_SIZE: usize = 1024 * 1024;

/// Calcula o SHA-256 de um arquivo em streaming (nunca carrega o arquivo
/// inteiro na RAM — pacotes de DLC podem ter varios GB, ver exemplo de
/// `size_bytes` no contrato). Bloqueante de proposito; sempre chamar via
/// `sha256_file_async` a partir de codigo async pra nao travar o runtime do
/// Tauri.
pub fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file =
        std::fs::File::open(path).map_err(|e| format!("Falha ao abrir {path:?} para checagem de integridade: {e}"))?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; CHUNK_SIZE];
    loop {
        let read = file
            .read(&mut buf)
            .map_err(|e| format!("Falha ao ler {path:?} durante checagem de integridade: {e}"))?;
        if read == 0 {
            break;
        }
        hasher.update(&buf[..read]);
    }
    Ok(hex_encode(&hasher.finalize()))
}

/// Versao async (via `spawn_blocking`) de [`sha256_file`], pra uso direto em
/// comandos Tauri / fluxo de orquestracao sem bloquear o executor async.
pub async fn sha256_file_async(path: PathBuf) -> Result<String, String> {
    tokio::task::spawn_blocking(move || sha256_file(&path))
        .await
        .map_err(|e| format!("Tarefa de checagem de integridade falhou: {e}"))?
}

/// Compara o hash local (se o arquivo existir) contra o hash esperado do
/// manifest. `Ok(true)` = arquivo presente e integro; `Ok(false)` = ausente
/// ou corrompido (precisa (re)baixar).
pub async fn matches_expected(path: &Path, expected_sha256: &str) -> Result<bool, String> {
    if !path.exists() {
        return Ok(false);
    }
    let actual = sha256_file_async(path.to_path_buf()).await?;
    Ok(actual.eq_ignore_ascii_case(expected_sha256))
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn sha256_file_matches_known_vector() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("empty.bin");
        std::fs::File::create(&path).unwrap();
        // SHA-256 do arquivo vazio, vetor de teste padrao.
        assert_eq!(
            sha256_file(&path).unwrap(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b85"
        );
    }

    #[test]
    fn sha256_file_detects_content() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("hello.bin");
        let mut f = std::fs::File::create(&path).unwrap();
        f.write_all(b"hello world").unwrap();
        drop(f);
        // sha256("hello world")
        assert_eq!(
            sha256_file(&path).unwrap(),
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde"
        );
    }

    #[tokio::test]
    async fn matches_expected_false_when_missing() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nope.bin");
        assert!(!matches_expected(&path, "anything").await.unwrap());
    }

    #[tokio::test]
    async fn matches_expected_true_when_hash_matches_case_insensitive() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("hello.bin");
        tokio::fs::write(&path, b"hello world").await.unwrap();
        let expected = "B94D27B9934D3E08A52E52D7DA7DABFAC484EFE37A5380EE9088F7ACE2EFCDE";
        assert!(matches_expected(&path, expected).await.unwrap());
    }

    #[tokio::test]
    async fn matches_expected_false_when_hash_diverges() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("hello.bin");
        tokio::fs::write(&path, b"hello world").await.unwrap();
        assert!(!matches_expected(&path, "0".repeat(64).as_str()).await.unwrap());
    }
}
