# Static evidence acquisition repair

This change keeps RequestsFetcher, the existing cleaner, source validator,
ResearchContext ledger and persistence services. It does not enable browser
rendering, change database schemas, rewrite historical snapshots, or execute a
paid workflow. README and provider fee settings are unchanged.

## Implementation

- `domain/content_cleaner.py`: walk text nodes once in DOM order, including
  div/span/label text; preserve block boundaries and repeated table cells.
  Remove template tags, explicit hidden/aria-hidden/inline-hidden elements and
  unconditional embedded CSS hiding rules. Only adjacent duplicate paragraphs
  are collapsed; nonadjacent text is not selected and stitched together.
- `domain/webpage.py` and `services/snapshot_service.py`: new snapshots use
  `deterministic-html-v2`. Historical rows remain untouched.
- `services/fact_extraction_service.py`: page cache keys use a new namespace and
  the snapshot's cleaner version, even when two versions produce identical text.
  Cache reuse still requires the existing completed, successful extraction audit.
- `infrastructure/http/requests_fetcher.py`: explicit HTTP charset takes priority;
  otherwise use BOM, an HTML encoding declaration, or strict UTF-8. Requests'
  implicit Latin-1 default is not a declaration. Unsupported/invalid decoding
  remains a failed fetch rather than replacement-character repair.
- `domain/source_discovery.py`, `domain/sources.py` and
  `services/source_discovery_service.py`: merge navigation and existing search
  candidates. Prefer dedicated product/docs/help/tour/pricing routes over audience
  pages; exclude news/changelog/login routes from feature and pricing candidates.
  Retain two ranked candidates per dimension. Validate identity, nonempty content,
  pricing applicability and final-domain ownership before saving. Equal-ranked
  valid alternatives remain ambiguous. Failed/empty/shell candidates can fall
  back within the shared budget; access denial does not trigger bypass.
  Identity discovery may inspect at most two pages per candidate domain, only
  falling back when the first is unusable. Already fetched pages are reused.
- `infrastructure/http/public_session.py` and `budgeted_transport.py`: default
  production fetch transports validate all DNS answers as public, reject mixed
  public/private responses, and connect to a validated numeric IP with original
  TLS SNI and certificate hostname verification. No second hostname resolution
  occurs at connection time. Credentials, cookies, inherited proxies and netrc
  are not imported. Only HTTP/HTTPS on their default ports are allowed. Redirects
  are manual and bounded; each hop uses the same checks and shared reservation.
  Requests' implicit redirect-body consumption is disabled. Search/model POST
  transports and their cost policies are unchanged.

These are static rules, not a CSS layout engine or semantic product classifier.
External/conditional CSS visibility is not guessed. Content applicability and
official ownership are candidate gates, not confirmation of individual facts.
Every candidate fact still passes the unchanged evidence validators. Explicitly
injected offline test transports are trusted test seams, not production egress.

## Local offline replay

Six previously captured pages were replayed through RequestsFetcher using injected
response bytes, then the production cleaner and official validator. Trello's
previous Latin-1-decoded capture was reversibly reconstructed to response bytes;
no characters were heuristically replaced. No new HTTP request, search or model
call occurred. Raw captures and replay outputs remain outside the repository.

| Page | Previous clean characters | v2 characters |
| --- | ---: | ---: |
| Linear homepage | 2,548 | 9,150 |
| Linear docs | 897 | 897 |
| Linear pricing | 616 | 2,308 |
| Trello homepage | 869 | 788 |
| Trello tour | 2,728 | 2,733 |
| Trello pricing | 9,665 | 6,461 |

All six retained page-level VERIFIED identity results. The saved Linear pricing
markup now preserves Basic/Business amounts, per-user monthly units and yearly
billing text. Trello retains plan names, USD, primary amounts and annual/monthly
conditions in order. Reduced Trello length reflects hiding/noise removal and
correct decoding, not loss of the primary pricing blocks. Functionality text
remains available in the docs/tour pages. These are replay observations, not
model-confirmed or newly persisted facts and not current price quotations.

Offline homepage discovery now selects Linear docs and Trello tour for FEATURES,
and both pricing pages for PRICING. This does not prove future live Serper
results, domain aggregation or model extraction will succeed.

## Verification and remaining boundaries

Tests cover nested price contexts, intervening text preservation, hidden content,
repeated table cells, encoding precedence, private/multicast/mixed DNS rejection,
TLS IP pinning, redirect revalidation, credential removal and shared budget
exhaustion. Disposable-database tests cover source fallback, tied ambiguity,
cross-domain refusal, identity fallback, and cleaner-version cache isolation.
Existing report/workflow tests remain offline, using injected providers.

Final full non-paid regression: **581 passed** in 51.49 seconds, with one existing
Starlette/httpx deprecation warning. Database integration tests used the disposable
test database. No production migration or historical-data write was performed.

After approval, one user-submitted Linear/Trello run is reasonable. It must still
use real search and models and preserve partial-result status. Missing currency,
region, tax or billing evidence must not be invented to support a cheaper/better
claim. Page identity and readable text alone do not establish factual extraction
accuracy. No full E2E or Stage 9.1 reliability acceptance is claimed here.
