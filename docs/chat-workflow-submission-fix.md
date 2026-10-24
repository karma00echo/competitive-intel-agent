# Chat workflow submission: 422 diagnosis and regression

The first user-submitted live acceptance attempt reached
`POST /api/analyst/workflows` and returned HTTP 422. Production remained at
35 runs, 116 tool calls and 8 reports, with no RUNNING task. No root run was
created and the workflow/provider path was not entered. This attempt produced
no model/search usage or partial report. It is a failed submission, not a passed
live E2E test. The paid-enabled service was stopped before repairs.

## Evidence and root cause

The original access log records the 422 but does not retain a request-body capture
or full validation traceback. The following type-level diagnosis was reproduced
offline using the shipped JavaScript and FastAPI request validation; it is not
claimed to be an archived original browser network trace.

The natural-language fee-confirmation handler in `web/static/chat.js` passed a
JSON-stringified body without `Content-Type: application/json`. The shared
`api()` helper in `web/static/app.js` forwards options unchanged. Fetch therefore
uses `text/plain;charset=UTF-8` for this string body. FastAPI passes raw `bytes`
to validation of `WorkflowRequest` in `api/analysis_workflow.py`, which expects
an object containing `text` and `allow_paid`. The reproduced validation error is
`model_attributes_type`, location `body`, with the exact message:

> Input should be a valid dictionary or object to extract fields from

Validation fails before `start()`, task preparation or AnalysisTaskSpec/model
execution. Existing TestClient tests used `json=`, which automatically adds the
correct header and consequently missed the browser wire-contract defect.

## Minimal repair and verification

- Set the JSON header on this specific confirmation request.
- Guard the confirmation callback with conversation revision and `record.started`
  before any asynchronous work, in addition to disabling the button.
- Retain the persisted started/uncertain state: no automatic POST retry after a
  timeout, reload or conversation replay. A new explicitly created task is still
  a new request; this is not a general server-side idempotency-key API.
- Bump the chat script cache version so the fixed handler is loaded.
- Execute shipped app/chat JavaScript against a synthetic DOM and intercepted
  Fetch boundary, verifying fee consent, closed readiness gate, double callback,
  lost response and reload. No external network is used.
- Replay its captured headers/body into FastAPI: reproduce the old raw-bytes 422,
  reject absent consent and invalid types, and accept the fixed request exactly
  once. No schema/model validation is weakened.
- Feed the same frontend wire path into the existing disposable-MySQL workflow
  integration test, with synthetic research providers, through report export.

These tests are non-paid regression evidence, not real provider E2E acceptance.
The next live attempt requires separate user approval and a fresh service start;
the previous failed conversation must not be silently reset or resubmitted.
