# Controlled dynamic rendering feasibility

## Outcome

The first bounded browser experiment did **not** establish reliable rendered
evidence acquisition. Production fetching remains unchanged and no automatic
browser fallback is enabled. No search, model, database write, or full research
workflow was executed.

The project had no Playwright dependency. The local experiment installed
Playwright 1.64.1 and reused the installed Chrome executable with a fresh,
non-persistent browser context. Experimental code, offline tests and raw network
audit are retained locally, outside this repository. Installation does not
activate any production feature.

## Scope and controls

Only `https://www.doubao.com/about` and
`https://www.doubao.com/work/pricing` were approved top-level targets. Resource
hosts were selected from the HTML already retained by the previous diagnostic;
only the target host and three explicit asset hosts were allowed. Images, media,
fonts, telemetry hosts, non-GET requests, popups, downloads, service workers and
websockets were denied. No login, challenge interaction or access-control bypass
was attempted.

Chromium used a dead proxy and disabled DNS. Intercepted requests were fulfilled
through a separate credential-free HTTPS transport: public-IP validation,
connection to the validated IP, TLS hostname verification, no environmental
proxy, no retries, and no imported cookies. Redirects remained intercepted;
top-level destinations outside the two approved URLs were denied.

Configured ceilings were two page attempts, 60 network requests and 20 MiB per
page, two redirects, and a shared 120-request task ledger. Every outgoing GET
reserved one fetch before transmission. The per-page cooperative timeout was
30 seconds; an independent 90-second process-tree watchdog bounded the complete
experiment. **The 30-second timeout did not reliably bound the complete browser
operation.** The outer watchdog was necessary and terminated the process.

## Observed external results

| Target | Actual observation | Evidence outcome |
| --- | --- | --- |
| `/about` | Initial document HTTP 200, 18 additional GET responses HTTP 200; 4,575,018 response bytes in total | No completed DOM capture, final title, final URL, clean-text hash or identity verdict was returned before the watchdog |
| `/work/pricing` | Not started before the global stop | No new pricing evidence or rendering result |

The first page loaded scripts/styles and a same-origin public text resource.
There were 19 network reservations and 19 recorded successful responses, zero
searches, zero model requests and zero provider cost reservations. Blocked
browser request attempts are separate from transmitted network requests. No
second attempt or additional target was launched after the deadline.

The available audit does not locate the exact blocking browser call. Successful
asset delivery is not proof of successful DOM rendering, official identity or
usable pricing evidence. In particular, it does not establish whether blocked
resources were required. No missing DOM or historical response is reconstructed.

## Offline checks

Before the live attempt, 29 tests passed: 16 experimental tests and 13 existing
source-validation/discovery tests. Six cases launched a real local Chrome with
entirely injected offline responses; the rest tested policy and domain logic.
Coverage included delayed DOM insertion, empty content, navigation outside the
allowlist, HTTP denial, network failure, exhausted shared budget, target/page
limits, private and mixed public/private DNS addresses, and existing identity
validation. These are offline checks, not real-site accuracy results.

The first dynamic-DOM test initially exceeded a three-second test budget that
included browser cold start. Its offline budget was corrected to ten seconds.
The passing suite does not establish a hard wall-clock guarantee: the live
watchdog result explicitly disproves readiness on that point.

After retaining the prototype outside the application, the unchanged production
suite passed **548 tests** with a fresh test temporary directory (61.24 seconds;
one existing Starlette/httpx deprecation warning). An earlier full-suite attempt
showed an error and was interrupted; only the completed rerun is counted here.

## Required next work, without further live requests

Before enabling a production adapter, isolate the browser worker behind a
parent-enforced deadline with process-tree cleanup, incremental audit checkpoints
and explicit failure results. Test a deliberately hung worker and teardown,
request/byte exhaustion, redirects and challenge pages offline. Reserve network
allowances in the parent/shared ResearchContext so worker termination cannot
reset or lose consumption. Bound browser memory/process resources as well.

Only after these checks should a separately approved bounded attempt validate
the two pages. Another possible public-evidence route is discovering accessible
official help/product documentation; its availability remains unverified and
additional search requires approval. No retry is scheduled.

If future validation succeeds, RequestsFetcher remains the default. A shared,
opt-in renderer may run once only for JS_UNSUPPORTED, empty content or a detected
shell, never for access denial or a login/CAPTCHA challenge. Its DOM must pass
the existing cleaner, official-source validator and evidence validator. Reuse
FetchPageResult, snapshot hashes/timestamps and existing cache/persistence
services; do not create a parallel crawler or relax source ownership checks.

Kimi may benefit if its useful public content is JS-rendered, but this is a
hypothesis. Its thin chat-entry page and source selection remain independent
blockers. Consumer Doubao, Doubao Work and model API pricing must remain distinct.
Neither a full two-product E2E nor Stage 9.1 reliability acceptance is ready on
the evidence from this experiment.
