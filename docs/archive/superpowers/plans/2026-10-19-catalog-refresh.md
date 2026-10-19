# Whole-catalog enrichment implementation plan

> **For agentic workers:** Use `subagent-driven-development` and TDD. Preserve the dirty worktree; no commits, pushes, paid subscriptions or external messages.

**Goal:** Enrich and audit all catalog records, publish source-bound facts and service information, and ensure recommendations respect explicit user requirements.

**Architecture:** Retain canonical source records and immutable snapshots. Add hash-bound rich-place facts and a typed city-service catalog; keep web observations separate from accepted facts. Apply reviewed exclusions to the active view, rebuild aligned retrieval data, and render facts deterministically.

**Tech stack:** Existing Python/httpx/BeautifulSoup/Pydantic/pytest, FastAPI, React/Vitest, local BM25/e5.

**Spec:** `docs/data_refresh_scope_2026-10-19.md` plus the user's subsequent explicit authorization: prices and RedBus service routes are now included, execution is authorized, incomplete/no-information records must be counted.

## Global constraints

- Target: 2026-10-20 10:00 Asia/Almaty. Report actual coverage; never equate attempted checks with confirmed facts.
- Global external LLM/embedding budget remains USD 0.10; known prior spend USD 0.0237488. This work uses free public sources and local processing.
- Branch identity and source/date/validity evidence are required for accepted data. HTTP errors, blocked pages and absent search results cannot prove closure.
- Missing individual attributes remain unknown. User-authorized exclusion after no information requires a completed source search; incomplete checks are separate.
- Existing quarantine, immutable source IDs, flight buffers and privacy/SMTP policies persist.

## Review focus

- Same-brand/wrong-address matches and operator office mistaken for boarding location.
- Menu URLs, average checks and delivery prices mistaken for exact dine-in dish evidence.
- Old dated schedules, conflicting official pages, absent/false values and source failures.
- Explicit constraints lost without a model, during model merging or on conversational follow-up.
- Exclusions missing from indexes/gazetteer or resurrected by a later refresh.

## Task 1: Full-catalog source audit

**Files:** `data/catalog_audit.py`, `data/tests/test_catalog_audit.py`, `eval/runs/2026-10-19-catalog-refresh/source-audit/`.

**Interface:** One row result per canonical ID, deduplicated fetch ledger/cache, source candidates with explicit identity evidence, exact coverage counts and resumable CLI.

- [ ] Red/green tests for failed fetch versus no evidence, branch identity, duplicate URLs, resumability and network bounds.
- [ ] Fetch available public websites; audit every record and record unavailable source access separately.
- [ ] Produce incomplete-field and no-confirmation counts by category, with machine-readable row evidence.

## Task 2: Accepted rich-place facts

**Files:** `data/place_details.py`, `data/tests/test_place_details.py`, `data/sources/place_details_2026-10-19.json` and evidence records.

**Interfaces:** `load_place_details(path, canonical_sha256=..., as_of=...) -> mapping`; `apply_place_details(rows, mapping) -> copied rows`; accepted record appears as `row['place_details']`.

- [ ] Red/green schema tests for hash/identity/provenance/date/conflict checks and separate price channels/units.
- [ ] Gather real branch-specific menu, price and useful visit facts from public primary/merchant sources; preserve unsupported gaps.
- [ ] Integrate approved candidate evidence only after identity and source review.

## Task 3: City services

**Files:** `data/city_services.py`, `data/tests/test_city_services.py`, `data/sources/city_services_2026-10-19.json`.

**Interface:** Typed operator/service/routes/stops/ticket offers/dated departures with aliases, evidence and validity; exact-date departure helper.

- [ ] Red/green tests for invalid/undated schedules, conflicts, boarding versus pass-by roles and fares.
- [ ] Collect RedBus and other verified city activities. Keep unknown current departures unknown.

## Task 4: Runtime evidence matching and presentation

**Files:** query/retrieval/service/schema/i18n/store/team-data helpers, a focused evidence matcher and service-answer module; corresponding tests; frontend API/cards/context.

- [ ] Reproduce the EXPO mashed-potatoes/cutlet/cheap failure; prove generic cafes and unrelated or delivery-only menus cannot satisfy it.
- [ ] Preserve food requirements across rules/model fallback and match them to accepted evidence before selecting or routing places.
- [ ] Return source-backed service answers/cards, correct boarding/ticket distinctions and honest schedule uncertainty.
- [ ] Preserve location/service context for relevant follow-ups while explicit new choices win.
- [ ] Publish facts, menu/prices and source links in cards; retain existing general discovery behavior.

## Task 5: Publication, verification and report

- [ ] Bind new sidecars and their readers into snapshot/index validity and refresh retention; validate corrupted/missing artifacts with regression tests.
- [ ] Archive exclusion decisions, publish a consistent local snapshot and aligned BM25/dense view.
- [ ] Run relevant suites and full existing integration checks, frontend tests/build; independently review the new delta.
- [ ] Deliver Markdown/JSON report with exact incomplete/no-confirmation/closed/incomplete-check counts, additions, exclusions, evidence and remaining limitations.
