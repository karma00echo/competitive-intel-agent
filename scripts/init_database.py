"""Create and initialize the application or disposable test database."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from competitive_intel.config import DatabaseSettings, Settings  # noqa: E402
from competitive_intel.persistence.schema import initialize_schema  # noqa: E402


def _test_settings() -> DatabaseSettings:
    full_url = os.getenv("TEST_DATABASE_URL")
    if full_url:
        from sqlalchemy.engine import make_url

        url = make_url(full_url)
        return DatabaseSettings(
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            name=url.database or "",
            user=url.username or "",
            password=url.password or "",
            charset=url.query.get("charset", "utf8mb4"),
        )
    base = Settings.from_env(None).database
    return replace(
        base,
        host=os.getenv("TEST_DB_HOST", base.host),
        port=int(os.getenv("TEST_DB_PORT", str(base.port))),
        name=os.getenv("TEST_DB_NAME", "competitive_intel_test"),
        user=os.getenv("TEST_DB_USER", base.user),
        password=os.getenv("TEST_DB_PASSWORD", base.password),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--database-exists", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    settings = _test_settings() if args.test else Settings.from_env(None).database
    if not re.fullmatch(r"[A-Za-z0-9_]+", settings.name):
        raise SystemExit("Database name may contain only letters, digits, and underscore.")
    if args.test and not settings.name.endswith("_test"):
        raise SystemExit("Refusing to initialize a test database without a _test suffix.")

    if not args.database_exists:
        server_engine = create_engine(settings.server_url, pool_pre_ping=True)
        with server_engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE IF NOT EXISTS `{settings.name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        server_engine.dispose()

    engine = create_engine(settings.url, pool_pre_ping=True)
    initialize_schema(engine)
    engine.dispose()
    print(f"Initialized MySQL database: {settings.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

