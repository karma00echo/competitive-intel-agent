# Stage 9.2.1 — Task understanding, without analysis execution

## Scope

One structured task interpretation is available through the existing CLI and web
application. No additional Agent, AgentRunner execution branch, database schema,
fact extraction chain, EvidenceChecker policy, report type, or Chat-first layout
is introduced in this substage. Stage 9.2.2 is not started.

The real adapter sends the original request plus a versioned task-understanding
prompt and JSON schema to the existing configured OpenAI-compatible endpoint.
It does not map a finite set of phrases to analysis commands. It has no search,
tools, filesystem or database access. Model output is untrusted: strict schema,
bounded fields, request-bound product names, unique dimensions/competitors and
consistent task status are validated before returning a preview.

Fixture is deliberately a limited offline grammar, not a substitute for real
language understanding. Unknown grammar asks for clarification rather than
silently invoking a model. Mock HTTP tests cover a longer free-language request
through the actual production adapter. These tests do not establish live model
understanding accuracy. No paid DeepSeek request or full Doubao analysis was made.

## Running the preview

```powershell
python -X utf8 -m competitive_intel.cli interpret "分析豆包"
python -X utf8 -m competitive_intel.cli interpret "比较豆包和 Kimi"
python -X utf8 -m competitive_intel.cli interpret "分析豆包的核心功能和定价策略"
python -X utf8 -m competitive_intel.cli interpret "分析它"
```

CLI exits: 0 for READY, 2 for clarification/unsupported, 1 for provider/validation
failure, 64 for invalid input/configuration. The Fixture CLI does not load local
credentials or construct a Database. Optional real interpretation requires
`--provider openai_compatible --allow-paid`; do not run it without paid-call approval.

`POST /api/analyst/interpret` accepts a required `text` (1–1000 characters) and
optional `provider` (`fixture` by default, or explicitly `openai_compatible`).
It returns the normal API envelope, whose `data.status` must be checked separately
from HTTP transport success. `execution_started` is always false. The endpoint
does not create a run, report, snapshot, observation or any other database row.

The existing read-only `/api/analyst/command` and simple product shortcuts remain
compatible. Complex analysis sentences are blocked from becoming a single product
name in the legacy executor. Chat-first task execution is deferred to 9.2.4.

## Contract

`AnalysisTaskSpec` carries status, target, intent, explicit competitors, dimensions,
output format, automatic discovery preference, assumptions and clarification.
READY means a request is interpretable, not that the product's identity or any
facts have been verified. No URLs are required. Names are copied from the input;
automatic candidate names must not be invented during interpretation.

Default dimensions are positioning, target_users, core_features, ai_capabilities,
pricing and differentiation. Formats are report/table/brief. Explicit competitors
disable discovery; single-product requests disable both competitors and discovery.
More than two requested competitors, unresolved pronouns, unsupported dimensions,
or contradictory scope require clarification rather than silent truncation.
The current preview is stateless; clarification is resolved by a new self-contained
request. Product identity verification belongs to subsequent source validation.

Examples executed with Fixture:

| Input | Target | Competitors | Dimensions | Result |
| --- | --- | --- | --- | --- |
| 分析豆包 | 豆包 | none, later discovery | six defaults | READY |
| 比较豆包和 Kimi | 豆包 | Kimi | six defaults | READY / comparison |
| 分析豆包的核心功能和定价策略 | 豆包 | none, later discovery | core_features, pricing | READY |
| 只分析豆包，不比较其他产品 | 豆包 | none, discovery disabled | six defaults | READY / product_analysis |
| 分析它 | unresolved | none | pending | NEEDS_CLARIFICATION |

## Cost and failure boundary

Each real preview performs at most one HTTP model attempt, with no retries and no
Fixture fallback. Input is bounded to 1000 characters and the configured input
limit; output is capped at the lower of 1500 tokens and the configured output
limit. Zero configured calls/output budget rejects before HTTP. HTTPS endpoints
must not contain credentials, query strings or fragments; redirects are disabled.
Response bytes are capped at 64,000; refusal, tool calls, incomplete generation,
invalid JSON/schema, secret echoes and invented product names fail closed.

The returned audit includes provider/model, prompt version, attempts, elapsed time
and valid provider-reported token usage. Missing usage remains unknown. No raw
provider response, credential or arbitrary provider exception is returned or
persisted. The global cross-phase request/Token ledger belongs to 9.2.2; it is not
claimed implemented by this single-request bound.

## Production migration preparation — blocked, not applied

The formal database still contains only migrations 001/002 and the old ENUMs.
Preflight found zero RUNNING tasks and no Python application process in the process
inventory. Application tables were held under READ locks during the full logical
dump; locks were released in a finally block. All table inventories, row counts,
row hashes and DDL hashes matched before/after that backup operation.

The dump includes schema/data, triggers, routines and events; it was written outside
the repository in a private, inheritance-disabled Windows ACL directory. No backup,
credential or captured data is included in this commit. Local operator metadata is
in `verification-pending.json` beside the dump.

- Backup directory: `%LOCALAPPDATA%/CompetitiveIntelBackups/20261021_111446/`.
- Dump: `competitive_intel.sql`, 25,916,101 bytes.
- SHA-256: `01d7612968d1689db9d630e4b4ea9fbb02aaeb51b7353661847b4fdad70b8210`.
- Intended isolated database: `competitive_intel_restore_20261021_111446_test`.
- Blocker: current configured account receives MySQL 1044 creating that database.
- **Restore has NOT been verified; production migration 003 has NOT been run.**

An administrator must create the dedicated restore database and configure a local
migration account with permission to restore/inspect it. Do not paste credentials
into chat, source files or command arguments. Do not restore into the ordinary
integration-test database. After restoration, compare every table's schema and
row content and check foreign-key relationships; rehearse 003 on the isolated
copy. Repeat the formal-source preflight and take a fresh verified backup if writes
have occurred. Report successful verification and obtain separate user confirmation
before running 003 on the formal database. Keep historical data and ENUM ordering.

The formal database was rechecked after preparation: 35 runs (19 COMPLETED,
16 FAILED), eight reports (one BASELINE, seven CHANGE_TRACKING), and unchanged
001/002 migration records/ENUM definitions. No formal data writes or migrations
were performed. Stage 9.2.1 code can be validated independently; deployment that
uses 9.1.4 partial publication must wait for approved production migration.

## Validation and remaining gates

Tests cover offline examples, negative scope, clarification, model HTTP payloads,
strict schema rejection, invented product rejection, missing usage, bounded calls,
transport failures, input limits, CLI paid opt-in, standalone API behavior without
Persistence/TaskManager, and existing shortcut compatibility. All model transport
tests are mocked. Full regression uses only the disposable configured `_test` DB.

Final validation on 2026-10-21 with Python 3.12.13: **431 passed**, including 58 new
task-understanding cases; one pre-existing Starlette/httpx deprecation warning.
`pip check` found no broken requirements, and `git diff --check` passed. On Windows,
the sandbox blocked TestClient's event-loop socketpair; the complete offline suite
passed outside the sandbox. No paid API call was needed.

Stage 9.1 full real end-to-end reliability acceptance remains incomplete. Before
9.2.2, resolve the restoration/migration gate and obtain the user's next-stage
confirmation. Future competitive-analysis report ENUM additions require their own
migration/testing proposal and approval; none are included here.
