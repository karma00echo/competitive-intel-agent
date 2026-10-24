# Natural-language workflow: entrypoint and acceptance gates

This implementation connects the production services. Offline tests do not prove
live website reliability, model accuracy or a completed Agent MVP. Live E2E user
acceptance and production 004 deployment remain separate approval gates.

## Connection audit and actual path

| Connection | Implementation |
|---|---|
| Chat input to execution | Home defaults to natural-language analysis; preparation check and explicit cost confirmation precede POST /api/analyst/workflows. Existing queries remain available in the task-type selector. |
| Understanding to scope | Existing TaskUnderstandingService produces validated AnalysisTaskSpec. Unresolved/unsupported tasks stop without researching guessed targets. |
| Explicit or automatic scope | Explicit competitors go directly to research. Automatic tasks use AgentRunner.discover_competitors and retain the persisted selection audit. |
| Discovery to research identity | Verified discovery domains constrain SourceDiscoveryService before it updates profiles or sources. No URL input is required. |
| Shared research | One ResearchContext constructs existing source, snapshot and fact services for every product. Queries are limited to official site, features and pricing, with three selected pages per product. |
| Research to matrix | UNKNOWN research runs are finished before conversion to ResearchProduct. Extraction uses explicit run_id and current_run_only=True, without version activation or historical comparison. |
| Matrix to report | Existing AgentRunner.compare_products performs evidence rechecks, constrained synthesis and transactional publication. |
| Read, display and export | Workflow polling links root, research, discovery and comparison runs. Home displays task, progress, budget, matrix, conclusions, evidence and gaps. Existing report API/page/download use stored report content. |

The new orchestration lives in services/analysis_workflow.py and is exposed through
AgentRunner.workflow. The existing AnalysisTaskManager executor and capacity limit
are reused. Budget checkpoints are composed across discovery and comparison, so
the root audit tracks reservations before provider I/O. No extra agent framework,
parallel demo implementation or new database schema was introduced.

GET /api/analyst/workflows/readiness is read-only. POST /api/analyst/workflows
accepts `{ "text": "...", "allow_paid": true }`, returns HTTP 202 and a run_id.
GET /api/analyst/workflows/{run_id} returns persisted task/progress/results and
the final report_id. This is a local in-process executor, not a durable queue:
process interruption is not automatically resumed or retried. Browser replay
never automatically POSTs an old request. Repeating a completed input with a new
explicit confirmation creates a new task and may incur new charges.

## Local startup and user entry

Use Python 3.12 from the repository root, with the existing dependencies and local
`.env` configured. Do not print credentials or commit that file. No application
login/test account is required; the application binds to loopback and is not
designed for public exposure. Database and provider service credentials are
configured locally by the operator, not entered in chat.

```powershell
python -m competitive_intel.web
```

Open http://127.0.0.1:8000/ . If an older instance is already using port 8000, stop
that instance and restart it with the new code. Left navigation retains History,
Competitors and Reports. Recommended first request:

> 比较豆包和 Kimi 的核心功能与定价策略，并生成竞品分析报告。

Select natural-language analysis. Sending the text first performs a readiness
check. When deployment and payment gates are satisfied, a separate confirmation
button displays the budget before starting real work. The main conversation
shows progress, final matrix and evidence gaps. History reopens existing runs;
report links open the stored report and download the same Markdown.

Current deployment blockers must not be worked around with fixtures. Production
requires 004, reviewed cost rates, valid provider configuration, and an explicitly
enabled server gate. Do not enable the gate or run the following commands until
paid testing has been separately approved:

```powershell
# AFTER paid-test approval only; rates must be reviewed for the actual account.
$env:WORKFLOW_PAID_ENABLED = '1'
# Configure RESEARCH_SEARCH_COST_MICROUSD,
# RESEARCH_INPUT_COST_MICROUSD_PER_MILLION,
# RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION with reviewed integer rates.
python -m competitive_intel.web
```

Equivalent API invocation, also only after approval:

```powershell
$body = @{text='比较豆包和 Kimi 的核心功能与定价策略，并生成竞品分析报告。'; allow_paid=$true} | ConvertTo-Json
$accepted = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/analyst/workflows -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$runId = $accepted.data.run_id
Invoke-RestMethod "http://127.0.0.1:8000/api/analyst/workflows/$runId"
# Use the returned report_id in /api/reports/{id} and /api/reports/{id}/download.
```

## Small real acceptance plan — not yet executed

Start with one explicit two-product run. Review it before approving the automatic
discovery case; do not batch-run all cases or silently retry failures.

| Case | Expected behavior and records |
|---|---|
| Explicit 豆包 / Kimi, features + pricing | Exact scope, real official-source research, observed facts and traceable references. Missing price/billing evidence yields partial comparison, never an assumed price. |
| Target only: 分析豆包 | At most three checked candidates and two selected rivals, documented relevance and identity, shared budget including discovery. Partial discovery/research must remain visible. |
| Ambiguous input: 比较它们 | Clarification or unsupported response, no guessed products and no search after unresolved interpretation. |
| Controlled failure | Use a separately approved isolated configuration with an invalid provider credential or reduced budget; no production credential changes. Persist failure, no invented conclusions or unbounded retry. |

For each live run save the original text, AnalysisTaskSpec, root/discovery/research/
comparison IDs, search queries, official sources and snapshot IDs, fact/observation
IDs, exact evidence quotes, matrix, conclusions and limitations, budget/usage,
elapsed time and errors. Capture report_id, API payload and exported Markdown;
verify stored/exported content equality and absence of baseline/Changes side effects.
Keep captured live evidence and credentials out of Git. A partial result can prove
failure handling but does not prove a complete successful research scenario.

### Calls and cost ceiling

- Explicit two-product path: one understanding call, six planned searches,
  at most six fact-extraction calls for three pages per product, and one synthesis
  call. Usually around twelve page requests; alternate domains and redirects can
  increase that count up to the shared cap. Cache hits can reduce model calls.
- Three-product explicit path: nine planned searches, up to nine extraction calls.
- Automatic discovery: up to three candidate checks and two rivals, plus one
  candidate-evaluation call; discovery and research share the same counters.
- All-task hard limits remain 18 searches, 24 page requests including redirect
  hops, 13 model requests (1 understanding + 1 evaluation + 10 extraction +
  1 synthesis), 250,000 reserved tokens and 1,000,000 micro-USD ($1) reserved cost.

Actual prices have not been verified and reviewed-rate configuration is required.
For illustration only, the code's default assumptions ($0.001/search,
$0.30/million input tokens, $1.20/million output tokens) imply a conservative
all-task estimate no greater than $0.318 using 250,000 tokens at the higher rate
and all 18 searches. These are NOT a current vendor quote or measured invoice.
Recompute using actual account/model rates before approval; the execution gate
does not silently adopt these example rates. Charges for failed requests remain
reserved, and no unobserved usage is refunded.

## Production 004 preparation and execution plan

The read-only inspection found versions 001–003 and the historical three-value
reports enum. No production DDL or data mutation was performed. 004 is necessary
for the new report types; its absence blocks the workflow before any model call.

1. Stop writers and verify no RUNNING tasks, current versions and exact enum.
2. Take a new complete logical backup with schema, data, triggers/routines/events
   as applicable; securely retain a checksum and pre-backup row counts/digests.
   Never put backup data, connection passwords or personal paths in Git.
3. Restore to a newly named isolated database, not the disposable pytest database
   and not the existing retained restore copy. Verify all tables, relationships,
   row counts/digests, historical report reads and exports.
4. Rehearse only 004 on that restored copy; compare all historical rows/FKs, reads,
   exports, migration markers and idempotence. MySQL DDL is not transactional.
5. Report results and obtain separate production approval. Immediately before
   execution, confirm production still matches the verified backup; otherwise
   pause and renew backup/restore validation.
6. Execute only approved 004 under stop-write conditions. Verify enum, marker,
   all historical digests/FKs and report reads/exports. Stop on partial failure;
   do not automatically roll back or continue DDL.

The old initializer applies every missing migration: do not run it against
production as an informal workaround. Production migration, paid Smoke Test and
user acceptance are three distinct checkpoints.

## Known limitations

Validation checkpoint: 535 tests passed in the full non-paid regression. The
final additional mid-extraction budget-exhaustion case passed in a focused run
of all 10 workflow integration tests. JavaScript syntax checks passed. Browser
verification of the formal home entry confirmed the 004/payment/rate blockers
without starting research. No live-provider E2E run has been performed.

Real websites may block requests or require JavaScript, identity evidence may be
insufficient, prices may be incomparable, and all default dimensions may not have
facts. These are reported rather than inferred away. The synthesis model ranks
validated conclusion templates; it is not free-form strategic reasoning. Each
request is independent; no conversational reference resolution, candidate editing
or automatic report version management has been added. Browser conversation lists
are local; durable task/report history is in MySQL. In-process task loss requires
operator inspection before retry. This is not a declaration of completed live E2E
acceptance, Stage 9.1 reliability acceptance, or a completed Agent MVP.
