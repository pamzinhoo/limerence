//! "Preparar ambiente": ultimo passo antes de iniciar o Ren'Py, 100% local
//! (nenhuma chamada de rede aqui — toda licenca/download ja aconteceu em
//! `download::ensure_installed`). Garante que os diretorios que o jogo
//! espera existem e resolve o diretorio de trabalho correto pro spawn do
//! processo.

use std::path::{Path, PathBuf};

/// Ambiente local pronto pra `game_launcher::launch` — o Ren'Py so enxerga
/// isto, nunca o backend, nunca licenca, nunca token.
#[derive(Debug, Clone)]
pub struct PreparedEnvironment {
    pub executable_path: PathBuf,
    pub working_dir: PathBuf,
    pub content_dir: PathBuf,
}

/// Monta o ambiente local: cria `content_dir` se ainda nao existir (onde
/// `download::ensure_installed` ja deixou base game + DLCs) e resolve o
/// diretorio de trabalho do processo do Ren'Py (o diretorio que contem o
/// executavel, convencao padrao de builds distribuidos do Ren'Py — o
/// executavel espera uma pasta `game/` irma dele).
pub fn prepare(executable_path: &Path, content_dir: &Path) -> Result<PreparedEnvironment, String> {
    if !executable_path.exists() {
        return Err(format!("Executavel do jogo nao encontrado em {executable_path:?}."));
    }

    std::fs::create_dir_all(content_dir)
        .map_err(|e| format!("Nao foi possivel preparar o diretorio de conteudo {content_dir:?}: {e}"))?;

    let working_dir = executable_path
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| format!("Nao foi possivel resolver o diretorio de trabalho a partir de {executable_path:?}."))?;

    Ok(PreparedEnvironment {
        executable_path: executable_path.to_path_buf(),
        working_dir,
        content_dir: content_dir.to_path_buf(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prepare_fails_when_executable_missing() {
        let dir = tempfile::tempdir().unwrap();
        let err = prepare(&dir.path().join("nope.exe"), &dir.path().join("content")).unwrap_err();
        assert!(err.contains("nao encontrado"));
    }

    #[test]
    fn prepare_creates_content_dir_and_resolves_working_dir() {
        let dir = tempfile::tempdir().unwrap();
        let exe_dir = dir.path().join("Limerence");
        std::fs::create_dir_all(&exe_dir).unwrap();
        let exe_path = exe_dir.join("Limerence.exe");
        std::fs::write(&exe_path, b"fake exe").unwrap();
        let content_dir = dir.path().join("content");

        let env = prepare(&exe_path, &content_dir).unwrap();
        assert_eq!(env.working_dir, exe_dir);
        assert!(content_dir.exists());
    }
}
