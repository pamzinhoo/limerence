from __future__ import annotations

import uvicorn

from api.main import create_app
from config.settings import SettingsError, get_settings

try:
    settings = get_settings()
except SettingsError as exc:
    print(f"Erro de configuracao: {exc}")
    raise SystemExit(1) from exc

app = create_app()


def run() -> None:
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("Backend encerrado pelo usuario.")
