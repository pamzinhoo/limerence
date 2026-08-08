use std::path::Path;
use tokio::process::Command;

/// So spawna o processo do Ren'Py, ja com o ambiente local montado por
/// `environment::prepare` (executavel + diretorio de trabalho corretos,
/// conteudo/DLC ja no lugar). E chamado depois que o caller confirmou
/// sessao valida, licenca ativa e arquivos integros (ver
/// `commands::play_game` em lib.rs) — o Ren'Py em si nunca sabe que existe
/// login/licenca/backend, so e executado com um cwd e um binario.
///
/// Nenhuma variavel de ambiente de auth/backend e propagada pro processo
/// filho: `Command::new` herda o ambiente do Launcher por padrao (mesmo
/// comportamento do std::process::Command), mas o Launcher nunca guarda
/// token em variavel de ambiente do proprio processo (fica so em RAM, ver
/// `AppState` em lib.rs) — nao ha nada sensivel pra vazar por heranca aqui.
pub async fn spawn(executable_path: &Path, working_dir: &Path) -> Result<tokio::process::Child, String> {
    Command::new(executable_path)
        .current_dir(working_dir)
        .kill_on_drop(false)
        .spawn()
        .map_err(|e| format!("Falha ao iniciar o jogo ({executable_path:?}): {e}"))
}

/// Resultado observavel do processo do jogo apos ele terminar — usado so
/// pra relatar erro/crash ao usuario no proprio Launcher, nunca reportado ao
/// backend (Ren'Py continua 100% desconhecido do backend, mesmo quando
/// crasha).
#[derive(Debug, Clone, serde::Serialize)]
pub struct GameExit {
    pub success: bool,
    pub code: Option<i32>,
}

/// Aguarda o processo do jogo terminar e resume o resultado pra
/// relato/diagnostico local. Bloqueia a task async chamadora ate o processo
/// fechar — o caller deve rodar isto numa `tokio::spawn` separada se nao
/// quiser travar outros comandos do Launcher enquanto o jogo esta aberto.
pub async fn wait(mut child: tokio::process::Child) -> Result<GameExit, String> {
    let status = child
        .wait()
        .await
        .map_err(|e| format!("Falha ao acompanhar o processo do jogo: {e}"))?;
    Ok(GameExit {
        success: status.success(),
        code: status.code(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(windows)]
    fn echo_executable() -> &'static str {
        "cmd.exe"
    }

    #[cfg(not(windows))]
    fn echo_executable() -> &'static str {
        "/bin/sh"
    }

    #[tokio::test]
    async fn spawn_fails_gracefully_for_missing_executable() {
        let dir = tempfile::tempdir().unwrap();
        let missing = dir.path().join("does-not-exist.exe");
        let err = spawn(&missing, dir.path()).await.unwrap_err();
        assert!(err.contains("Falha ao iniciar o jogo"));
    }

    #[tokio::test]
    async fn spawn_and_wait_reports_exit_status() {
        let dir = tempfile::tempdir().unwrap();
        #[cfg(windows)]
        let child = Command::new(echo_executable())
            .args(["/C", "exit 0"])
            .current_dir(dir.path())
            .spawn()
            .unwrap();
        #[cfg(not(windows))]
        let child = Command::new(echo_executable())
            .args(["-c", "exit 0"])
            .current_dir(dir.path())
            .spawn()
            .unwrap();

        let result = wait(child).await.unwrap();
        assert!(result.success);
        assert_eq!(result.code, Some(0));
    }

    #[tokio::test]
    async fn spawn_and_wait_reports_nonzero_exit_as_failure() {
        let dir = tempfile::tempdir().unwrap();
        #[cfg(windows)]
        let child = Command::new(echo_executable())
            .args(["/C", "exit 7"])
            .current_dir(dir.path())
            .spawn()
            .unwrap();
        #[cfg(not(windows))]
        let child = Command::new(echo_executable())
            .args(["-c", "exit 7"])
            .current_dir(dir.path())
            .spawn()
            .unwrap();

        let result = wait(child).await.unwrap();
        assert!(!result.success);
        assert_eq!(result.code, Some(7));
    }
}
