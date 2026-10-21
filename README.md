# Universal Competitive Intelligence Agent

## Stage 9.2.1: standalone natural-language task understanding

`python -m competitive_intel.cli interpret "分析豆包"` previews a structured
`AnalysisTaskSpec`, without creating a run or accessing MySQL. The offline Fixture
grammar is a labelled demonstrator; the real `openai_compatible` adapter interprets
free language through one schema-constrained model request, followed by server
validation. Real CLI use requires both `--provider openai_compatible --allow-paid`.
No paid request was made during development. The same preview is available through
`POST /api/analyst/interpret` with `{"text":"比较豆包和 Kimi","provider":"fixture"}`.
Explicitly selecting `openai_compatible` on that endpoint authorizes one model call;
configuration alone never switches a Fixture request to a paid provider.

This stage does not discover competitors, execute comparisons, generate reports,
or connect free-language execution to Chat-first. Existing shortcuts remain, with
guards against launching a whole analysis sentence as a product name. See
[Stage 9.2.1 scope, validation and migration blocker](docs/stage-9.2.1-task-understanding.md).
Production migration 003 remains unapplied, pending verified restore and separate
user approval. Stage 9.1 full real end-to-end reliability acceptance remains open.

## Stage 9.1.4: conservative partial results

`PARTIAL_SUCCESS` publishes an independent `PARTIAL_EVIDENCE` report only when
uncontested, evidence-validated facts exist. Observations stay PENDING; partial
runs never replace a formal baseline or generate Changes/Signals. Report,
critical audit and terminal status are committed atomically. See
[migration, recovery and MVP/reliability boundaries](docs/stage-9.1.4-closeout.md).
Apply migration `003_partial_success.sql` through the existing initializer before
deploying this version. A passing offline suite is **not** full Notion end-to-end
reliability acceptance.

## Stage 9.1: real LLM fact extraction

### Stage 9.1.2: reliability and baseline integrity

Connection failures audit typed causes and the request phase (connect/headers,
response-body read, or decode), not exception messages. DNS, TCP refusal, SSL,
connect/read timeout, remote disconnect and protocol errors are distinguished
only when their actual exception types support that conclusion. Generic client
errors remain unspecified. No connection/timeout retries are introduced; the
existing bounded HTTP 429/5xx retry policy is unchanged. One requests Session is
reused, and responses are closed by their context manager. Old audits cannot
retroactively establish the precise cause of run #34.

Version-2 page caches store the entire validated fact set in the existing tool
audit JSON, independently of new-row counts. Snapshot duplicates are checked for
canonical equality and receive observations; conflicting values fail closed.
Cross-source duplicates retain separate complete page caches. Empty success can
be cached, but is not proof of absence. Cache replay checks the source URL,
snapshot/source relation and exact cleaned content, then runs evidence checks
again before saving observations. PARTIAL_ERROR and failed runs cannot supply
complete caches. Old observation-only caches are deliberately not reused.

Only a completed full AgentRunner run with a versioned `baseline_integrity`
marker, complete successful source coverage, a report and finalized observations
can be selected as a formal comparison baseline. Repository selection rechecks
CONFIRMED facts, non-PENDING observations and successful run-owned snapshots.
Legacy and standalone smoke runs without this provenance are excluded, not
deleted. With only smoke history, the next formal run starts a new baseline.

State policy: SUCCEEDED pages may contribute validated observations. NO_FACTS is
a legal non-error, but prevents full baseline replacement/eligibility; absence
is unknown. PARTIAL_ERROR retains only validated facts with PENDING observations
and stops real runs before comparison/reporting. Transport/schema/evidence
errors, missing successful snapshots or incomplete extraction also fail the real
run. Rejected facts are never saved. No PARTIAL_SUCCESS reporting is implemented;
any future extension must disclose missing sources and exclude them from removal
detection. Existing incomplete fixture warning runs can still be displayed but
cannot replace a complete formal baseline.

Pricing extraction keeps raw `plan_name` grounded in a contiguous quote. The
provider derives `normalized_plan_name` with the existing server `slug()` only
when the model's name is deterministically equivalent; a different plan is still
rejected. `SERVER_PLAN_SLUG` audits retain the bounded model name, source name,
and derived value. Homepage audience lists must not infer teams from companies.

Price period and payment commitment are separate: `/month` supports `MONTH`,
while `paid annually` / `paid monthly` support `ANNUAL_BILLING` /
`MONTHLY_BILLING`. No schema change is made. There is no DOMAIN or per-N-credits
unit enum: those dimensions remain unknown and the original quantity stays in
evidence. `monthly credits` alone is not a billing schedule. A bare dollar sign
does not establish USD. Quotes must include the price subject and amount in one
continuous source span, including any intervening text. Null fields use the
existing audited UNKNOWN adapter; they do not mean a free or flat-rate product.

The Chat-first home and Developer launcher now offer three explicit modes:
Fixture (offline demonstration), Serper + real fetching with extraction skipped,
and Serper + `openai_compatible` evidence-first extraction. The controlled Agent
itself is unchanged; this is not a free-form conversational LLM Agent.

Configure the existing **untracked local `.env`**, never source files:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your-local-key
LLM_MODEL=your-structured-output-model
LLM_ENDPOINT=https://api.openai.com/v1/chat/completions
LLM_TIMEOUT_SECONDS=45
LLM_MAX_INPUT_CHARACTERS=30000
LLM_MAX_OUTPUT_TOKENS=6000
LLM_MAX_RETRIES=1
LLM_MAX_CALLS=8
```

`LLM_ENDPOINT` accepts an HTTPS base URL (for example `https://api.deepseek.com`)
or a full Chat Completions URL. The adapter appends `/chat/completions` only when
it is missing, preserving an optional `/v1` prefix. It sends `json_object` and
`max_tokens`, with the exact JSON Schema in the system prompt. DeepSeek requests
disable thinking to bound extraction cost. Strict server-side schema, field,
snapshot and evidence validation remain mandatory; there is no Fixture fallback.
No additional SDK dependency was added. The web
request's `fact_provider` explicitly selects the mode; setting `LLM_PROVIDER`
alone never changes an existing Fixture request into a paid request. Configuration
is loaded on server startup, so restart the server after editing `.env`.
JSON mode follows the [DeepSeek Chat Completions interface](https://api-docs.deepseek.com/api/create-chat-completion/).

Only successful, cleaned snapshots are submitted. The adapter has no tools,
filesystem access, or database access. It sends webpage text as untrusted data,
rejects overlong input rather than silently extracting a truncated page, caps
responses at 1 MB, disables redirects, and uses bounded connection/read timeouts.
Retries apply only to HTTP 429/5xx; timeouts are not retried because they may already
have incurred cost. `LLM_MAX_CALLS` includes retry attempts across a single run.
Actual returned token counts, elapsed milliseconds, model, attempt count and safe
error codes appear in Developer audit. Missing usage is unknown, not zero or an
estimated monetary cost. Provider bodies, request headers and credentials are not
logged. No raw provider response is persisted.
HTTP audit includes status, host/path, model, elapsed time and allowlisted provider
error type/code/message. Unrecognized error prose is withheld because a provider
could echo credentials or page content. No headers or error bodies are persisted.
Evidence rejection audits include zero-based fact index, field name, bounded
value (160 characters), bounded quote (240 characters), source/snapshot IDs,
failure type and matching strategy. At most 50 field diagnostics are retained;
credential-shaped text is redacted. These are untrusted excerpts, not confirmed
facts. Rejection of any field rejects that entire fact, never just the field;
independently valid facts on the page may be saved. Diagnostics do not relax
matching or authorize saving unsupported facts.
Feature classification alone recognizes explicit case-insensitive whole-word
aliases: Docs/Doc/Document/Documents → DOCUMENTS and
Meeting/Meetings/Meeting Notes/AI Meeting Notes → MEETINGS. Matching uses the
existing whitespace/case-normalized evidence; no stemming, semantic inference or
LLM judgment is used. Descriptions, prices, numbers, source/snapshot bindings and
verbatim evidence checks are unchanged. The versioned extraction policy prevents
reuse of results validated under a different policy.
The conservative LLM contract permits null FEATURE status/category when evidence
does not explicitly support them. The unchanged legacy domain schema requires
enums, so the adapter maps only null to UNKNOWN (status) / OTHER (unclassified).
Each such mapping is audited with the original null. Non-null unsupported claims
still reject the fact; they are never silently converted to unknown. Required
descriptions and all other grounding checks are unchanged. Website presence does
not establish AVAILABLE, and Databases does not establish PROJECT_MANAGEMENT.

For a bounded single-page smoke test, call `FactExtractionService.extract` with
`source_id` set to an existing verified source of the named competitor. It reads
only that source's latest successful cleaned snapshot. Set provider `max_calls=1`,
`max_retries=0`; do not launch `smoke_real_llm.py` (which runs the full Agent).
This extraction-only path saves validated facts and an audit run, without calling
change detection, signal generation, or report generation.

All accepted descriptive fields must be verbatim substrings of a contiguous
evidence excerpt in the supplied snapshot. Source URLs are bound by the server,
not generated by the model; the returned snapshot ID must match. Schema, enum,
price and existing evidence checks run server-side. Missing evidence, invented
descriptions, invalid JSON, refusal, output truncation and empty input fail closed.
Any real page/fact error stops downstream comparison/report
generation for that run; any already-saved observations are not activated as a
successful baseline. A failed run never means that competitors have not changed.

The adapter deliberately favors precision over recall: free-form summaries,
translated descriptions, non-ISO update dates and ambiguous currency symbols
may be rejected. Quotes can establish textual support, not independently prove a
publisher's claim. Inspect the evidence before relying on it.

For identical source ID + clean text + model/endpoint + extraction policy, the
service reuses facts from a completed, audited extraction and records fresh
observations against the new snapshot. Reuse has zero model attempts and unknown/
absent token usage, not invented usage. Different input or policy invokes extraction
again. Fact keys and the existing comparison algorithm remain unchanged. Switching
between Fixture and real extraction creates a new baseline rather than reporting
differences between demonstration and real facts. Original historical runs remain
available in Developer. There are no database migrations for this stage.

### Stage 9.1.1: page-aware contracts

Existing verified `source_type`, source URL, snapshot ID and cleaned content are
sufficient to select the contract; no schema migration or inferred URL typing is
used. HOMEPAGE permits explicit positioning/features; FEATURES only FEATURE;
PRICING only PLAN/PRICE; CHANGELOG only PRODUCT_UPDATE. Dedicated instructions
require one contiguous evidence block for all non-null values in each fact.
Pricing never derives USD from `$` or billing periods from layout. Releases use
null for dates unless an ISO date is explicitly quoted, and do not infer status,
plans or feature categories. Nullable enum inputs use audited existing UNKNOWN
sentinels, not inferred values. Existing field grounding is unchanged.

Per-page audit records returned facts, confirmed facts, rejected facts, field
diagnostics, skipped duplicates and page status:

- `SUCCEEDED`: all accepted items validated; exact canonical duplicates may be skipped.
- `NO_FACTS`: valid empty array, not proof that facts do not exist. Not an error.
- `PARTIAL_ERROR`: valid facts saved, other facts rejected; the error is retained.
- `FAILED`: transport/envelope/schema/evidence failure with no accepted facts.

Envelope errors reject the response. Item schema/evidence errors reject only that
item. Identical verified identity + canonical value keeps the first occurrence;
conflicting values with the same identity are errors, not silently merged.
All values of a conflicting identity are rejected (neither first nor last wins).
Bounded conflict audit pairs contain identity, type, indices, original/canonical
values and evidence plus source/snapshot IDs. Old audits cannot reconstruct values
that were not retained. Homepage prompts allow at most one primary POSITIONING
fact to match the unchanged `positioning.primary` identity. Quote instructions
explicitly retain intervening boilerplate/video placeholders; deleting such text
would splice discontinuous evidence. Existing Unicode/whitespace normalization
is unchanged; no fuzzy matching or automatic quote repair is performed.
Partial-error facts remain pending rather than becoming an active baseline;
partial/error pages cannot supply cached results or reach comparison/reporting.
NO_FACTS does not trigger baseline replacement. Existing history comparison treats
sources with no observations as unknown coverage rather than confirmed removals.

Cache identity composition is deliberately unchanged in this stage, including
`max_output_tokens`; the policy version is bumped for the new contract. An output
budget is a resource constraint rather than intrinsic fact semantics, but removing
it safely requires a complete-result policy (including max_facts and page/schema
scope) and tests excluding truncated/partial results. That redesign is deferred.

Real validation is explicitly limited to one saved FEATURES, one PRICING and one
CHANGELOG source, each through `FactExtractionService.extract(source_id=...)` with
`max_calls=1`, `max_retries=0`. Ordinary tests use mocked responses and disposable
MySQL only. Never use the full-run smoke script for this three-page validation.

### Tests and explicit paid smoke

Ordinary tests mock the HTTPS model response; integration tests use the existing
disposable MySQL `_test` database, never a paid API:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m pytest -p no:cacheprovider --basetemp=.pytest_stage91_verify
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m pip check
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m compileall -q src scripts tests
```

After configuring Serper and the LLM locally, explicitly authorize a paid smoke:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" scripts/smoke_real_llm.py --allow-paid --competitor Notion --runs 2 --max-calls-per-run 4
```

This writes to the configured application database and may make at most eight
model calls in total (two runs, four per run, no retries). It stops on the first
unsuccessful run and never substitutes Fixture data. A four-call cap can produce
an explicit failure if more pages require extraction. Output provides run IDs,
report IDs, counts and Developer audit links. Inspect both runs' evidence and
change counts; matching snapshots should reuse the original facts. If credentials
are missing it prints `NOT_RUN` before any paid request or database write.

Real Notion end-to-end acceptance requires this explicit smoke; passing mocked
tests is not evidence that a particular remote model/service works. The legacy
CLI and `/workspace` launcher retain their previous fixture/skip-only behavior;
use Home, Developer, or the smoke script for the real LLM flow.

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

## Phase 6.5 real-source smoke mode

`SerperSearchProvider` is a bounded implementation of the existing
`SearchProvider` interface. It sends generated queries to
`https://google.serper.dev/search`, parses usable webpage candidates from
`organic`, `knowledgeGraph`, and `answerBox`, and leaves all official-source
decisions to the existing deterministic validator.

Configuration is read only from `.env` or process environment:

```text
SEARCH_PROVIDER=serper
SEARCH_API_KEY=<local secret>
SEARCH_ENDPOINT=https://google.serper.dev/search
```

Missing credentials are a configuration error; there is no fixture fallback.
The provider uses separate connection/read timeouts, a response-size bound,
result limit, and at most two attempts. Authentication errors are not retried.
Timeouts, HTTP 429, and selected HTTP 5xx responses have bounded retries.
Credentials and provider response bodies are not placed in errors or audit
records.

Real Serper mode uses `RequestsFetcher`, not fixture HTML. Because this phase
does not include a real fact-extraction provider, fixture facts are
automatically blocked and extraction is recorded as:

```text
fact_extraction_status=SKIPPED
fact_extraction_reason=REAL_CONTENT_REQUIRES_REAL_FACT_PROVIDER
```

Run the limited smoke flow:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli analyze Linear --search-provider serper --agent-provider fixture --fact-provider fixture --skip-fact-extraction --verbose
```

Official-domain disambiguation is deterministic and auditable. Candidate URLs
are grouped by their Public Suffix List registrable domain (eTLD+1) using
`tldextract` with its bundled snapshot and runtime suffix downloads disabled.
The score combines result count, query-type coverage, brand matches, homepage
evidence, redirects, canonical/title/`og:site_name` metadata, typical official
paths, and supporting subdomains. Known social, job, review, media, aggregator,
store, and short-link domains are hard rejected.

Automatic verification requires all of the following: no hard rejection,
brand support in both search and page metadata, homepage evidence, a score of
at least `8.0`, and a lead of at least `2.0` over the next eligible
registrable domain. Otherwise the result remains `PENDING_CONFIRMATION`.
Only the top three domain representatives receive lightweight page
validation. The discovery tool returns a bounded `domain_evidence` audit list;
search rank contributes no verification points.

The summary explicitly reports `search_provider=serper`, `fetch_mode=real`,
`agent_provider=fixture`, and `fact_provider=fixture`. This is source and
snapshot validation only; it is not a production search integration or a
real-model analysis.

## Phase 7 local FastAPI console

Phase 7 adds a loopback-only FastAPI application, JSON API, Jinja2 pages, and
native CSS/JavaScript. It reuses the existing services, controlled
`AgentRunner`, `Persistence`, repositories, MySQL schema, fixture providers,
and Serper integration. No Node.js or CDN is required.

Initialize the existing database and start the local service:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" scripts/init_database.py --database-exists
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.web
```

The terminal prints:

```text
Competitive Intelligence Agent is running
Open: http://127.0.0.1:8000
```

Open `http://127.0.0.1:8000`. The server deliberately binds only to
`127.0.0.1`, not `0.0.0.0`.

The JSON API provides:

- `GET /api/health`
- `GET /api/competitors` and `GET /api/competitors/{id}`
- `GET /api/competitors/{id}/sources`
- `GET /api/competitors/{id}/facts`
- `GET /api/competitors/{id}/changes`
- `GET /api/competitors/{id}/reports`
- `GET /api/reports/{id}`
- `GET /api/reports/{id}/download?format=markdown`
- `GET /api/runs` and `GET /api/runs/{id}`
- `GET /api/runs/{id}/events`
- `GET /api/runs/{id}/tool-calls`
- `GET /api/workspace/runs/{id}`
- `POST /api/analyses`

HTML pages are `/`, `/workspace`, `/dashboard`, `/competitors/{id}`,
`/runs/{id}`, and `/reports/{id}`.
The run page polls the run and event APIs once per second and stops on
`COMPLETED`, `COMPLETED_WITH_WARNINGS`, or `FAILED`, with a ten-minute client
limit. Internal states are translated into readable Chinese labels.

Analysis requests run in a fixed-size in-process thread pool. The default
global limit is two and can be reduced or increased up to four with
`WEB_MAX_CONCURRENT_ANALYSES`. Only one active analysis is allowed for each
normalized competitor; a second request receives
`ANALYSIS_ALREADY_RUNNING`. This executor is intended for a single local
process and is not a distributed queue or suitable for multi-instance
production deployment.

Fixture search, fetching, fact extraction, and Agent tool selection remain the
default demonstration path. Selecting Serper performs real search and real
HTTP fetching and requires `SEARCH_API_KEY` in the local ignored `.env`.
Because a real fact provider is not implemented, Serper requests must set
`skip_fact_extraction=true`; the UI enforces this and clearly displays the
skip reason. Fixture facts are never applied to real page content.

The API returns bounded summaries only. It does not expose database
credentials, API keys, full captured HTML, unlimited cleaned page text, raw
model output, stack traces, arbitrary SQL, or arbitrary URL-fetch endpoints.
Templates use automatic escaping, browser rendering uses `textContent`, report
filenames are sanitized, provider/scenario values are allowlisted, and
competitor names and tool budgets are bounded. The console has no login and
must remain local.

## Phase 8 Agent workspace

The root page is now a three-column competitive-intelligence workspace. The
previous Phase 7 management view remains available at `/dashboard`.

- The left column lists recent analysis conversations and competitor profiles.
  A conversation is an existing `agent_runs` record; Phase 8 does not add a
  conversation table or a second task system.
- The center column replays a deterministic message stream and structured
  source, fetch, fact, change, and report cards. Messages are derived only from
  the original input, `stage_events`, `tool_calls`, run summary, facts,
  changes, and report data. No model invents chat responses.
- The right column displays the state timeline, bounded tool-call summaries,
  source evidence, providers, timing, and run metadata. Selecting a historical
  conversation performs a read-only replay and never reruns the Agent.

The command box is a controlled intent interface, not free-form chat. It
recognizes analysis or refresh commands, latest-report and recent-change
queries, numeric run opening, and the explanation for skipped fact extraction.
Unrecognized input receives an explicit capability-boundary message. New
analysis requests continue to use the existing `POST /api/analyses` endpoint.

Progress is mapped deterministically from the controlled state machine and is
monotonic; it is not guessed from elapsed time. Active runs poll once per
second and stop at a terminal state or after the existing ten-minute client
limit. On narrow screens the execution trace collapses into a side panel.

The workspace identifies the current Agent as the controlled
`FixtureAgentProvider`. Serper can perform real search and real HTTP fetching,
but real fact extraction remains unavailable and is visibly skipped. This
interface is not a real natural-language Agent and makes no claim that a model
autonomously understood arbitrary instructions.

CLI analysis exit codes are:

- `0`: `COMPLETED`
- `2`: `COMPLETED_WITH_WARNINGS`
- `1`: `FAILED`
- `64`: invalid input or configuration

Report export supports exactly one selector:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report export --report-id 1 --format markdown --output report.md
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report export --run-id 1 --format json --output report.json
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.cli report export --competitor Notion --latest --format markdown --output notion.md
```

Troubleshooting: check `/api/health`, verify MySQL is running and `.env`
contains the local database settings, and confirm the selected disposable test
database ends in `_test` when running pytest. Serper mode additionally requires
a valid local key. A `COMPLETED_WITH_WARNINGS` run is successful with explicit
limitations, not a failed run.

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

## Phase 8.5 — Competitive Intelligence Command Center

The product navigation is now intelligence-first, with a persistent desktop
sidebar and a compact navigation on narrow screens:

| Route | Product view |
| --- | --- |
| `/` | Command Center: metrics, Needs Attention, recent signals, competitor overview |
| `/signals` | Paginated changes, filtered by competitor/category/type/date/verification status |
| `/analyst` | Analyst Preview: deterministic commands only |
| `/competitors` | Competitor library |
| `/competitors/{id}` | Overview, Signals, Pricing, Features, Sources, History, Reports |
| `/reports` | Report list, run status, change counts, existing Markdown downloads |
| `/developer` | Existing developer dashboard, providers, system health and runs |
| `/developer/runs/{id}` | Phase-eight three-column workspace replay for that run |

`/workspace`, `/dashboard`, `/runs/{id}`, and `/reports/{id}` remain accessible.
The original workspace tests remain; their homepage assertion now uses
`/workspace`, since `/` is intentionally the product homepage.

### Data definitions and boundaries

- Signals are a **read-only projection of `changes`**, not another table.
  `UNKNOWN` is presented as `UNCOMPARABLE`; unchanged records appear only in
  History. Pricing includes PRICE/PLAN, Product includes PRODUCT_UPDATE.
- The 30-day metric uses UTC database time. Recent Signals shows latest
  recorded signals even when older than 30 days, with explicit dates.
- Needs Attention counts latest-run/current-source items, not individual
  warnings. Latest failed/warning runs, pending or missing verified sources,
  latest uncomparable changes and missing generated reports are deterministic
  reasons. Unlinked failed attempts are associated with a later registered
  competitor by its existing normalized name, avoiding duplicate old alerts.
  These are derived review items, not a new dismiss/acknowledgement workflow.
- Last successful check is the latest completed run time (including a run
  completed with warnings); it does not claim every source succeeded.
- Signal status is `confirmed` or `needs_review` from stored verification and
  comparison status. No strategic severity or model-written impact is invented.
- Fact cards contain only current, confirmed FACT records from fact_versions
  and product_facts. Missing facts show **No verified facts available yet.**
  Existing fixture records remain demo data; nothing backfills real competitors.
- Developer derives its view from runs/events/tool_calls. Agent state machine,
  comparison, report generation, source verification and database schema are
  unchanged. New SQL is only in the existing DashboardRepository; API handlers
  own `Persistence.transaction()`. Presenters do not access the database.

Read-only APIs added: `/api/command-center`, `/api/signals`,
`/api/competitors/{id}/intelligence`, `/api/reports`, `/api/analyst/command`.
List queries have bounded SQL pagination (limit <= 100, offset <= 10000).
Profile facts support `fact_category=Pricing|Feature` before pagination;
sources, reports, current facts and history have separate page controls.
The competitor filter lists up to 100 competitors for this local MVP.
DTOs allow-list fields and limit evidence to 500 characters. Raw HTML,
configuration, secrets and stack traces are not projected. Evidence URLs strip
userinfo/query/fragment, allow only HTTP(S), and dynamic content uses textContent,
not innerHTML. Original stored URLs/evidence are not modified.

Analyst supports `分析 <name>`, `重新分析 <name>`, `查看 <name> 最新报告`,
`查看 <name> 最近变化`, `打开运行 <id>`, `为什么本次没有提取事实`,
`最近有哪些变化`, `查看最近 signals`, `查看 <name> 来源`, and
`查看 <name> 当前价格`. Analysis first asks for an explicit real-search or
offline-demo mode, then uses the existing `POST /api/analyses` task manager.
Unsupported commands explicitly say the natural-language Analyst is not connected.
Real AgentProvider and real FactExtractionProvider are **not connected**.
Real-source runs continue to skip extraction; no LLM calls were added.

### Local verification (Python 3.12 environment)

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m competitive_intel.web
# In another terminal:
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m pip check
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m pytest -p no:cacheprovider --basetemp=.pytest_tmp_stage85
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m compileall -q src scripts tests
git diff --check
```

Open http://127.0.0.1:8000/. Verify existing Notion pricing/history/reports,
Linear warning status and empty verified facts, Analyst controlled queries,
and historical Developer tool traces. No live search is needed for this UI
acceptance. Tests use the existing disposable local MySQL `_test` database,
offline fixtures and mocks, never public internet requests. Only remove the
resolved project-local `.pytest_tmp_stage85` after tests; old ACL-restricted
pytest directories do not need to be touched.

## Stage 8.7 — Chat-first homepage

Open **http://127.0.0.1:8000/** after starting the existing web service.
The Editorial welcome screen now has a real multiline composer. Sending a
message replaces the welcome screen with a conversation, not an appended demo.
`/analyst` uses the same controller and existing `/api/analyst/command` grammar.
The former homepage and all its live metrics remain at `/command-center`.
`/signals`, `/competitors`, `/reports`, `/developer`, and run/report detail
routes are preserved. No schema, repository, AgentRunner, extraction, comparison,
or report-generation changes were made in this phase.

Supported examples:

- `Notion` or `帮我分析 Notion 这个产品。`
- `查看 Linear 最近发生了哪些变化。`
- `查看 Notion 当前价格` / `查看 Notion 来源` / `查看 Notion 最新报告`
- `最近有哪些变化` / `打开运行 123` / `为什么本次没有提取事实`

Analysis requires an explicit in-chat confirmation of **real Serper search**
or **Fixture offline demonstration**. The existing `POST /api/analyses` starts
the actual controlled runner; no Developer form or simulated task is used.
Real mode skips fact extraction. Fixture mode writes fixed demo records and
must not be interpreted as current competitive research. Existing-record queries
also warn that the database can contain demo records. No external search is
started by loading a page, choosing a shortcut, or replaying a conversation.

Run cards poll the existing workspace projection, show only recorded stages and
tools, and link to reports, competitor sources, and the Developer audit trail.
Polling is bounded to 601 reads; failure or exhaustion offers manual retry and
never claims the task completed. An ambiguous start error asks the user to check
History before retrying, rather than automatically creating another run.

`/history` distinguishes browser-local conversations from database run history.
The browser retains up to 30 conversations of 60 requests each in localStorage
(product questions, mode, and run IDs; no copied evidence or API credentials).
Do not type secrets. These conversations are not account-synced. Refresh/back/
forward restore the selected conversation; saved run IDs are read, never POSTed
again. Read-only queries are refreshed from current records, so this is not an
immutable transcript. Clearing browser storage removes local conversation
history but not database runs. If storage is unavailable, the UI warns and
database run history remains accessible.

The user may submit multiple independent requests in one conversation. Contextual
pronouns, open-ended multi-turn reasoning, cross-competitor natural-language
comparison, and real LLM providers are **not implemented**. Developer's existing
audit tools remain available; its deep visual redesign and other page migrations
are intentionally deferred until the homepage is accepted.

Regression command (offline fixtures plus disposable local MySQL integration):

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" -m pytest -p no:cacheprovider --basetemp=.pytest_tmp_stage87
```

Browser acceptance: send a supported request; explicitly choose Fixture only on
a disposable test database; check real stage/tool records, report/source links,
refresh and back/forward without new runs; test an unknown product, unsupported
comparison, failed run, and the six sidebar destinations. Keep the production
database free of new acceptance-test fixture facts.

## Editorial data-page migration

Signals, Competitors (including profiles), Reports (including reading pages),
and Developer now share a scoped warm-paper / sage editorial stylesheet.
The Chat-first homepage and its runner interactions are unchanged.

- `/developer` prioritizes paginated real run history (20 per page). Advanced
  launch settings and competitor links remain available in disclosure panels.
- `/developer/runs/{id}` and the legacy `/runs/{id}` show the same execution
  audit: recorded timeline, expandable tool inputs/outputs, provider settings,
  warnings/errors, evidence, changes and report links. `/workspace` remains
  available as the original three-column interface.
- Audit data comes from the existing `/api/workspace/runs/{id}` projection;
  API limits and sanitization still apply. Current source records are explicitly
  distinguished from run-specific facts. Older runs lacking provider metadata
  are not assumed to be real research merely because an API default is present.
- Signals filtering, profile tabs, report reading/download and all API,
  repository, schema and AgentRunner contracts are unchanged. No mock data was
  introduced. The new audit controller only performs read-only requests.

Run regression tests using the project Python 3.12 interpreter and
`-m pytest -p no:cacheprovider --basetemp=.pytest_tmp_ui`. Browser checks cover
real history, expanded tools, filtered signals, reports, failed runs and narrow
viewports. This phase does not start Stage 9.

## Not implemented yet

- real natural-language AgentProvider and real fact-extraction model adapters
- production hardening for Serper and real webpage collection
- authentication, public/cloud or multi-instance deployment
- distributed task queues, scheduling, Playwright, RAG, and vector databases
- notifications and production search orchestration
- PDF, Word, and PowerPoint report export
- a real model fact-extraction adapter; future configuration requires
  `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_ENDPOINT`
- a real AgentProvider adapter; future configuration requires
  `AGENT_PROVIDER`, `AGENT_API_KEY`, `AGENT_MODEL`, and `AGENT_ENDPOINT`
