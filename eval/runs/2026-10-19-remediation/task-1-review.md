# Task 1 independent review

**Status: APPROVED — no actionable findings.**

Reviewed the assigned brief, report, preserved review diff, audit acceptance criteria B01–B05/B11–B13, and actual current implementation/tests. The current `SavedIn` NaN/Infinity guard was reviewed directly because it postdates the preserved diff. No implementation files were changed.

## Spec compliance

- Shared throttling uses the trusted ASGI peer, stores hashed bucket keys, consumes budgets with atomic database upserts, and cleans expired rows. Coverage includes independent limiter instances, concurrent consumers, and independent processes.
- SQLite connection-level FK enforcement and additive orphan cleanup preserve valid accounts/cards/reset records. Account deletion cascades owned reset/session rows; orphan reset consumption returns a controlled error.
- Reset consumption and credential replacement occur in one transaction. SQLite obtains a write transaction before reading the token; PostgreSQL locks the owning user and conditionally consumes the token. All reset tokens and existing sessions are revoked together.
- Sessions store random-token verifiers rather than bearer tokens, enforce expiry and credential binding, and revoke the current session on logout while preserving other sessions.
- Saved snapshots retain the prior field allowlist and slash-ID contract while adding strict bounded fields, coordinates/URL validation, aggregate UTF-8 size enforcement, and controlled non-finite-number rejection. The frontend snapshot field list matches the accepted schema.
- Photo requests receive an early body cap and bounded upload read; decoding checks pixels before loading, handles Pillow bomb errors, limits concurrent decodes, and runs outside the event loop.
- MCP search/recommend sanitize text before retrieval/model boundaries; the provider spy verifies actual embedding arguments. Telegram expiry runs from a scheduled callback independently of new updates and handles replacement/forget cancellation.

## Code quality and correctness

No concrete changed-code defect or documented-standard violation found. Reviewed reset/session ordering, independent limiter transactions, migration preservation, callback identity checks, photo middleware/decoder boundaries, and test isolation. Root-owned temporal/data/runtime changes were excluded from this review.

## Independent validation

Executed the targeted auth/account-security/photo/privacy/MCP/Telegram suites with provider and SMTP credentials disabled:

```sh
env OPENAI_API_KEY= openai_api_key= LLM_API_KEY= LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= \
  LLM_ENABLED=false EMBED_MODEL=off WEATHER_ENABLED=false \
  SMTP_HOST= SMTP_USER= SMTP_PASSWORD= SMTP_FROM= \
  .venv/bin/python -m pytest ayat_backend/tests/test_account_security.py \
  backend/tests/test_privacy_security.py backend/tests/test_photo.py \
  backend/tests/test_mcp.py backend/tests/test_telegram.py ayat_backend/tests/test_auth.py -q
```

**51 passed in 4.51s; exit 0.** Scoped `git diff --check` also passed.

No provider, SMTP, Telegram, or production database calls were made. PostgreSQL paths received static review only; live PostgreSQL concurrency and the final integrated broad suite remain outside this scoped review. The report correctly discloses old-cookie invalidation and existing fresh-schema initialization limitations.
