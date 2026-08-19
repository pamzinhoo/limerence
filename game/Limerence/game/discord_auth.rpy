# ============================================================================
# Login com Discord (device flow) contra o backend Limerence.
# Backend: https://limerence-backend.onrender.com (ver backend/api/routes/auth_routes.py)
# ============================================================================

init -10 python:
    import json
    import platform
    import ssl
    import threading
    import urllib.request
    import urllib.error
    import uuid as _uuid
    import webbrowser

    DISCORD_AUTH_BACKEND_URL = "https://limerence-backend.onrender.com"

    def _discord_ssl_context():
        """Python embutido do Ren'Py SDK as vezes nao enxerga a lista de CAs
        do sistema. Tenta usar certifi (se empacotado); se nao der, cai pro
        contexto padrao do sistema; em ultimo caso, segue sem verificar
        (evita travar o login por causa disso, backend e https conhecido)."""
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
        try:
            return ssl.create_default_context()
        except Exception:
            pass
        ctx = ssl._create_unverified_context()
        return ctx

    _DISCORD_SSL_CONTEXT = _discord_ssl_context()

    class DiscordAuthState(object):
        """Estado compartilhado entre a thread de rede e a UI (thread principal)."""

        def __init__(self):
            self.reset()

        def reset(self):
            self.status = "idle"          # idle | starting | waiting_browser | polling | success | error | expired | denied
            self.message = ""
            self.verification_uri = None
            self.user_code = None
            self.device_code = None
            self.interval = 5
            self.error = None

    discord_auth_state = DiscordAuthState()

    def _discord_device_uuid():
        """UUID estavel por instalacao, guardado no persistent do Ren'Py."""
        if not persistent.discord_device_uuid:
            persistent.discord_device_uuid = str(_uuid.uuid4())
        return persistent.discord_device_uuid

    def _discord_http_json(path, payload, timeout=15):
        url = DISCORD_AUTH_BACKEND_URL + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_DISCORD_SSL_CONTEXT) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), None
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                msg = body.get("detail", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            return None, msg
        except Exception as exc:
            return None, str(exc)

    def _discord_login_worker():
        state = discord_auth_state
        state.status = "starting"

        payload = {
            "device_uuid": _discord_device_uuid(),
            "os_info": platform.platform(),
            "launcher_version": config.version,
        }
        data, err = _discord_http_json("/auth/device/code", payload)
        if err or not data:
            state.status = "error"
            state.error = err or "Falha ao iniciar login."
            return

        state.device_code = data["device_code"]
        state.user_code = data["user_code"]
        state.verification_uri = data["verification_uri"]
        state.interval = data.get("interval", 5)
        state.status = "waiting_browser"

        try:
            webbrowser.open(state.verification_uri)
        except Exception:
            pass

        state.status = "polling"

        import time
        expires_at = time.time() + data.get("expires_in", 600)
        while time.time() < expires_at:
            time.sleep(state.interval)

            poll_data, poll_err = _discord_http_json(
                "/auth/device/token", {"device_code": state.device_code}
            )
            if poll_err:
                # rate limit / erro de rede transitorio: continua tentando
                continue

            poll_status = poll_data.get("status")

            if poll_status == "success":
                persistent.discord_access_token = poll_data["access_token"]
                persistent.discord_refresh_token = poll_data["refresh_token"]
                state.status = "success"
                return
            elif poll_status == "slow_down":
                state.interval = poll_data.get("interval", state.interval * 2)
            elif poll_status == "access_denied":
                state.status = "denied"
                return
            elif poll_status == "expired_token":
                state.status = "expired"
                return
            # authorization_pending -> continua o loop

        state.status = "expired"

    def start_discord_login():
        if discord_auth_state.status in ("starting", "waiting_browser", "polling"):
            return
        discord_auth_state.reset()
        t = threading.Thread(target=_discord_login_worker, daemon=True)
        t.start()
        renpy.show_screen("discord_login_status")

    def discord_button_action():
        if discord_is_logged_in():
            try:
                webbrowser.open(DISCORD_AUTH_BACKEND_URL + "/auth/discord/already-linked")
            except Exception:
                pass
        else:
            start_discord_login()

    def discord_logout():
        persistent.discord_access_token = None
        persistent.discord_refresh_token = None
        discord_auth_state.reset()

    def discord_is_logged_in():
        return bool(persistent.discord_access_token)

default persistent.discord_device_uuid = None
default persistent.discord_access_token = None
default persistent.discord_refresh_token = None


## Tela de status do login (spinner / codigo / erro) ##########################
screen discord_login_status():
    modal True
    zorder 200

    add "#000000cc"

    frame:
        xalign 0.5
        yalign 0.5
        xpadding 40
        ypadding 30
        xminimum 520

        vbox:
            spacing 16
            xalign 0.5

            if discord_auth_state.status in ("starting",):
                text _("Conectando com o Discord...") xalign 0.5

            elif discord_auth_state.status in ("waiting_browser", "polling"):
                text _("Confirme o login na aba do navegador que abriu.") xalign 0.5
                if discord_auth_state.user_code:
                    text "[discord_auth_state.user_code!q]" xalign 0.5 size 34
                text _("Aguardando confirmação...") xalign 0.5 size 18

            elif discord_auth_state.status == "success":
                text _("Login concluído!") xalign 0.5
                timer 1.2 action Hide("discord_login_status")

            elif discord_auth_state.status == "denied":
                text _("Login cancelado.") xalign 0.5

            elif discord_auth_state.status == "expired":
                text _("Tempo esgotado, tente novamente.") xalign 0.5

            elif discord_auth_state.status == "error":
                text _("Não foi possível conectar: [discord_auth_state.error!q]") xalign 0.5

            if discord_auth_state.status not in ("starting", "waiting_browser", "polling"):
                textbutton _("Fechar"):
                    xalign 0.5
                    action Hide("discord_login_status")
            else:
                textbutton _("Cancelar"):
                    xalign 0.5
                    action [SetField(discord_auth_state, "status", "denied"), Hide("discord_login_status")]

    ## Repinta a tela periodicamente pra refletir o estado atualizado pela thread.
    timer 0.3 repeat True action Function(renpy.restart_interaction)
