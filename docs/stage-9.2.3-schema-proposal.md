# Stage 9.2.3 report compatibility and migration proposal

Status: migration-file implementation and disposable test-database rehearsal
approved. Production execution still requires separate explicit deployment
approval after backup/restore verification; it is not authorized here.

## Existing contracts and conflict check

ResearchContext already supports a trusted budget handoff and shared research
services. Single-product extraction can write observations without calling the
historical comparison/baseline publisher. Facts, versions, observations, snapshots
and source records can represent all products independently.

Reports currently allow BASELINE, CHANGE_TRACKING and PARTIAL_EVIDENCE only.
Their competitor_id is a required foreign key, and (run_id, report_type) is unique.
The existing summary_json field can hold a versioned multi-product matrix and
the full evidence index. No additional table is needed for this MVP.

Stage 9.2.2's public contract explicitly prohibits publishing comparative research
through historical baseline runs and requires separate schema approval for new
report types. This agrees with the Stage 9.2.3 request; no conflicting instruction
was found. Calling a competitive report BASELINE or PARTIAL_EVIDENCE would obscure
its semantics and is not an acceptable workaround.

## Proposed incremental 004

Only append these values to reports.report_type, preserving existing order:

```sql
ALTER TABLE reports MODIFY COLUMN report_type
  ENUM('BASELINE', 'CHANGE_TRACKING', 'PARTIAL_EVIDENCE',
       'COMPETITIVE_ANALYSIS', 'COMPETITIVE_ANALYSIS_PARTIAL') NOT NULL;
```

`004_competitive_reports.sql` is discovered by the existing initializer.
There are no UPDATE/DELETE statements, new required columns, new tables or foreign
key changes. MySQL may take a metadata/table lock; this is not promised to be an
online or zero-downtime alteration.

For these reports, competitor_id references the target product as an anchor,
not sole ownership of every fact. Versioned summary_json explicitly lists all
products, research run IDs, selected dimensions, matrix cells, fact/evidence IDs,
gaps, conclusions, inherited budget and parent discovery run. Each evidence entry
retains its actual product/source/snapshot/observation/run association.

Competitive runs keep run_mode UNKNOWN and never create baseline_integrity markers,
activate fact versions or generate historical Changes/Signals. Their observations
remain PENDING for historical comparison. Full and partial types are explicit;
zero evidence must not generate a complete report. A target identity that cannot
be resolved cannot be used as a fake report FK: retain an incomplete run result.

## Application compatibility

Extend the existing report service's lookup and renderer plus report API projections
to recognize the two new types. Reuse ReportRepository and existing Markdown export.
Keep historical latest-report/baseline selectors restricted to their existing types.
Existing report IDs, content and historical selectors must produce identical results.
New-schema capability checks must fail before starting paid work on an old schema.

The target/product mapping belongs in the versioned report payload; no field named
competitor_id may be interpreted as ownership of all matrix cells. Do not join
cross-product facts by name or attach one product's facts to another run.

Publish report, terminal run status and final audit atomically through Persistence.
Serialize comparison claims on the target profile row and save the task ID and
scope signature in tool audit before synthesis. Repeated/concurrent calls return
the same running/completed execution rather than resetting the ledger. Completed
reports are immutable; changed scope requires a new task. Automatic research
continuation and user-directed report versioning remain later workflow work.

## Isolated migration and application tests

1. Only use an explicitly disposable `_test` database, never the retained restore
   database or production. Seed all existing report types and related history.
2. Initialize through 003, capture SHOW CREATE TABLE, row counts and full row hashes;
   apply only 004, compare history/FKs, then rerun and verify idempotence.
3. Confirm both new types can be persisted and read/exported; an unknown enum is
   rejected; old reports/exports and baseline selection remain unchanged.
4. Verify duplicate and concurrent report publication, transaction failure rollback,
   explicit partial results, provenance rejection and shared budget continuation.
5. Simulate interrupted initialization where the ALTER succeeded but the marker did
   not: test safe re-entry on the disposable copy. No automatic production retry.

## Production deployment gate (not part of this implementation approval)

Stop writers and confirm no active tasks. Verify versions 001–003 and exact expected
enum, take a complete backup, restore it to an isolated copy, rehearse 004 there,
compare full business-row digests, FKs, report reads/exports and idempotence.
Immediately before production execution, compare production with the verified
backup; any difference requires renewed backup/rehearsal. Obtain separate approval
to apply only 004. Stop on partial failure; do not automatically issue more DDL.

Rollback is not a blind down migration. MySQL DDL is not transactional; removing
enum values after new reports exist can lose data. Prefer a forward fix, or a
separately approved restore with an explicit post-backup data-preservation plan.
Application rollback must keep the additive schema and prevent old consumers from
misclassifying new types. Never delete competitive reports to make rollback work.
