# Universal Competitive Intelligence Agent

通用竞品建档与动态追踪 Agent。

The first development phase contains only project configuration, MySQL schema,
database connections, repositories, and database integration tests. Search,
web fetching, extraction, model tool calling, reports, and CLI workflows are
intentionally not implemented yet.

## Requirements

- Python 3.12
- MySQL 8.0+ or MySQL 9.x
- A MySQL account allowed to create the application/test databases, or
  databases created beforehand through Navicat

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` locally. Never commit it.

## Initialize the application database

If the configured account can create databases:

```powershell
python scripts/init_database.py
```

If it cannot, create `competitive_intel` in Navicat with `utf8mb4`, then run:

```powershell
python scripts/init_database.py --database-exists
```

The command is idempotent: it executes
`migrations/001_initial_schema.sql`, whose tables use `CREATE TABLE IF NOT
EXISTS`.

## Run database integration tests

Tests intentionally refuse to run against a database whose name does not end
in `_test`. Configure either `TEST_DATABASE_URL` or the `TEST_DB_*` values.

Create and initialize the disposable test database:

```powershell
python scripts/init_database.py --test
```

Run all phase-one tests:

```powershell
python -m pytest
```

Run only database integration tests:

```powershell
python -m pytest -m integration -v
```

The integration suite clears rows from the disposable test database between
tests. It never touches the application database.

