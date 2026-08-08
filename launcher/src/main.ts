import { invoke } from "@tauri-apps/api/core";
import { renderHomeView, renderLoginView } from "./views/login";

interface SessionInfo {
  logged_in: boolean;
}

async function bootstrap(): Promise<void> {
  const root = document.querySelector<HTMLElement>("#app");
  if (!root) return;

  root.innerHTML = `<p class="hint">Verificando sessao...</p>`;

  let session: SessionInfo;
  try {
    session = await invoke<SessionInfo>("check_session");
  } catch {
    session = { logged_in: false };
  }

  if (session.logged_in) {
    showHome(root);
  } else {
    showLogin(root);
  }
}

function showLogin(root: HTMLElement): void {
  renderLoginView(root, () => showHome(root));
}

function showHome(root: HTMLElement): void {
  renderHomeView(root, () => showLogin(root));
}

bootstrap();
