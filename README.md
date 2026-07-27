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
  persistence;
- phase five: a controlled single-Agent Runner, native tool-calling provider
  abstraction, deterministic state machine, bounded Agent tools, run audit,
  structured run summaries, and a unified CLI;
- phase six: deterministic fact normalization and history comparison,
  cross-run fact-version reuse, persisted change records, formal baseline and
  change-tracking reports, and report viewing/export.

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

The command is idempotent and executes unapplied SQL files in `migrations/`
in filename order. Applied versions are recorded in `schema_migrations`.

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

## Phase-five controlled Agent Runner

`AgentRunner` turns the existing discovery, snapshot, and fact services into
one bounded single-Agent workflow. The program—not the model—selects
`BASELINE` or `REFRESH`, validates every transition, controls tool
allowlists and budgets, decides whether data may be saved, and determines the
final state.

`BASELINE` is selected when the competitor is absent or lacks any part of a
complete profile: VERIFIED source, successful snapshot, or confirmed fact.
`REFRESH` requires all three and skips source discovery. REFRESH creates new
snapshots, extracts facts only from successful snapshots in the current run,
and then executes deterministic fact comparison and reporting.

The logical state paths are:

```text
BASELINE:
INITIALIZING -> PROFILE_LOOKUP -> MODE_SELECTION -> SOURCE_DISCOVERY
-> SOURCE_VALIDATION -> PAGE_FETCHING -> SNAPSHOT_PERSISTENCE
-> FACT_EXTRACTION -> FACT_PERSISTENCE -> REPORT_GENERATION
-> REPORT_PERSISTENCE -> RUN_SUMMARY -> terminal

REFRESH:
INITIALIZING -> PROFILE_LOOKUP -> MODE_SELECTION -> PAGE_FETCHING
-> SNAPSHOT_PERSISTENCE -> FACT_EXTRACTION -> FACT_PERSISTENCE
-> HISTORY_LOOKUP -> FACT_COMPARISON -> CHANGE_PERSISTENCE
-> REPORT_GENERATION -> REPORT_PERSISTENCE -> RUN_SUMMARY -> terminal
```

Terminal states are `COMPLETED`, `COMPLETED_WITH_WARNINGS`, and `FAILED`.
Logical states are recorded in the existing `stage_events.details_json`;
compatible phase-one audit enum values remain the physical database stages.

### Provider responsibilities

- `AgentProvider` chooses from tools allowed in the current state. It cannot
  access MySQL, determine the run mode, validate evidence, or extract facts.
- `FactExtractionProvider` converts bounded clean page content into structured
  fact candidates. It cannot control Agent states or tools.
- `FixtureAgentProvider` selects one deterministic tool per actionable state,
  uses no network or credentials, and incurs no model charges.

The registered Agent tools are:

- `get_competitor_profile`
- `discover_competitor_sources`
- `refresh_verified_sources`
- `extract_competitor_facts`
- `get_previous_fact_baseline`
- `compare_competitor_facts`
- `generate_competitor_report`
- `get_competitor_report`
- `get_run_status`
- `finalize_run_summary`

Every tool has a strict object schema, rejects unknown or missing arguments,
and returns `ok`, bounded `data`, `error_code`, `error_message`, and
`retryable`. Full HTML, full clean content, passwords, API keys, and unbounded
model output are never returned to the Agent context.

The Runner enforces a global tool budget, a per-state provider-call budget,
and a bounded identical-call retry count. Unknown, disallowed, malformed,
repeated, empty, and over-budget calls terminate deterministically. Only
errors marked `retryable=true` may be retried.

### Unified CLI

Initialize the application database, then run the completely offline fixture
workflow:

```powershell
python -m competitive_intel.cli analyze "Notion" --search-provider fixture --fact-provider fixture --agent-provider fixture --verbose
python -m competitive_intel.cli analyze "飞书" --search-provider fixture --fact-provider fixture --agent-provider fixture --language zh --verbose
```

The first complete run uses `BASELINE`; a later run uses `REFRESH`. Verbose
mode prints bounded tool requests, results, and state transitions, never raw
page content or credentials. Exit codes are:

| Code | Meaning |
|---:|---|
| `0` | `COMPLETED` |
| `2` | `COMPLETED_WITH_WARNINGS` |
| `1` | `FAILED` |
| `64` | Invalid input or provider/configuration |

The structured summary includes the persisted formal report ID/type and
deterministic fact-change counts.

To add a real tool-calling model, implement `AgentProvider` and register it in
a future provider factory. Configuration is reserved as `AGENT_PROVIDER`,
`AGENT_API_KEY`, `AGENT_MODEL`, and `AGENT_ENDPOINT`. The adapter must honor
the supplied allowlist and strict tool schemas; missing real-model
configuration does not affect fixture imports or tests.

## Phase-six fact history and reports

Fact identity is `(competitor_id, fact_category, fact_key)`. `fact_key` is the
primary semantic identity; normalized business values decide whether that
identity is unchanged or modified. Evidence text, confidence, source,
snapshot, and collection time remain auditable metadata and do not by
themselves produce `MODIFIED`.

`FactNormalizer` applies category-specific rules:

- `PRICE`: decimal formatting is canonical, currency and billing enums are
  uppercase, and `null` remains distinct from `UNKNOWN`;
- `FEATURE`: names and whitespace are normalized; status, availability, and
  related plans remain business fields;
- `PLAN`: plan names and public status are normalized, and included-feature
  arrays are sorted before comparison;
- `POSITIONING`: whitespace is normalized and list-like sets are sorted;
- `PRODUCT_UPDATE`: date, title, and update type remain part of stable
  identity/value semantics, so recrawling the same update is unchanged.

The additive migration `002_fact_history.sql` creates `fact_versions` and
`fact_observations` without altering phase-one tables. Existing facts are
backfilled. `product_facts` stores distinct business versions;
`fact_observations` links each run to the version it observed. Therefore an
unchanged refresh reuses the previous `fact_id` without growing
`product_facts`, while retaining current-run evidence. Modified facts create a
new version with `supersedes_fact_id`; old values remain queryable.

The five core comparison states are:

| State | Rule |
|---|---|
| `ADDED` | Identity absent from the previous valid baseline, present now |
| `MODIFIED` | Same identity, different normalized business value |
| `UNCHANGED` | Same identity and normalized business value |
| `REMOVED` | Previously present, now absent, with a successful complete source fetch |
| `UNCOMPARABLE` | Absence cannot be trusted because fetching or source coverage failed |

A failed page is never `REMOVED`. `COMPLETED_WITH_WARNINGS` runs are valid
comparison baselines because their physical persisted status is `COMPLETED`;
individual failed-source facts remain protected by `UNCOMPARABLE`. Runs with
physical status `FAILED` are never selected. Source coverage is conservative:
the current source must have both a successful snapshot and at least one
confirmed observation before absence can become `REMOVED`; otherwise it is
`UNCOMPARABLE`.

`changes` stores idempotent per-run comparison records with old/new fact IDs
and values, evidence, confidence, and the deterministic reason. Because its
original enum uses `UNKNOWN`, logical `UNCOMPARABLE` is stored physically as
`UNKNOWN` and exposed as `UNCOMPARABLE` by services and reports.

Reports are deterministic and use only persisted official sources, confirmed
facts, and comparison records:

- `BASELINE_REPORT` describes positioning, features, plans, prices, public
  sales status, product updates, evidence coverage, and limitations;
- `CHANGE_TRACKING_REPORT` describes added, removed, modified, unchanged, and
  uncomparable facts, grouped change areas, evidence, risks, and run IDs.

Possible-impact text is emitted only for confirmed changes, is explicitly
labelled `INFERENCE`, and records the triggering `fact_key` and change type.
It never becomes a confirmed product fact or an unsupported strategy
recommendation.

Both readable Markdown and structured JSON are stored in the existing
`reports` table (`summary_json` contains title, JSON content, prompt/generator
metadata, and counts).

Use the project Python 3.12 interpreter for the offline fixture scenarios:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --verbose
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --fixture-scenario unchanged
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --fixture-scenario price_changed
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --fixture-scenario feature_added
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --fixture-scenario feature_removed
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Notion --agent-provider fixture --fixture-scenario page_failure
```

View and export reports:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report show --run-id 3
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report show --competitor Notion --latest
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report export --run-id 3 --format markdown --output reports/notion_run_3.md
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report export --run-id 3 --format json --output reports/notion_run_3.json
```

Fixture scenarios cover Notion and Feishu baselines/unchanged refreshes,
Notion price modification, feature addition/removal, and a failed pricing page
that produces `UNCOMPARABLE`.

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
fixture provider, and Agent tests use `FixtureAgentProvider`; neither calls a
model API or incurs model charges. This keeps ranking, timeout, redirect,
content-size, JavaScript-shell, validation, discovery, extraction, evidence,
state, and tool-call results reproducible.

## Not implemented yet

- real Agent and fact-extraction model adapters
- frontend, scheduling, Playwright, RAG, and vector databases
- notifications and production search orchestration
- PDF, Word, and PowerPoint report export
- a real search-provider adapter; future configuration requires
  `SEARCH_PROVIDER`, `SEARCH_API_KEY`, and `SEARCH_ENDPOINT`
- a real model fact-extraction adapter; future configuration requires
  `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_ENDPOINT`
- a real AgentProvider adapter; future configuration requires
  `AGENT_PROVIDER`, `AGENT_API_KEY`, `AGENT_MODEL`, and `AGENT_ENDPOINT`
