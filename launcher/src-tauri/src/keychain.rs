use keyring::Entry;

const SERVICE: &str = "com.limerence.launcher";
const USERNAME: &str = "refresh_token";

/// Guarda o refresh token no cofre do SO (Credential Manager no Windows,
/// Keychain no macOS, Secret Service no Linux) — nunca em arquivo texto
/// puro. Regra obrigatoria do fluxo de login: token Discord nunca e
/// guardado (nem chega aqui); o unico segredo persistido pelo Launcher e
/// este refresh token opaco emitido pelo backend.
fn entry() -> Result<Entry, String> {
    Entry::new(SERVICE, USERNAME).map_err(|e| format!("Falha ao acessar o keychain do sistema: {e}"))
}

pub fn save_refresh_token(token: &str) -> Result<(), String> {
    entry()?
        .set_password(token)
        .map_err(|e| format!("Falha ao salvar refresh token no keychain: {e}"))
}

pub fn load_refresh_token() -> Option<String> {
    entry().ok()?.get_password().ok()
}

pub fn clear_refresh_token() {
    if let Ok(e) = entry() {
        // Se nao existir entrada, delete() retorna erro — ignorado de proposito,
        // "nao tinha nada pra apagar" nao e uma falha aqui.
        let _ = e.delete_credential();
    }
}
