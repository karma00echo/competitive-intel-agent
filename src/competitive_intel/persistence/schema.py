"""Schema initialization helpers used by scripts and integration tests."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = PROJECT_ROOT / "migrations" / "001_initial_schema.sql"


def _split_sql(script: str) -> list[str]:
    """Split this repository's DDL file into executable statements."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buffer).rstrip().removesuffix(";"))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements


def initialize_schema(engine: Engine, schema_path: Path = SCHEMA_PATH) -> None:
    script = schema_path.read_text(encoding="utf-8")
    with engine.begin() as connection:
        for statement in _split_sql(script):
            connection.exec_driver_sql(statement)

