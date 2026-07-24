from __future__ import annotations

import os
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from competitive_intel.config import DatabaseSettings, Settings
from competitive_intel.persistence import Database, Persistence
from competitive_intel.persistence.schema import initialize_schema


DELETE_ORDER = (
    "tool_calls",
    "stage_events",
    "reports",
    "changes",
    "product_facts",
    "snapshots",
    "sources",
    "agent_runs",
    "competitors",
)


@pytest.fixture(scope="session")
def fixture_pages() -> dict[str, str]:
    pages_dir = PROJECT_ROOT / "tests" / "fixtures" / "pages"
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in pages_dir.glob("*.html")
    }


def _integration_settings() -> DatabaseSettings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    full_url = os.getenv("TEST_DATABASE_URL")
    if full_url:
        url = make_url(full_url)
        settings = DatabaseSettings(
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            name=url.database or "",
            user=url.username or "",
            password=url.password or "",
            charset=url.query.get("charset", "utf8mb4"),
        )
    else:
        base = Settings.from_env(None).database
        settings = replace(
            base,
            host=os.getenv("TEST_DB_HOST", base.host),
            port=int(os.getenv("TEST_DB_PORT", str(base.port))),
            name=os.getenv("TEST_DB_NAME", "competitive_intel_test"),
            user=os.getenv("TEST_DB_USER", base.user),
            password=os.getenv("TEST_DB_PASSWORD", base.password),
        )
    if not re.fullmatch(r"[A-Za-z0-9_]+", settings.name):
        pytest.fail("Unsafe TEST_DB_NAME; use only letters, digits, and underscore.")
    if not settings.name.endswith("_test"):
        pytest.fail("Integration tests refuse databases without a _test suffix.")
    return settings


@pytest.fixture(scope="session")
def mysql_engine() -> Engine:
    settings = _integration_settings()
    try:
        server_engine = create_engine(settings.server_url, pool_pre_ping=True)
        with server_engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE IF NOT EXISTS `{settings.name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        server_engine.dispose()
        engine = create_engine(settings.url, pool_pre_ping=True)
        initialize_schema(engine)
    except Exception as exc:
        pytest.fail(
            "Cannot initialize disposable MySQL integration database. "
            "Configure TEST_DATABASE_URL or TEST_DB_* in .env. "
            f"Original error: {type(exc).__name__}: {exc}"
        )
    yield engine
    engine.dispose()


def _clear_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        for table_name in DELETE_ORDER:
            connection.execute(text(f"DELETE FROM `{table_name}`"))


@pytest.fixture()
def persistence(mysql_engine: Engine) -> Persistence:
    _clear_rows(mysql_engine)
    value = Persistence(Database(engine=mysql_engine))
    yield value
    _clear_rows(mysql_engine)
