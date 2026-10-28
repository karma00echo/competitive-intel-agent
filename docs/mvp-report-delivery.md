# AI analysis and formal report delivery

The report pipeline now accepts original analytical prose rather than finite text
variants. The model receives confirmed facts, legal comparisons, original quotations,
the research question and coverage gaps. It produces structured units for overview,
differences, conclusions and recommendations. The server assigns IDs, resolves
citations, normalizes paragraph whitespace and renders one persisted presentation
for both Workspace and Markdown. Historical reports retain their existing format.

## Evidence and review boundary

`domain/analytical_writing.py` validates structure, reference existence, confirmed
fact status, cross-product premises, recommendation verification methods and duplicate
paragraphs. Numerical assertions and absolute rankings are conservatively excluded
from free prose; numerical facts remain in verified structured tables. These rules
are not a general natural-language entailment detector.

Free prose cannot be accepted solely because its IDs exist. Every unit requires a
server-owned independent review keyed by SHA-256 of the complete evidence packet and
normalized unit. The reviewer must check the text, premises and recommendations
against the cited quotations, including product attribution and the distinction
between documented mechanisms and claimed effects. Changing evidence, request scope
or substantive prose invalidates the review. Never generate blanket approvals from
model self-assessments or from successful reference checks.

Unreviewed/rejected content stays in the expandable technical audit; it is withheld
from report conclusions. Valid reviewed units survive a failure elsewhere. A missing
or rejected required section prevents READY. Format diagnostics are separate from
evidence/review diagnostics. Provider failures retain verified tables and limitations.

Coverage (`PARTIAL`/`COMPLETE`), `ai_status`, and `delivery_status` are independent:

| AI status | Delivery | Meaning |
| --- | --- | --- |
| NOT_RUN | EVIDENCE_REPORT | Existing deterministic report path |
| FIXTURE_VALIDATED | DEMO_READY | Offline fixture checked; not live AI acceptance |
| REVIEW_REQUIRED | REVIEW_REQUIRED | Candidate stored, unreviewed claims withheld |
| FAILED | REVIEW_REQUIRED | Writer/JSON failure; factual evidence retained |
| HUMAN_VALIDATED | READY | All required AI sections independently reviewed |

The database transaction must still succeed before a report ID is returned. No
schema migration, historical fact update or source acquisition change is required.

## Formal application paths

The existing Chat now has an “已有证据 → AI 分析报告” mode. Supply a source competitive
report number and a request naming its products. This mode explicitly retains the
source report's research scope; it does not interpret arbitrary replacement products
or silently broaden research. Chinese requests default to Chinese, with explicit
language requests taking precedence. It uses `POST /api/analyst/saved-writing`.

The server recovers product/run identities from the persisted comparison tool call,
then revalidates observations through `CompetitiveMatrixService`. It does not trust
a client-supplied matrix. A new report is saved through `CompetitiveReportService`;
the source report is immutable. The request UUID provides idempotency, and scope
changes under the same UUID are rejected. Browser refresh does not restart a task.

Operator configuration (local trusted paths only; never commit these artifacts):

- `REPORT_WRITER_FIXTURE`: a JSON file with `packet_hash`, `payload`, and `reviews`.
  The response is pinned to the entire input packet and always labelled Fixture.
- `REPORT_WRITER_REVIEWS`: an independently prepared JSON mapping from diagnostic
  fingerprints to review rationales. The offline action on a candidate report uses
  `StoredCandidateWriter` to publish reviewed prose in a new report without another
  provider call. Use the original research request verbatim. Changed evidence blocks
  reuse. This is operator review, not an unauthenticated browser approval API.
- `AI_REPORT_WRITER_ENABLED=1`: enables the separately authorized live writing action.
  Browser fee consent is also required. Leave disabled until live acceptance is
  approved. No live execution is needed for fixture demonstration.

When enabled on the existing full research workflow, the analytical writer uses the
same task budget. The deterministic Finding catalog is supplied directly, avoiding a
second paid ID-selection call. Legacy synthesis remains unchanged when the writer is
disabled. Full live research still requires its existing configuration/consent gates.

## Provider and next acceptance

`AnalyticalWriter` reuses the reviewed DeepSeek transport, output bounds, pre-request
reservation, response limits, timeout and durable attempt guard. Only the prompt and
wire compaction differ. All confirmed fact values and quotations are retained; source
URLs/timestamps remain in the server's hashed review packet and final references.

The isolated saved-evidence path permits one model request, input ceiling 16,000 and
output ceiling 4,000, with a US$0.50 application ceiling. Existing reviewed rates imply
a worst-case US$0.0096 reservation. This is not a vendor invoice. Model/endpoint,
capacity, rate match, remaining shared budget and the seven-day review validity are
checked before HTTP. No retries, search, fetch or extraction occur on this path.

Next live acceptance requires separate approval: one request, saved candidate/raw
response and vendor usage, independent claim-by-claim review, then offline publication
of accepted prose through the same report service. Evaluate natural Chinese,
non-repetitive cross-product interpretation, conditional strategy advice, exact
evidence support, preserved gaps, reopening and export. Fixture tests prove plumbing
and rejection behavior, not live-model analytical quality or autonomous truth checking.

## Offline verification

Run the full suite with Python 3.12 and a disposable MySQL database ending in `_test`:

```powershell
python -m pytest -q -o cache_dir=build/pytest-cache --basetemp=build/pytest-mvp
```

New tests exercise open prose, review invalidation, legal-ID hallucinations, invented
prices, unsupported advantages, missing premises, whitespace normalization, malformed
JSON, timeout/HTTP/truncation/oversize responses, one-attempt accounting, production API
persistence, idempotency, original report preservation, reopening, production DOM
citations and Markdown parity. A private historical packet test checks all 17 facts
and quotations and the writer preflight; it skips when that private fixture is absent.
