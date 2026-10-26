# Evidence-bound report quality improvements

## Observed failure chain

Run 38 produced report 9 with 17 confirmed facts (9 for the target, 8 for its
competitor). All 17 facts and their observation links reached the matrix. The
report remained partial; the data did not support a price ranking.

- Feature comparisons required exact normalized-name equality. Different names
  for AI, automation and integrations were reported as one-sided evidence.
- The synthesis provider selected existing finding IDs; it could not repair
  missing comparison structure. Its successful response was prioritization, not
  newly authored research or independent confirmation.
- Two paid-plan candidates were rejected at `billing_commitment`: the quote
  contained `Billed yearly`, absent from the annual-billing alias lists in both
  grounding layers. This is a confirmed lexical false rejection. Adding that
  explicit synonym does not supply currency, region or tax information.
- A custom enterprise plan was rejected as `CONTACT_SALES` without that explicit
  wording in its selected quote. That rejection remains correct.
- The competitor's two pricing candidates returned the same final URL and
  cleaned body. The service counted them as two competing candidates, classified
  pricing as ambiguous and never sent a pricing page for model extraction.
  This was source selection failure, not a pricing-model rejection.
- Distinct equal-score feature pages still remain ambiguous. Resolving general
  multi-page source selection is outside this small repair.

The rejected full model objects were not retained. Diagnostic fields and quote
snippets prove the annual-billing rejection, but cannot reconstruct every other
field of those original candidates. No rejected historical candidate is promoted
to a confirmed fact by this repair.

## Compatible implementation

`AnalysisTaskSpec.output_language` adds an optional `zh-CN` / `en` presentation
preference, with `en` as the legacy default. Task understanding applies an explicit
output-language request or the input-language default. Existing JSON storage is
sufficient; no SQL schema migration or historical update is needed. Stored legacy
task scopes are normalized for idempotency checks.

`comparison_presentation.py` builds a reading view from the existing validated
matrix. A small product-independent vocabulary maps quoted feature names to
capability categories. Every category retains fact and evidence IDs. Unmatched
features remain visible. Shared categories require all compared products, matching
observation dates and no source conflicts or known availability restrictions.
They do not imply equivalent implementations or complete capability coverage.

Generic action annotations retain their exact supporting quote spans. They are
reading aids, not new product facts. Source quotations, original fact values,
URLs, timestamps and IDs are preserved. Chinese headings, comparison boundaries,
glossary annotations and rule-bound analysis are supported; arbitrary English
source descriptions are intentionally not machine-translated in this offline
release. Full narrative translation still requires a separately approved,
evidence-reviewed model evaluation.

The findings planner now supplies shared-category implementation comparisons to
the existing bounded synthesis selector. It keeps all price comparability gates
and does not allow free-form model claims. The reading view exposes scope,
capabilities, plans, constrained differences, conclusions, references and gaps.
It is persisted alongside the original matrix for future reports. Markdown and
the formal report/Chat-first pages consume the same persisted view. Legacy
reports are displayed unchanged; technical details are expandable.

The annual-billing alias repair changes the fact-provider policy cache version.
Verified source aliases collapse only when final URL and cleaned content match;
different pages or content still require disambiguation. Request budgets and
identity validation are unchanged.

## Verification and remaining acceptance

Offline replay rechecked the 17 persisted facts through the matrix repository and
evidence validator: all facts and all 17 evidence records were retained unchanged.
Three shared categories were recovered without new network requests. Original
report 9 remains immutable. The locally generated Chinese sample is explicitly
labelled offline regeneration, not a new agent run, and is not published here.

Regression tests cover semantic grouping, conflicts, different observation times,
partial coverage, exact quote-span annotations, explicit yearly billing versus
missing/monthly evidence, same-final-page aliases versus distinct pages, output
language, and isolated report persistence/API/Markdown equivalence. Integration
tests use disposable `_test` databases and injected providers.

Remaining limits: historical paid-plan candidates cannot be recovered fully;
missing pricing facts stay missing; source currency/region/tax gaps still block
price rankings; semantic vocabulary is conservative and finite; generic scenario
recommendations require user requirements and fuller comparable evidence.
Improved synthesis prioritization and fully translated prose have not been
validated with a new real model response. No new paid E2E was executed.

Validation: full offline regression 598 passed; final affected-area check 64 passed.
JavaScript syntax checks passed for both formal report and chat scripts. The
existing Starlette/httpx deprecation warning remains. No live provider was called.
