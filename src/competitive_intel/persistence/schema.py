"""Schema initialization helpers used by scripts and integration tests."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_PATH = PROJECT_ROOT / "migrations"
SCHEMA_PATH = MIGRATIONS_PATH / "001_initial_schema.sql"


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


def initialize_schema(engine: Engine, schema_path: Path = MIGRATIONS_PATH) -> None:
    paths = (
        sorted(schema_path.glob("*.sql"))
        if schema_path.is_dir()
        else [schema_path]
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) NOT NULL,
                applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                PRIMARY KEY (version)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COLLATE=utf8mb4_0900_ai_ci
            """
        )
        applied = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT version FROM schema_migrations"
            )
        }
        for path in paths:
            if path.name in applied:
                continue
            script = path.read_text(encoding="utf-8")
            for statement in _split_sql(script):
                connection.exec_driver_sql(statement)
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (path.name,),
            )
