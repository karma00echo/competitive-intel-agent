# Project instructions

## Scope

This repository implements the Universal Competitive Intelligence Agent.
Keep the product name as the only required user input. Do not require users to
provide website URLs.

## Architecture boundaries

- Use one controlled main agent. Do not introduce a multi-agent architecture.
- Search, official-source validation, and source discovery are separate tools.
- Web fetching, cleaning, fact extraction, comparison, and report generation
  must not access MySQL directly.
- All database reads and writes go through `competitive_intel.persistence`
  repositories.
- Database transactions are owned by the application layer through
  `Persistence.transaction()`.
- Facts without source URL, evidence text, collection time, and confidence
  cannot become confirmed facts.
- A failed page fetch is an unknown comparison result, never an unchanged page.

## Development

- Target Python 3.12.
- Keep tests offline by default except tests explicitly marked `integration`.
- MySQL integration tests must use a disposable database whose name ends in
  `_test`.
- Never commit `.env`, credentials, captured secrets, or production snapshots.
- Do not proceed to the next development phase while the current phase has
  failing tests.

