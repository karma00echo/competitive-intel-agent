# Run 36: live workflow diagnosis

Outcome: **FAIL for the requested evidence-backed comparison/report**, although
the persisted orchestration status is PARTIAL_SUCCESS. No live retry was made
during diagnosis. The paid-enabled web service was stopped. Production records
were read only; retained snapshots were not re-cleaned into the database.

## Observed path

- Root 36, tool call 117: input comparing Doubao and Kimi, features and pricing.
  Live DeepSeek Flash task understanding returned READY, explicit competitors,
  no automatic discovery. Audit records one attempt, 742 input and 116 output
  tokens (858 total). Chinese input/name are correct in storage; console encoding
  artifacts are not corrupted task data.
- Doubao: three queries (`豆包 官网`, `豆包 功能`, `豆包 定价`), no selected
  official domain and no saved sources. No product research run or fact extraction
  was started. The first known break is official identity/source selection.
- Kimi: three queries (`Kimi official website`, `Kimi features`, `Kimi pricing`).
  Source 15 is verified `https://www.kimi.com/en`, domain kimi.com. Its saved
  validation reason records score 12.0, 8 results, features/homepage/pricing
  coverage, brand=5, redirect=1, metadata=2, margin=2.5. These are aggregation
  signals, not eight retained individual URLs or a redirect trace.
- Kimi child run 37, snapshot 89: HTTP 200, SUCCESS, requested and final URL both
  `https://www.kimi.com/en`. Raw HTML length 168447; cleaned main content length
  74: “Ask anything, or task an agent… Select project Plugins Explore inspiration”.
  Stored title identifies Kimi; description metadata mentions coding/agent uses.
  Navigation includes links such as /slides, /deep-research and /docs. This is a
  sparse application shell, not an empty response. There is no saved evidence
  proving a CAPTCHA, HTTP denial or that executing JavaScript would fix it.
- Offline re-cleaning of the saved HTML reproduces the exact stored text/hash
  `b4145809b55c446a7ff09403bc33b3cc24e5405d7c662b530a54973c54037ca1`.
  Existing cleaner intentionally excludes navigation/head metadata and chooses
  main content. That policy is not relaxed; UI labels are not pricing facts.
- One extraction request was reserved. Zero observations were persisted; no
  FACT_EXTRACTION_PARTIAL flag was returned. Exact model response, candidate
  count, HTTP response, rejections and usage were not persisted by this workflow.
  “Zero confirmed” must not be relabeled “the model returned zero candidates”.
- Target identity was false, triggering TARGET_IDENTITY_UNVERIFIED_NO_REPORT
  before compare_products. No matrix, synthesis call or report was generated.
  Root duration was 36.937 seconds.

## Historical observability limits

SourceDiscoveryService returned candidates, validations, domain scoring,
warnings/errors and discovered page decisions, but the workflow saved only
queries, selected domain and source IDs. The returned FactExtractionResult also
contained provider_calls/candidate/rejection diagnostics, which were discarded.
Child 37 has zero tool audit rows because extraction used an existing run without
an extraction stage/tool owner. Only root tool 117 exists for this workflow.

Consequently Doubao's returned URLs/ranking, rejected identity rules, validation
HTML/redirects and Kimi's model response cannot be recovered from these records.
Claims of an overly strict identity filter, anti-bot response, wrong attribution,
or a particular rejected quote would be speculation. No provider error flag was
recorded for search, but original search responses are absent. Query locale is
the existing en-US default; language is inferred per product (zh/en). Its impact
on this run is unverified.

## Budget and status semantics

| Reservation | Recorded amount | What can be established |
|---|---:|---|
| Search | 6 | Three per product; no discovery error flag. Original response rows are missing. |
| Page GET | 8 | Three before Kimi searches, five afterward. Includes validation and redirect hops; only snapshot 89 has durable response evidence. |
| Model | 2 | Understanding 1, extraction 1; no evaluation/synthesis. Only understanding usage is retained. |
| Tokens | 20088 | Conservative reservation: 6036 understanding + 14052 extraction, not measured usage. |
| USD | 0.018777 | 0.006 search + 0.003161 understanding + 0.009616 extraction reservations, not an invoice. |

No budget was exhausted. At the saved reviewed rates, understanding's retained
usage would cost $0.0003618 assuming cache-miss peak pricing. Actual total billed
cost cannot be reconstructed without extraction usage/account billing; failures
and reserved output are not refunded in the application ledger.

UNKNOWN is the run_mode used to exclude competitive research from historical
baseline tracking. SUCCEEDED means the root tool returned a structured outcome,
not that research succeeded. PARTIAL_SUCCESS is the database mapping of workflow
PARTIAL. analysis_complete=false and report_id=null are authoritative. The
terminal root's phase remains product_research (last reached phase). These
overlapping labels are potentially confusing, but are not evidence of a complete
report. This run did not achieve the user's research acceptance goal.

## Minimal repairs and non-paid verification

1. Persist returned discovery details and bounded search/validation fetch metadata
   in the existing root audit. Persist extraction candidate counts, provider
   HTTP/usage diagnostics, errors and rejection reasons. No new schema or raw
   model-response retention is added; historical Run 36 remains unchanged.
2. Pass already retrieved candidates into page discovery. When homepage navigation
   lacks a dimension, consider same-site results without another search. Reject
   other sites and the homepage as a substitute price page; preserve ambiguity
   and existing navigation priority. Candidates still require the unchanged page
   and evidence validators. No product/domain whitelist is introduced.

The dropped handoff is a code defect: initial feature/pricing searches previously
contributed only to domain selection, while this workflow disables supplemental
search. It is not proof that the missing historical candidate URLs would have
yielded adequate evidence for either product.

544 non-paid tests passed, including persisted diagnostic assertions, model
failure diagnostics, same-site handoff, ambiguity, navigation priority and the
existing workflow/report integration suite. Tests use synthetic providers and a
disposable test database. Snapshot 89 replay is a separate offline check of a
retained real artifact. None is a new live acceptance run.

Still blocking reliable live acceptance: Doubao's exact identity failure is
unknown, and no verified substantive feature/pricing pages were retained for
either product. A narrowly scoped, separately approved diagnostic could repeat
three Doubao searches (at most $0.003 at the reviewed search rate), validate at
most two candidate pages with at most six total GET/redirect hops, and use zero
model calls. It must not automatically create another analysis task. Recovered
current results would be new evidence, not a reconstruction of Run 36.

The repair is ready for review; a successful next live E2E is not established.
No further real requests or paid tests are authorized by this diagnosis.
