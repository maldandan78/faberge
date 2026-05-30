#!/usr/bin/env python3
"""Применить схему (и опционально демо-данные) к PostgreSQL.

Работает и с локальной БД, и с Yandex Managed PostgreSQL (TLS через
DB_SSL_ROOT_CERT). Читает DATABASE_URL из окружения / .env.

    python scripts/init_db.py            # только схема
    python scripts/init_db.py --seed     # схема + db/seed.sql
"""
from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent


def _dsn() -> str:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://faberge:faberge@localhost:5432/faberge"
    )
    # asyncpg.connect ожидает driver-agnostic DSN.
    return url.replace("+asyncpg", "")


async def _run(seed: bool) -> None:
    ca = os.environ.get("DB_SSL_ROOT_CERT")
    ssl_ctx = ssl.create_default_context(cafile=ca) if ca else None
    conn = await asyncpg.connect(_dsn(), ssl=ssl_ctx)
    try:
        await conn.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        print("schema applied")
        if seed:
            await conn.execute((ROOT / "db" / "seed.sql").read_text(encoding="utf-8"))
            print("seed applied")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Init/seed the Faberge guide database.")
    parser.add_argument("--seed", action="store_true", help="также загрузить db/seed.sql")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.seed))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
