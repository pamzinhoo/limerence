"""
Restaura o backup JSON do bot (pasta database/*.json) num Postgres novo (Neon).

Uso (rodar local, na pasta backend, com DATABASE_URL no ambiente/.env apontando
pro banco novo, e com `alembic upgrade head` ja executado nesse banco):

    python scripts/restore_backup.py "C:\\caminho\\pro\\backup\\extraido"

O argumento e a pasta que contem a subpasta "database/" (a raiz do zip
extraido, ex: onde estao config/, dashboard/, database/, ranking/, transcricoes/).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
import os

load_dotenv()

# Ordem importa por causa de foreign keys.
TABLE_ORDER = [
    "guild_settings",
    "staff",
    "tickets",
    "claims",
    "evaluations",
    "ticket_messages",
    "achievements",
    "staff_stats",
    "logs",
]

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def convert(value):
    if value is None:
        return None
    if isinstance(value, str):
        if _UUID_RE.match(value):
            return uuid.UUID(value)
        if _DATE_RE.match(value):
            return date.fromisoformat(value)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


async def restore_table(conn: asyncpg.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    col_list = ", ".join(f'"{c}"' for c in cols)
    query = (
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT DO NOTHING'
    )
    inserted = 0
    for row in rows:
        values = [convert(row.get(c)) for c in cols]
        try:
            await conn.execute(query, *values)
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [aviso] linha ignorada em {table}: {exc}")
    return inserted


async def main(backup_dir: Path) -> None:
    db_dir = backup_dir / "database"
    if not db_dir.exists():
        raise SystemExit(f"Pasta nao encontrada: {db_dir}")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL nao definido no ambiente/.env")
    # asyncpg nao entende o prefixo +asyncpg nem ?ssl=require
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]

    conn = await asyncpg.connect(dsn, ssl="require")
    try:
        for table in TABLE_ORDER:
            f = db_dir / f"{table}.json"
            if not f.exists():
                print(f"- {table}: sem arquivo, pulando")
                continue
            rows = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                rows = [rows]
            n = await restore_table(conn, table, rows)
            print(f"- {table}: {n}/{len(rows)} linhas inseridas")
    finally:
        await conn.close()

    print("Restauracao concluida.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/restore_backup.py <pasta_do_backup_extraido>")
    asyncio.run(main(Path(sys.argv[1])))
