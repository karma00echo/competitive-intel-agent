# Stage 9.2.2: evidence-supported competitor discovery and task budgets

## Scope and acceptance boundary

This stage implements the discovery branch of the existing controlled AgentRunner.
It consumes the Stage 9.2.1 AnalysisTaskSpec, uses existing search/fetch/cleaning and
official-domain validators, and persists results through existing repositories.
It does not implement cross-product fact comparison, synthesis, reports, or the
Chat-first UI integration. No new schema or production migration is required.
Task Understanding and Evidence Validator are unchanged.

The adapters support live Serper and configured chat-completions evaluation, but
all development tests replace HTTP with synthetic responses. No paid requests
were made. These tests establish implementation behavior, not real search recall,
model accuracy, or complete Stage 9.1 live reliability acceptance.

## Actual execution path

`POST /api/analyst/discover` accepts exactly one of:

- `task`: a validated AnalysisTaskSpec from the existing interpretation service;
- `text`: natural language, interpreted once through the existing real adapter.

Paid providers require `allow_paid: true`, configured keys/model, and explicit
operator-reviewed cost rates. The default `false` rejects with HTTP 403 before
creating providers or accessing the database. Missing rates reject with HTTP 503.
This API is registered on the existing FastAPI application, not a demo server.

The path is:

1. One ResearchContext owns the ledger for interpretation, discovery, and later
   research. If text is provided, the interpretation call consumes the same ledger.
2. The existing AgentRunner discovery branch creates an UNKNOWN run, SOURCE_DISCOVERY
   stage event, and `discover_competitors` Tool Registry audit entry. It does not
   bind this discovery-only run to a competitor or historical baseline.
3. Two searches for target identity (official site and product features) feed the
   existing official-source validator and domain aggregation/margin selection.
   Up to two promising domain pages are fetched. Unresolved identity is disclosed;
   ambiguous targets request a company or use description, never a mandatory URL.
4. Explicit competitors remain exactly the user's scope, including when identity
   verification fails. They are marked USER_SPECIFIED and unverified when necessary;
   no alternatives search or relevance model call expands or replaces them.
5. Otherwise, an alternatives search supplies candidate leads from product-like
   result titles. If fewer than three leads exist, up to two retrieved articles
   can nominate products via labelled external links. No product-name lookup list
   is used. Search co-occurrence and article links are leads only, not proof.
6. Name normalization removes Unicode/case/spacing duplicates and the target itself.
   At most three nominees undergo official identity checks. Shared domains are
   conservatively treated as an alias/product-family ambiguity, not separate rivals.
7. One schema-constrained evaluation compares the verified official page excerpts.
   Each supported candidate needs exact continuous quotes from both products and
   a specific overlapping use present in both quotes. Own-product attribution,
   generic-use rejection, negative/comparison markers, known names, duplicate
   results, and evidence substring checks run server-side.
8. At most two supported candidates are selected. Selection is explicitly an
   EVIDENCE_BASED_INFERENCE with uncertainty, not a confirmed competitive fact or
   market ranking. Unknown names/quotes are rejected; valid other results survive.

The response contains the task, target identity, candidate leads, official identity
confidence/reason, source URLs, collection times, bounded clean excerpts and hashes,
quoted relevance evidence, selected names, gaps, provider metadata, model usage when
returned, and the shared budget state. `analysis_complete` is always false and no
report is generated. A READY response means discovery is ready, not full analysis.
Fewer than two supported automatic candidates yields PARTIAL; no invented fill-ins.

The existing `/api/runs/{id}` exposes discovery phase/status without mislabelling
it as Fixture or complete analysis. `GET /api/analyst/discover/{id}` reads the saved
bounded result, including full ledger, from the ToolCallRepository. The developer
tool-audit endpoint remains available as well.

## Budget semantics

| Shared resource | Default maximum |
| --- | ---: |
| Search HTTP attempts | 18 |
| Web HTTP attempts, including redirects | 24 |
| All model attempts | 13 |
| Understanding / candidate evaluation / later synthesis | 1 each |
| Later fact-extraction attempts | 10 |
| Reserved input plus maximum output tokens | 250,000 |
| Reserved cost | 1,000,000 micro-USD (US$1) |

Requests reserve quota before network I/O. Search/model redirects are disabled;
web redirects are explicit and each hop consumes quota, with a six-hop bound.
Retries, including failed attempts, cannot bypass the transport ledger. The
discovery runtime disables search/extraction automatic retries. Model evaluation
has no retries. Count/cost reservations are atomic under a lock and never refunded
on unknown usage, malformed responses, timeout or failure.

Token accounting is a conservative UTF-8 payload byte estimate plus a framing
reserve and maximum output allowance for supported byte-tokenized chat models.
It is not exact tokenizer usage or an invoice. Actual returned usage is separately
recorded. Custom endpoints/tokenizers require operator validation of that bound.
Operators must supply reviewed rates matching the configured provider/model:

```text
RESEARCH_SEARCH_COST_MICROUSD
RESEARCH_INPUT_COST_MICROUSD_PER_MILLION
RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION
```

All three are positive integer micro-USD amounts. No price is inferred from a
model alias or a free-credit assumption. No account top-up is performed. The
ledger reserves using these configured ceilings, so outdated/understated rates
cannot establish an actual invoice guarantee. Rates, model/host and reservation
semantics are retained in research_policy. This configuration is intentionally
not written into the local environment by this implementation.

Before each discovery-phase external request, a Repository checkpoint persists
the ledger without marking the tool finished. If checkpoint persistence fails,
the external attempt does not proceed. Terminal result, audit and run status are
committed together. Budget exhaustion returns PARTIAL, preserves gathered evidence
and explicit scope, and prevents further network work. UNKNOWN discovery runs have
no report or baseline_integrity marker and never create Changes/Signals.

There is no automatic process-crash recovery or public resume endpoint in this
stage. A crash can leave a RUNNING audit checkpoint; no automatic quota reset or
claim of success is made. The natural-language interpretation precedes run creation;
its failure returns an API result and ledger but does not create a discovery run.

## Handoff to later research

Later code must keep the same ResearchContext, or reconstruct it from trusted
Repository audit with `ResearchContext.from_trusted_audit(...)`. Never accept
client-provided spent counters or create a new context per product. Rehydration
preserves task ID, limits, consumption, exhaustion and pricing; model/host changes
are rejected within a task. This is a continuation interface, not an implemented
cross-product analysis workflow.

`context.research_services(persistence)` returns the existing SourceDiscoveryService,
SnapshotService and FactExtractionService bound to the same budgeted transports.
Its fact provider is the existing evidence-validated LLM extractor. Existing
eligible extraction caches bypass model transport and incur no new model charge;
the discovery service additionally reuses successful pages only within its own
invocation. No new persistent fact cache or weakened validator is introduced.

Candidate evidence is retained as bounded discovery audit, not inserted into
confirmed Facts or historical Sources/Snapshots. Later research must fetch or
legitimately reuse eligible evidence through the existing source/snapshot/fact
pipeline before treating it as a comparison fact. Candidate excerpts are not a
substitute for product/source/snapshot/observation relationships.

The existing historical `/api/analyses` behavior is unchanged. It must not be
looped once per product to implement later competitive analysis: that would reset
budgets and could publish historical baselines. Stage 9.2.3 still requires an
explicit research-only execution path and a separately approved schema plan if
new report types or relationships are needed.

## Offline and isolated validation

Run the dedicated tests without any live provider:

```shell
python -m pytest tests/unit/test_competitor_discovery.py tests/integration/test_competitor_discovery_flow.py -q
```

MySQL integration fixtures require a disposable database ending in `_test`; they
initialize and clear test rows. Never point them at production or a retained
restore-verification database. External HTTP in these tests is forbidden; the
production Serper/RequestsFetcher/evaluation adapters run against synthetic
transports with clearly invented products.

Coverage includes explicit scope preservation, automatic title/link nomination,
normalization/deduplication, identity ambiguity, insufficient relevance, fabricated
quotes/names, generic co-occurrence, search/page/model failure, each resource limit,
redirect charging, concurrent reservation, no-refund errors, page reuse, multiple
fact-provider instances sharing quota, trusted handoff, paid-consent/rate gates,
API entry, Repository persistence, checkpoint-before-I/O, and history isolation.

Validation record: full suite **472 passed**; after the final failure-path and
run-view metadata adjustments, focused discovery/interpretation/integration
regression **99 passed**. Both have one existing Starlette/httpx deprecation
warning. There are 41 new discovery/budget tests (31 unit, 10 integration).
The disposable integration database was `competitive_intel_test`. No production
or retained restore database was accessed, and no live provider call was made.

## Known limits

- Candidate nomination is conservative title/link parsing, not open-ended entity
  extraction; unusual titles, numeric product names, aliases and unlinked articles
  may yield insufficient candidates. It does not promise exhaustive discovery.
- English/Chinese own-product quote forms and literal shared-use matching trade
  recall for explicit evidence. Cross-language synonyms can be rejected even if
  semantically related; real-source/model acceptance remains pending.
- Relevance is still a bounded model inference, not a deterministic proof of
  direct market competition. Quotes and identity checks reduce unsupported output
  but do not make semantic interpretation infallible.
- Missing/blocked/dynamic pages are unknown. Domain inspection limits and partial
  evidence are disclosed. Same-domain distinct products need later clarification.
- This synchronous discovery API is not yet connected to the Chat-first composer
  or its asynchronous task progress manager. Those belong to the later UI phase.
- Cross-product matrix, grounded synthesis, competitive reports and candidate
  replacement/versioning remain unimplemented. No full Agent MVP or real E2E pass
  is claimed by this stage's automated tests.
