# Bounded official-identity diagnostic

This diagnostic is separate from Run 36 and from the competitive-analysis
workflow. Three real Serper searches and two page checks consumed three HTTP GET
requests including one redirect. There were zero model calls, zero new agent
runs and no production database writes. Search reservation: $0.003 at the
reviewed rate, excluding tax and account-level purchases. Raw search responses,
page artifacts and request metadata remain outside Git.

## Observed evidence

Queries were `豆包 官网`, `豆包 功能`, `豆包 定价`, with hl=zh, gl=us and num=10,
matching the prior workflow configuration. All three search responses were HTTP
200. Examples from the recorded rankings:

| Query | Rank | Candidate |
|---|---:|---|
| Official site | 1 | https://www.doubao.com/about |
| Official site | 2 | https://www.doubao.com/ |
| Features | 1 | https://www.doubao.com/ |
| Features | 3 | https://www.doubao.com/work |
| Features | 6 | https://www.53ai.com/news/neirongchuangzuo/2024103075290.html |
| Features | 9 | https://www.doubao.com/about |
| Pricing | 1 | https://www.doubao.com/work/pricing |
| Pricing | 2 | https://www.doubao.com/about |

These URLs are candidates, not verified product facts. Consumer subscription,
work-product pricing and model API pricing must not be conflated.

The existing selector retained doubao.com candidates but chose the shortest root
path over the higher-ranked about page. Root returned 302 to /chat/, which
returned HTTP 200. RequestsFetcher classified it JS_UNSUPPORTED with
PROBABLE_JS_SHELL and deliberately returned no raw HTML/clean text to the caller.
The diagnostic therefore retains status/redirect evidence for this page, not a
recoverable full HTML body. No access-control bypass or JavaScript execution was
attempted.

The domain aggregate had score 9.0, margin 4.5, ten retained results and three
query-type categories. Page metadata support was zero. Selection remained
PENDING_CONFIRMATION because successful page identity evidence is required.
That rejection is appropriate for the selected shell; the confirmed selection
defect is preferring an app entry over a returned identity-information candidate.
The about page was not fetched in this authorized two-page diagnostic, so its
contents and eventual verification result remain unknown.

The second selected page was a 53AI tutorial: HTTP 200, 5894 cleaned characters,
title describing a guide to Doubao. Its copyright notice names the publisher,
not Doubao. The old single-page validator incorrectly combined the product name
anywhere in the HTML with a copyright marker anywhere else, and also treated an
article's own canonical plus product title as ownership evidence. It returned
VERIFIED. Domain aggregation did not select this domain (score 4.5, no homepage
support). This is a false-positive ownership defect, not a reason to loosen
identity verification or accept the article as official product evidence.

This new observation explains a reproducible failure path. It cannot establish
that Run 36 saw identical search results or redirects: those historical details
were not retained.

## Minimal generic changes

- Within each already grouped domain, prefer brand-labelled about/about-us/company
  candidates, including locale prefixes, before the shortest path. No domain
  whitelist, extra request or threshold reduction. Missing/unbranded about pages
  retain the previous ordering. This affects identity representative selection
  for every product; it does not verify the selected page automatically.
- Limit brand-copyright support to a bounded local copyright notice. Ignore script
  and style strings. News/blog/article pages without brand-domain or local
  brand-copyright ownership remain pending rather than using title/canonical
  alone. Official branded editorial pages remain eligible under existing checks.

Offline replay of the retained 53AI artifact now returns PENDING_CONFIRMATION.
Offline ranking of retained search results now selects /about. Neither replay
performed a new web request or establishes that /about contains useful facts.

Full non-paid regression: 548 tests passed (one existing Starlette/httpx
deprecation warning). Added cases cover branded/unbranded about selection,
third-party article rejection and legitimate branded editorial ownership.

## Kimi and next gate

No Kimi request or model call was made. Run 36's retained /en snapshot contains
74 cleaned main-content characters. The old pipeline preferred short homepage
representatives, always included the homepage as a research page, and discarded
initial feature/pricing search candidates before page discovery while disabling
supplemental search. Commit 2b7de89 repairs that handoff. The historical alternative
Kimi URLs are unavailable, so there is no evidence that a specific richer page
would have passed validation. Navigation labels alone are not feature or price
facts. Reuse same-site research candidates, validate their bodies and distinguish
pricing scope; do not replace missing facts with menu text or model knowledge.

Full real E2E readiness remains unproven. A next separately approved check can use
zero searches and zero models to inspect the already returned /about and
/work/pricing candidates, with at most two pages and four GET/redirect hops.
The latter must be labelled as work-product pricing, not assumed to describe all
Doubao consumer offerings. No such follow-up was executed here.
