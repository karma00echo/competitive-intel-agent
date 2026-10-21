# Stage 9.1.4 — Conservative Partial Success

Verified locally on 2026-10-21 with Python 3.12.13: 373 tests passed (one
pre-existing Starlette/httpx deprecation warning), including actual empty-test-
schema initialization and upgrade recovery. compileall, pip check, JavaScript
syntax checks and git diff checks passed. No paid API request was made.

## Result contract

Partial publication is only attempted after the normal extraction tool has been
audited, when extraction/fetch coverage is incomplete (including NO_FACTS).
At least one CONFIRMED, traceable fact outside every unresolved identity must be
available. All run observations must still be PENDING. Source, competitor,
same-run successful snapshot and contiguous evidence are rechecked.

Report insertion, final summary audit and PARTIAL_SUCCESS status are committed
in one transaction. Failure rolls these back and the runner records FAILED.
No baseline activation, fact comparison, Changes or Signals occurs. Previously
active facts remain active, but observations made by this run remain PENDING.
No trustworthy fact, all-conflicting facts or corrupt provenance means FAILED.
All-empty extraction remains NO_FACTS at page level; the run fails with
NO_UNCONTESTED_VERIFIED_FACTS, not a fabricated evidence error.

PARTIAL_EVIDENCE reports disclose coverage, failed/not-extracted/NO_FACTS pages,
rejections, field diagnostics, unresolved conflicts and snapshot-linked facts.
Conflict versions appear only in an explicitly unresolved audit section, never
as confirmed conclusions. No strategy or inference is generated.

Formal latest-report queries exclude partial reports. Lists and explicit report-ID
or run-ID lookup may return them with their distinct type. Baseline selection
continues to require COMPLETED plus the eligible full-run audit and activated
observations. Completed partial runs cannot be activated, compared, or converted
into formal reports by the history/report services. Partial runs are excluded
from complete-page cache origins by the existing COMPLETED filter.

Chat-first and Developer display PARTIAL_SUCCESS, pending evidence and a partial
report link; Reports displays PARTIAL_EVIDENCE. No layout redesign is included.
Database current_state retains COMPLETED as a stage value; status is the distinct
PARTIAL_SUCCESS outcome. Consumers must use final_state/status, not stage alone.

## Migration and deployment

Actual local server checked: MySQL 9.0.1, native ENUM columns. Migration 003 only
appends PARTIAL_SUCCESS to agent_runs.status and PARTIAL_EVIDENCE to
reports.report_type. No new table or fact-schema change; existing enum order and
historical values are preserved. New databases apply 001, 002, 003 in order.

Stop writers and take a verified backup before upgrading the application database.
Use a migration account with ALTER on these two tables (and existing migration
metadata privileges). Do not grant elevated permissions to the web process merely
to perform deployment. Run from the repository with the appropriate local .env:

```powershell
& "D:\anaconda\envs\competitive-intel-py312\python.exe" scripts/init_database.py --database-exists
# Disposable test DB only:
& "D:\anaconda\envs\competitive-intel-py312\python.exe" scripts/init_database.py --test --database-exists
```

MySQL DDL implicitly commits: these two ALTERs are not an atomic transaction.
If interrupted, keep writers stopped and rerun the initializer. ALTER is
idempotent and the migration marker is recorded only after both succeed. Tests
exercise old rows surviving upgrade, repeated application and missing-marker
recovery, as well as fresh initialization of the disposable test schema.

Recovery preference: roll forward by rerunning 003. For a code rollback, retain
expanded enums and do not serve partial records with an older UI that mislabels
them; use maintenance/read-only operation until compatible code is restored.
Do not shrink ENUM if *any* partial rows exist, and never relabel/delete them to
force rollback. If there are no partial rows, an administrator may, with writers
stopped, restore exactly the old ENUM definitions from 001 and remove only the
003 migration marker. Recheck zero counts first:

```sql
SELECT COUNT(*) FROM agent_runs WHERE status='PARTIAL_SUCCESS';
SELECT COUNT(*) FROM reports WHERE report_type='PARTIAL_EVIDENCE';
```

This development run upgrades/rebuilds only the disposable test database. Apply
the production migration explicitly at deployment; old historical data is not
rewritten by the application.

## MVP completion versus real reliability acceptance

MVP foundation: real search/fetch/DeepSeek, strict schema/evidence validation,
and safe partial-result publication are implemented. Offline/MySQL tests cover
publication rollback, audit failure, terminal-status failure, invalid provenance,
conflict exclusion, empty results and formal-baseline isolation.

Full end-to-end reliability acceptance is NOT established by these tests. No
paid request or full Notion run is performed for this stage. Remaining known
issues: model classification/quote/list instability, cross-source canonical
conflicts requiring evidence-based diagnosis, strict single-quote schema limits,
and formal baseline + repeated-run stability still needing explicit real-world
acceptance. Partial results do not resolve these limitations or count as full
baselines. Do not open additional 9.1.x work or start 9.2 automatically.

If the database itself is unavailable, even recording FAILED may be impossible;
never claim successful publication in that case. Operator recovery must inspect
interrupted RUNNING records after connectivity returns.
