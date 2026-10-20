# Stage 9.1.3: extraction robustness and partial-result decision

## Scope and evidence

Offline changes only. No paid calls, no database migration, no validator,
identity, comparison, report or state-machine changes. Prompt policy v10
invalidates older extraction cache identities intentionally.

Read-only investigation of run 35:

| Failure | Finding |
| --- | --- |
| Six Features classifications | Model inferred AI / AUTOMATION / INTEGRATION from descriptions, not supported explicit labels. Nullable provider fields already exist; persisted OTHER is the existing unknown sentinel, not a positive classification. |
| Business / Enterprise lists | The quote ends at the inheritance heading; 17 list fields are outside that quote. Model quote scope is insufficient. Existing PLAN schema has one evidence string, not per-item citations. |
| Release affected_features | Notion MCP is absent from the selected quote. Presence elsewhere cannot ground this field. |
| Release discontinuous quote | The model omitted the video/ad-blocker notice between title and paragraph in snapshot 87. Strict rejection is correct. |
| Four cross-source conflicts | Pricing snapshots 85/86 have identical clean hashes; releases 87/88 likewise. They do not demonstrate a change in page content. Old audit did not retain either conflicting candidate pair, so the precise fields cannot be reconstructed reliably. No retrospective assertion of semantic contradiction is justified. |

Minimal changes: explicit counterexamples in page contracts, schema descriptions
for nullable categories and quote-scoped lists, and bounded paired cross-source
conflict audit with IDs, normalized value excerpts, evidence excerpts and reason.
No model result is silently repaired, dropped from validation, or promoted.

For PLAN, output one small name/description fact and only list items within its
single quote. An empty list means "not extracted", NOT "the plan has no features".
Do not split one plan into multiple PLAN identities to store different lists.
True per-item citations would require a future contract/storage/read-model
decision; they are not introduced here.

## Identity interpretation

Keep canonical equality as the deduplication rule. Distinct explicit price
period/unit/payment commitments already produce distinct PRICE keys.
The same key with different normalized values remains unresolved and rejected;
it can mean contradiction, extraction granularity, wording variation, or a missing
scope dimension. Neither first nor last candidate is activated as a winner.
An earlier validated record may remain stored as PENDING for audit, not baseline.

Source ID alone must not be added to identity to hide conflicts. Version, region,
currency, product scope and release date distinctions must first be grounded and
reviewed against the actual key/schema. In particular price currency/region are
values rather than key dimensions today; do not claim all legitimate variants
are already representable. No key migration is justified by the incomplete #35
conflict audit.

New cross-source diagnostics are bounded per fact and retain both source/snapshot
IDs. They redact credential-shaped text and never include request headers, local
configuration or complete source pages. Values/evidence may be truncated; IDs
allow an authorized local audit. They label the conflict unresolved rather than
asserting a real-world contradiction.

## Current status semantics (unchanged)

- SUCCEEDED page: all returned facts accepted or deterministically deduplicated.
- NO_FACTS page: valid empty extraction, not proof of absence.
- PARTIAL_ERROR page: some accepted facts, some rejected; not complete cache.
- FAILED page/run: execution, schema, grounding or identity integrity failure.
- In a failed full run, validated facts may persist but observations stay PENDING;
  no comparison, activation or formal report follows.
- Current formal-baseline eligibility requires full AgentRunner provenance,
  complete successful source/snapshot coverage, SUCCEEDED pages, non-PENDING
  observations, no errors and a report.
- A legal NO_FACTS page can complete with warnings but currently prevents
  baseline replacement/eligibility. This is conservative, not an execution error.
  Do not conflate "finished" with "eligible baseline".

## Proposed PARTIAL_SUCCESS (NOT IMPLEMENTED; approval required)

Recommend an explicit non-baseline partial-result outcome, but only after
coverage-aware report/comparison rules are agreed. Merely renaming PARTIAL_ERROR
or mapping it to SUCCEEDED is unsafe.

Minimal first implementation proposal:

1. A run with at least one accepted evidence-backed fact and incomplete source
   coverage may produce a clearly labelled **partial evidence report**. A run
   with no trusted facts, broken provenance or a failed persistence transaction
   remains FAILED. Per-page errors remain visible.
2. All observations in this partial run stay PENDING. No baseline replacement,
   Changes, Signals or deletion detection is performed. Rejected facts remain
   excluded; unresolved identities cannot be presented as settled conclusions.
3. The existing eligible full baseline is retained. Partial/single-page/failed
   runs are never eligible for the next full comparison.
4. A partial report must enumerate requested, fetched, extracted and missing
   sources, page statuses, rejected field names/reasons, unresolved identities,
   accepted fact counts and source/snapshot/run links. It must explicitly state
   comparison was not performed and missing facts are not deletions.
5. NO_FACTS is reported separately from HTTP/schema/evidence failure. Any source
   with unknown coverage, including an empty extraction, cannot prove a removal.
   Later source-aware comparisons require a separate approved completeness
   design; per-source partial activation is out of scope for the minimal option.
6. Before implementation, decide how to expose the outcome in the existing
   persisted run-status enum and API. Reusing COMPLETED_WITH_WARNINGS would
   require an explicit partial-result marker and all consumers respecting it;
   adding a status may require a migration. Neither is silently chosen here.

Required acceptance tests for that future change:

- Partial report never changes current facts or the next baseline selection.
- A missing/failed/NO_FACTS source cannot produce REMOVED or deletion Signals.
- Rejected/conflicting facts cannot be activated or described as settled facts.
- Reports disclose each missing source and field and retain source evidence links.
- A later complete run compares against the last eligible full run, not partials.
- Transaction rollback cannot leave an eligible marker with incomplete activation.

## Remaining decision

Approve (or reject) the conservative partial-evidence-report design above before
changing state/report contracts. Real model improvement is not claimed by offline
tests. A future bounded live validation must be explicitly authorized.
