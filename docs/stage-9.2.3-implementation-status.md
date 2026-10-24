# Stage 9.2.3: evidence matrix and competitive reports

This stage consumes researched product observations and persists comparative
reports. No live-provider or production database validation has been performed.
Stage 9.1 real end-to-end reliability acceptance remains outstanding.

## Implemented contracts

`CompetitiveMatrixService.build(task, products)` accepts an AnalysisTaskSpec and
one target plus up to two ResearchProduct records. These records are server-side
research outputs, not trusted client-supplied IDs. Explicit competitor scope is
preserved. Application-owned transactions load fact observations through
FactObservationRepository.list_for_matrix; the domain builder performs no I/O.

The `competitive-matrix-v1` payload contains target, dimensions, products with
dimension cells, deduplicated facts, an evidence index and gaps. Each evidence
entry carries product, original fact, source, snapshot, observation and run IDs,
URL, quote, confidence, snapshot hash and collection/observation timestamps.
Source, snapshot, fact version and observation ownership are rechecked together
with the existing EvidenceChecker. Identical normalized values retain all source
observations; conflicting values remain visible but cannot support conclusions.
The service also reads persisted extraction conflict diagnostics when a conflicting
candidate was rejected before persistence, and derives partial research status
from actual runs. Callers can supply additional known conflicted_fact_keys.

Cells distinguish EVIDENCED, INFORMATION_INSUFFICIENT, IDENTITY_UNCERTAIN,
SOURCE_CONFLICT and TIME_INCOMPARABLE. Missing information never implies feature
absence. Collection dates are conservatively required to match; collection time
is not a guarantee of the underlying claim's effective date.

`CompetitiveAnalysisService.analyze(matrix, context)` accepts only a matrix built
by the trusted service and the existing ResearchContext. Deterministic findings
include common documented features, possible differentiators, positioning and
listed unit-price comparisons. Every finding references facts and observations
and is labeled ANALYSIS_INFERENCE. Price comparison requires aligned currency,
period, unit, commitment, region, tax basis and observation date. It makes no
claim about equivalent entitlements, overall value or suitability.

The synthesis adapter can prioritize up to twelve supplied findings, returning
only existing IDs; new prose, sources and facts are rejected. This intentionally
does not implement unrestricted generative analysis. The shared synthesis
transport reserves model/token/cost budget before I/O, with no retries or new
ledger. Failure preserves the matrix, returns PARTIAL and no invented conclusions.
Model prioritization is limited to sixty findings and a bounded request size.

## Controlled runner, persistence and APIs

`AgentRunner.compare_products(persistence, task, products, context)` is the
server-side entry point, registered as compare_products in the existing Tool
Registry. It returns phase, status, run_id, report_id, report_type,
analysis_complete and inherited budget. Products are ResearchProduct records
with name, product_id, run_id, identity_verified, status and issues. No client
execution endpoint or arbitrary client-supplied budget is introduced.

Automatic scope must match persisted discovery task, selected names and task ID;
budget limits cannot change and usage cannot decrease. Explicit scope cannot be
expanded or replaced. Target/profile/research-run bindings are checked. A 004
capability check runs before model use. Claims serialize on the target profile
row and store task ID plus scope signature in tool audit. Duplicate calls return
the existing execution, including a running or failed claim. Changed scope needs
a new task. Budget checkpoints precede I/O. Interrupted RUNNING claims require
operator recovery and are never automatically retried with a fresh budget.

Report publication, terminal run state and final audit commit atomically. A
publication failure rolls back the report and records failure. Competitive runs
stay UNKNOWN and never activate fact versions, create Changes/Signals or publish
baseline integrity. Historical latest-report selectors remain unchanged.

The approved 004 migration adds only COMPETITIVE_ANALYSIS and
COMPETITIVE_ANALYSIS_PARTIAL. The target anchors reports.competitor_id; every
matrix fact retains its actual product. The complete analysis is stored in
summary_json, with Markdown rendered once. Existing GET /api/reports/{id} returns
the competitive payload without display truncation, and /download exports the
same stored Markdown. Report lookup by run ID and run API phase/completion flags
also support the new types.

## Verification

- 42 new pure unit tests use synthetic observations and injected HTTP.
- Full non-paid regression: 525 passed. A final additional no-competitor boundary
  test was followed by 54 passing stage-specific tests (42 unit and 12 disposable
  MySQL integration tests). Existing TestClient cases also pass in the full run.
- Integration covers explicit three-product reports, automatic-discovery handoff,
  missing dimensions, failed research, shared budget, model failure, persisted
  conflicts, concurrent/repeated execution, publication rollback and API/export
  consistency. Providers and upstream research observations are synthetic.
- 003-to-004 rehearsal preserves all seeded business-table rows and report FKs;
  repeated initialization and missing-marker re-entry pass on the disposable DB.
- No real search, model accuracy or end-to-end claim follows from these tests.
- No production database operation or paid call was executed.

## Later workflow and deployment boundary

See [the schema proposal](stage-9.2.3-schema-proposal.md). Production migration
still requires a separate backup/restore, stop-writer and explicit approval gate.

The runner consumes existing research observations; it does not automatically
execute search/fetch/extraction. The later natural-language workflow must gather
products using the same context's research services, finish research runs without
historical activation, and hand them to this interface. Real-provider reliability,
model accuracy and complete interactive workflow acceptance remain unverified.

The eventual workflow can pass the trusted discovery scope into research, then
feed ResearchProduct records into these two services using the same context.
The Workspace can consume product cells, evidence index, conclusions, gaps and
budget directly from persisted report content. No UI or Stage 9.2.4 implementation
is included. Claims are deliberately limited: collection date is not effective
date, and model synthesis prioritizes validated templates rather than producing
unrestricted prose or unsupported competitive rankings.
