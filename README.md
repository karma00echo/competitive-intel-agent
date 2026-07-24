# Universal Competitive Intelligence Agent

通用竞品建档与动态追踪 Agent。

The repository currently contains:

- phase one: Python project configuration, MySQL schema, transactions, and
  repositories;
- phase two: bounded HTML fetching, deterministic page cleaning, SHA-256
  content hashes, persisted snapshots, and page-level change detection;
- phase three: provider-neutral search, deterministic queries, URL
  normalization, official-source validation, official-page discovery, and
  verified source persistence;
- phase four: structured fact schemas, provider-neutral extraction,
  deterministic evidence validation, stable fact keys, and confirmed fact
  persistence.

Fact-level history comparison, Agent Tool Calling, reports, and the complete
CLI workflow are not implemented yet.

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

## Phase-three source discovery

`SourceDiscoveryService` accepts only a competitor name. It generates bounded
queries, calls a `SearchProvider`, normalizes and deduplicates candidates,
validates official ownership, discovers official pages, validates those pages,
and saves only `VERIFIED` sources through `Persistence`.

Search, validation, and page discovery remain separate responsibilities:

- `SearchProvider.search()` returns candidates and never decides ownership.
- `validate_official_source()` evaluates evidence and never searches or saves.
- `discover_sources()` finds page candidates from an already verified homepage
  and never promotes cross-domain pages to official sources.

### FixtureSearchProvider

Fixture mode reads fixed JSON search results and fixed HTML pages. It contains
mixed official, encyclopedia, news, app-store, advertising, and aggregator
candidates for deterministic testing.

After configuring a local MySQL database:

```powershell
python scripts/discover_competitor_sources.py "Notion" --provider fixture
python scripts/discover_competitor_sources.py "飞书" --provider fixture --language zh
```

The output is structured JSON containing the generated queries, candidates,
verification decisions, official domain, discoveries, saved source IDs,
pending decisions, rejected third parties, warnings, and errors. This script
is a phase-three demonstration, not the final Agent CLI. A missing fixture
returns a structured `FIXTURE_NOT_FOUND` error instead of crashing.

### Verification and discovery states

Official verification uses combined domain/brand agreement, title and body
identity, canonical URL, internal links, copyright/company text, successful
page retrieval, and known third-party risk categories. Search rank is only a
weak signal.

| Verification state | Meaning |
|---|---|
| `VERIFIED` | Multiple independent signals support official ownership |
| `REJECTED` | Known third-party, media, store, social, download, ad, or aggregator source |
| `PENDING_CONFIRMATION` | Plausible but insufficient or conflicting evidence |

| Discovery state | Meaning |
|---|---|
| `FOUND` | A candidate was found and can proceed through validation |
| `NOT_FOUND` | No public candidate was found; no URL is fabricated |
| `AMBIGUOUS` | Multiple candidates or insufficient validation require review |
| `UNSUPPORTED` | The page cannot be inspected with the current static fetcher |

### Adding a real search provider

Implement the `SearchProvider` protocol in
`competitive_intel.infrastructure.search.providers`, then register it in
`create_search_provider()`. Read credentials from `SEARCH_API_KEY` and
`SEARCH_ENDPOINT`; never place them in code or fixtures. Missing search
configuration must not break imports.

A real provider is not required for phase-three acceptance because it would
make tests depend on network availability, credentials, quotas, changing
rankings, and potentially paid requests. Fixture mode proves the complete
source-discovery control flow without those variables.

## Phase-four structured facts

`FactExtractionService` reads only `VERIFIED` active sources and their latest
successful snapshots. It selects schemas by source type, calls a
`FactExtractionProvider`, validates the payload, checks exact evidence, creates
stable keys, removes duplicates, and saves only confirmed `FACT` statements
through `Persistence`.

Supported categories and important fields:

| Category | Structured fields |
|---|---|
| `POSITIONING` | primary positioning, target users, use cases, deployment, public description |
| `FEATURE` | name, normalized name, description, finite category, availability, related plan, status |
| `PLAN` | name, normalized name, description, target user, included features, public status |
| `PRICE` | plan, decimal amount, currency, period, unit, commitment, region, tax status, public status |
| `PRODUCT_UPDATE` | title, explicit published date, type, affected features, summary, availability, status |

Fixture extraction reads `tests/fixtures/facts/facts.json`; it makes no model
or network calls. The demonstration prepares fixture sources and successful
fixture snapshots when needed:

```powershell
python scripts/extract_competitor_facts.py "Notion" --provider fixture
python scripts/extract_competitor_facts.py "飞书" --provider fixture --language zh
```

Each candidate must use `statement_type=FACT`, pass its category schema, and
include an evidence fragment found in the snapshot's `clean_content` after
only Unicode and whitespace normalization. Price evidence additionally has to
support the plan name, amount, currency, billing period, billing unit, and
billing commitment. Missing evidence is `INSUFFICIENT_EVIDENCE`; contradictory
values are `CONFLICTING`; invalid fields are `INVALID_SCHEMA`. None of these
states is persisted.

Stable keys exclude the competitor name. Examples:

```text
positioning.primary
feature.collaborative_docs
plan.business
price.business.month.user.annual_billing
product_update.2026_07_15_enterprise_search
```

Keys normalize Unicode, case, whitespace, names, and decimal amounts. Price
period, unit, and commitment remain separate dimensions. A matching
snapshot/key is treated as `DUPLICATE`, making repeated extraction idempotent.

To add a real model, implement `FactExtractionProvider` and register it in a
future provider factory. Read `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, and
`LLM_ENDPOINT` from configuration. The adapter must send bounded snapshot
content, require strict JSON and exact evidence, and must not use model
knowledge or web search to fill missing facts. Real model access is not part of
phase-four acceptance and is never used by default tests.

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
content with a disposable local MySQL database. Source-discovery tests use
fixed search JSON and official-site HTML. Fact-extraction tests use the JSON
fixture provider and never call a model API or incur model charges. This keeps
ranking, timeout, redirect, content-size, JavaScript-shell, validation,
discovery, extraction, and evidence results reproducible.

## Not implemented yet

- fact-level history comparison
- Agent Tool Calling and model APIs
- report generation
- complete CLI business workflow
- frontend, scheduling, Playwright, RAG, and vector databases
- a real search-provider adapter; future configuration requires
  `SEARCH_PROVIDER`, `SEARCH_API_KEY`, and `SEARCH_ENDPOINT`
- a real model fact-extraction adapter; future configuration requires
  `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_ENDPOINT`
