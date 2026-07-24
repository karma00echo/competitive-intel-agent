# Universal Competitive Intelligence Agent

通用竞品建档与动态追踪 Agent。

The repository currently contains:

- phase one: Python project configuration, MySQL schema, transactions, and
  repositories;
- phase two: bounded HTML fetching, deterministic page cleaning, SHA-256
  content hashes, persisted snapshots, and page-level change detection.

Automatic source discovery, fact extraction, model tool calling, reports, and
the complete CLI workflow are not implemented yet.

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

The command is idempotent and executes `migrations/001_initial_schema.sql`.

## Prepare a verified source

Source discovery and official-source validation are intentionally not
implemented yet. During development, prepare a known test source through the
existing Persistence boundary:

```python
from datetime import UTC, datetime
from decimal import Decimal

from competitive_intel.config import Settings
from competitive_intel.persistence import Database, Persistence

settings = Settings.from_env()
persistence = Persistence(Database(settings.database))

with persistence.transaction() as session:
    competitor_id = persistence.competitors.create(
        session,
        canonical_name="Example",
        normalized_name="example",
        official_domain="example.com",
    )
    source_id = persistence.sources.create(
        session,
        competitor_id=competitor_id,
        source_type="HOMEPAGE",
        url="https://example.com/",
        normalized_url="https://example.com/",
        domain="example.com",
        verification_status="VERIFIED",
        verification_reason="Manually prepared development fixture",
        confidence=Decimal("1.0000"),
        verified_at=datetime.now(UTC).replace(tzinfo=None),
    )
```

The snapshot service rejects unverified or disabled sources. Application code
must not insert records with direct SQL.

## Phase-two page states

| State | Meaning |
|---|---|
| `BASELINE` | First successful snapshot for the source |
| `UNCHANGED` | Current clean hash equals the latest successful clean hash |
| `PAGE_CHANGED` | Current clean hash differs from the latest successful hash |
| `FETCH_FAILED` | Request, HTTP, decoding, size, or cleaning failure |
| `JS_UNSUPPORTED` | Requests received a probable JavaScript-only shell |
| `UNSUPPORTED_CONTENT` | Response is not supported HTML |

Failed, blocked, and JavaScript-only snapshots are saved for auditing but
never become the latest successful snapshot. A failed fetch is not interpreted
as an unchanged page.

## Tests

Configure either `TEST_DATABASE_URL` or the `TEST_DB_*` values. Tests refuse to
operate on a database whose name does not end in `_test`.

Create and initialize the disposable test database:

```powershell
python scripts/init_database.py --test
```

Run the complete suite:

```powershell
python -m pytest
```

Run only deterministic fetcher and cleaner tests:

```powershell
python -m pytest tests/unit -v
```

Run the snapshot service integration tests:

```powershell
python -m pytest tests/integration/test_snapshot_service.py -v
```

Default tests never contact the public internet. Fetcher tests use mocked
requests responses and fixed HTML fixtures; snapshot tests use the same fixed
content with a disposable local MySQL database. This keeps timeout, redirect,
content-size, JavaScript-shell, and change results reproducible.

## Not implemented yet

- `search_web`
- `validate_official_source`
- `discover_sources`
- fact extraction and fact-level history comparison
- Agent Tool Calling and model APIs
- report generation
- complete CLI business workflow
- frontend, scheduling, Playwright, RAG, and vector databases

