import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

type AuthStatusEvent =
  | { status: "waiting_browser"; user_code: string; verification_uri: string }
  | { status: "success" }
  | { status: "expired" }
  | { status: "denied" }
  | { status: "error"; message: string };

interface SessionInfo {
  logged_in: boolean;
}

type PlayStatusEvent =
  | { stage: "checking_license"; product_id: string }
  | { stage: "downloading"; product_id: string; attempt: number }
  | { stage: "repairing"; product_id: string; attempt: number }
  | { stage: "validating"; product_id: string }
  | { stage: "preparing_environment" }
  | { stage: "launching" }
  | { stage: "started" }
  | { stage: "exited"; success: boolean; code: number | null }
  | { stage: "error"; message: string };

function describePlayStatus(payload: PlayStatusEvent): string {
  switch (payload.stage) {
    case "checking_license":
      return "Verificando licenca...";
    case "downloading":
      return `Baixando conteudo (tentativa ${payload.attempt})...`;
    case "repairing":
      return `Reparando arquivo corrompido (tentativa ${payload.attempt})...`;
    case "validating":
      return "Validando integridade dos arquivos...";
    case "preparing_environment":
      return "Preparando ambiente do jogo...";
    case "launching":
      return "Iniciando o jogo...";
    case "started":
      return "Jogo em execucao.";
    case "exited":
      return payload.success ? "Jogo encerrado." : `Jogo encerrado com erro (codigo ${payload.code ?? "?"}).`;
    case "error":
      return `Erro: ${payload.message}`;
  }
}

export function renderLoginView(root: HTMLElement, onLoggedIn: () => void): void {
  root.innerHTML = `
    <section class="login">
      <h1>Limerence Launcher</h1>
      <p class="hint" id="login-hint">Entre com sua conta Discord pra continuar.</p>
      <button id="login-button">Entrar com Discord</button>
      <div id="login-progress" hidden>
        <p>Codigo: <strong id="user-code"></strong></p>
        <p class="hint">Confirme no navegador que abriu. Voltando aqui sozinho.</p>
      </div>
    </section>
  `;

  const button = root.querySelector<HTMLButtonElement>("#login-button")!;
  const hint = root.querySelector<HTMLParagraphElement>("#login-hint")!;
  const progress = root.querySelector<HTMLDivElement>("#login-progress")!;
  const userCodeEl = root.querySelector<HTMLElement>("#user-code")!;

  let unlisten: UnlistenFn | null = null;

  button.addEventListener("click", async () => {
    button.disabled = true;
    hint.textContent = "Iniciando login...";

    unlisten = await listen<AuthStatusEvent>("auth://status", (event) => {
      const payload = event.payload;
      switch (payload.status) {
        case "waiting_browser":
          progress.hidden = false;
          userCodeEl.textContent = payload.user_code;
          hint.textContent = "Aguardando confirmacao no navegador...";
          break;
        case "success":
          hint.textContent = "Login concluido!";
          break;
        case "expired":
          hint.textContent = "Codigo expirou. Tente novamente.";
          button.disabled = false;
          progress.hidden = true;
          break;
        case "denied":
          hint.textContent = "Login negado. Tente novamente.";
          button.disabled = false;
          progress.hidden = true;
          break;
        case "error":
          hint.textContent = `Erro: ${payload.message}`;
          button.disabled = false;
          progress.hidden = true;
          break;
      }
    });

    try {
      const result = await invoke<SessionInfo>("login_start");
      if (result.logged_in) {
        onLoggedIn();
      }
    } catch (err) {
      hint.textContent = `Erro: ${String(err)}`;
      button.disabled = false;
    } finally {
      unlisten?.();
      unlisten = null;
    }
  });
}

export function renderHomeView(root: HTMLElement, onLogout: () => void): void {
  root.innerHTML = `
    <section class="home">
      <h1>Limerence</h1>
      <button id="play-button">Jogar</button>
      <button id="logout-button">Sair</button>
      <p class="hint" id="home-hint"></p>
    </section>
  `;

  const hint = root.querySelector<HTMLParagraphElement>("#home-hint")!;
  const playButton = root.querySelector<HTMLButtonElement>("#play-button")!;

  playButton.addEventListener("click", async () => {
    playButton.disabled = true;
    const unlisten = await listen<PlayStatusEvent>("game://status", (event) => {
      hint.textContent = describePlayStatus(event.payload);
    });
    try {
      await invoke("play_game");
    } catch (err) {
      hint.textContent = `Nao foi possivel iniciar o jogo: ${String(err)}`;
    } finally {
      unlisten();
      playButton.disabled = false;
    }
  });

  root.querySelector<HTMLButtonElement>("#logout-button")!.addEventListener("click", async () => {
    await invoke("logout");
    onLogout();
  });
}
