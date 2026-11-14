"""Create the database schema for the configured environment.

Usage (from the Backend directory):
    python -m scripts.migrate

On PostgreSQL with PGVECTOR_ENABLED=true this creates the vector extension
before creating tables. The script is idempotent; it never drops data.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings, load_dotenv_if_present  # noqa: E402
from app.database import engine, init_db  # noqa: E402


def main() -> int:
    load_dotenv_if_present(str(ROOT / ".env"))
    settings = get_settings()

    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)

    if engine.dialect.name == "postgresql" and settings.pgvector_enabled:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    init_db()
    print(
        f"schema ready: dialect={engine.dialect.name} "
        f"pgvector={settings.pgvector_enabled} storage={settings.storage_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
