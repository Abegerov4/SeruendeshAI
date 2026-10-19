# Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Close every actionable defect in the 44-item audit, implement honest mechanisms for data/verification gaps, and mark only evidence-backed items closed.

**Architecture:** Ayat is the primary UI runtime; the original backend remains a separate photo/MCP/Telegram service. Deterministic code owns facts, eligibility, time and sources; generation owns phrasing. Both consume a reviewed canonical snapshot with version-bound evidence.

**Tech Stack:** Existing Python/FastAPI/SQLAlchemy/SQLite/Postgres, BM25, optional local embeddings; React/Vite, Docker and GitHub Actions.

**Spec:** `docs/backend_model_data_audit_2026-10-19.md`, explicitly authorized for implementation by the user on 2026-10-19.

## Global Constraints

- Preserve all pre-existing dirty integration work; stay in the existing linked `big-data` worktree. No commits/push/merge/deployment without instruction.
- User approved Ayat as primary, original backend separate. Flight buffer: domestic 120 minutes, international/unknown 180, excluding road time and travel uncertainty.
- Total external LLM/embedding spend must not exceed USD 0.10. No real email without a supplied test recipient. No secrets in output or evidence.
- Do not invent facts, clear uncertainty flags without evidence, force ambiguous matches, or silently weaken original tests. Frozen evaluation sets and canonical source IDs survive.
- Meaningful behavioral regressions use failing tests first, then minimal implementation; ordinary docs/config changes need runnable validation, not source-text mirror tests.
- All tasks report exact commands/results, changed files, audit IDs resolved and remaining real-world prerequisites. Final status must distinguish code fix from live verification.
- Root owns shared config additions, deployment/CI/evaluator files and report updates. Workers own disjoint files below; cross-owner changes are requested, not silently made.

## Review Focus

- Existing accounts/cookies/SQLite databases must migrate safely; logout/reset/restart semantics verified against real temporary storage and concurrent consumers.
- Opening intervals across closing, midnight, route permutations and flight meanings must agree with final card numbers and uncertainty.
- Missing/false/conflicting facts cannot become positive claims because of LLM text, target preference or fallback.
- Failed/partial collection and interrupted promotion must preserve a complete usable version and all provenance.
- Clean checkout/container/current UI must use identical eligibility, API, snapshot and declared runtime evidence.

## Task 1: Accounts, shared throttling, safe uploads and privacy boundaries

**Files:** Own `ayat_backend/app/auth.py`, `ayat_backend/app/db.py`, new `ayat_backend/app/limiting.py`, limiter-only changes in `ayat_backend/app/main.py`; `backend/app/vision.py`, photo-only `backend/app/main.py`, `backend/mcp_server/server.py`, `backend/telegram_bot/bot.py`; relevant new tests. Do not edit shared config.py; send required settings to root.

**Interfaces:** Keep current HTTP auth/saved contracts, slash IDs, `init_db()` and dependency session APIs compatible. Server-side sessions with hashed random token verifiers and expiry/revocation. A shared storage-backed throttle uses trusted `request.client`, not raw XFF; bounded TTL storage. Existing tests using `_attempts.clear()` may be adapted to proper isolated fixtures without weakening behavior.

- [ ] Add failing regressions for B01–B05: spoofed XFF, storage shared across limiter instances, expiry cleanup, FK deletion, orphan reset controlled error, all reset-token revocation, concurrent single consumption, logout replay, oversized/mistyped snapshot.
- [ ] Implement transaction-safe storage/session/reset/throttle semantics, SQLite FK and orphan cleanup; validate saved fields and byte limits without breaking valid cards.
- [ ] Add failing B11–B13 cases: bounded image read/pixels/bomb error, MCP PII at provider boundary, Telegram cleanup without a new update.
- [ ] Implement bounded decode off event loop, common existing PII sanitizer and real scheduled TTL cleanup.
- [ ] Run targeted auth/photo/MCP/Telegram suites; report audit mapping and migration behavior. No real providers/SMTP; no commits.

## Task 2: Temporal correctness and deterministic route ownership

**Files:** Own `ayat_backend/app/service.py`, `planner.py`, `hours.py`, `retrieval.py`, `query.py`, `schemas.py`, temporal strings in `i18n.py`; `backend/app/pipeline.py`, `routing.py`, `cache.py`; regression tests. Root edits generation separately; coordinate interface.

**Interfaces:** Planner owns route visits; final route cards use the planner timeline. Root will change Ayat `generate.validate()` to clamp within allowed range; worker additionally forces fixed route visits from timeline. Flight kind must distinguish departure vs airport-arrival, domestic/international/unknown, user-approved 120/180/180 buffers plus separate configurable road uncertainty. Send shared config requirements to root; defaults must work absent settings.

- [ ] Add failing B06–B10/M02/M04 cases: exact `now` cache, arrival/visit closing, midnight, per-stop route intervals, target filters, matrix destination snap, final route127 vs advertised90, separate flight meanings/types.
- [ ] Implement exact temporal validation with no 10-minute opening cache collision; one final duration per route stop, consistent summary, total, return and deadline.
- [ ] Apply mandatory accessibility/dark/cold/indoor/kids constraints to targets; include both snaps and label uncertainty/fallback honestly.
- [ ] Support hours field provenance passed by data task through `hours_source`/`hours_source_url`; derive suffix from actual source, not constant OSM. Unknown hours stay unknown even for public-space categories unless source proves access hours.
- [ ] Run focused unit/API/golden/route suites, preserving original assertions unless approved flight policy intentionally changes expected outcomes. Report tests and audit IDs; no commits.

## Task 3: Data safety, common eligibility and source provenance

**Files:** Own `data/collect/*`, `data/run_pipeline.py`, new `data/snapshot.py`/`data/eligibility.py` if useful, `rag/retriever.py`, `backend/app/rag_adapter.py`, `ayat_backend/app/team_data.py`, `store.py`, `ayat_backend/pipeline/events.py`, related tests and review artifacts. Do not edit temporal `hours.py`/service/planner; send required interface adjustments to Task2/root.

**Interfaces:** Expose common canonical eligibility and conflict-safe facts to both runtimes without destructive removal of source records. Legacy files remain supported. Snapshot generation uses staged immutable bundles with quality gates and atomic promotion; callers resolve one selected version, or explicitly run legacy fixed files. `hours_source`/URL/dates come from actual field-level evidence.

- [ ] Add failing D01/D02 tests for partial3→1 publication and faults on every promotion stage; implement staging, completeness/loss gates, manifest file hashes and atomic pointer.
- [ ] Add failing M05/M06/I11 tests: five review exclusions in both candidate pools, conflicting hours unknown, search/map/lookup from one version; implement shared normalized-ID policy and version-bound loaders.
- [ ] Add failing D03/D04 tests: same-name chain order independence/unresolved match and real hours-source labels/provenance; preserve original venue/candidate evidence.
- [ ] Implement D05–D10 mechanisms: scenario curator/review queues with field evidence/freshness/license status, suspicious classification policy, duplicate review decisions and graph-coverage diagnostics. Do not assert all unknown facts verified or all candidate pairs duplicates.
- [ ] Produce reproducible current data-quality/review artifacts and tests; preserve canonical source IDs and frozen golden. No online collection, no mass text/category invention, no commits. Report what still needs source/human checks.

## Task 4: Model failure and grounded final explanations (root)

**Files:** `ayat_backend/app/llm.py`, `generate.py`, `backend/app/generate.py`, tests; configuration fields after worker coordination.

- [ ] Add failing real SDK MockTransport incomplete/refusal/schema-invalid tests; handle parsing failures within total deadline and deterministic fallback.
- [ ] Add failing false-facility/event/source model-output tests for both runtimes; server-generated evidence-bound explanations for critical facts, model text cannot elevate source confidence. Clamp duration without1.5 expansion; Task2 enforces route timeline.
- [ ] Create explicit source/fact confidence contract; ensure no generated claim is displayed as verified POI evidence by UI.
- [ ] Run real local tests then independent review before task closure.

## Task 5: Runtime delivery, refresh, CI, evaluation and readiness (root)

**Files:** Dockerfiles/compose/.dockerignore, workflows, scripts, evaluator/readiness/provenance, main health after Task1, frontend API metadata, requirements/docs.

- [ ] Fix root compose to primary Ayat UI plus explicit secondary profile; build/copy frontend and required review files. Validate configuration and clean image if Docker is available.
- [ ] Refresh canonical active data using corrected module/cwd and Task3 snapshot promotion; freeze/hashes policy; do not silently rebuild only unused legacy JSONL.
- [ ] Replace unittest-only CI with full pytest/real snapshot local integrations; frontend tests/build and container smoke; update branch/path triggers.
- [ ] Add failing evaluator semantics/exit/provenance tests; final budget=sum visits+legs+return, failures count and nonzero exit, runtime-specific source/index/review hashes.
- [ ] Separate configured/verified/degraded health with bounded cached provider probe and runtime/snapshot identity; template readiness does not imply model readiness.
- [ ] Repeat all project tests/build, fresh BM25 benchmark, local live HTTP/UI and restart persistence tests; record immutable evidence.

## Task 6: Canonical dense, independent evaluation, live integrations and closure ledger

**Files:** canonical embed/index builder, eval dataset/holdout tools, staging smoke scripts, `docs/audit_remediation_2026-10-19.md` and item-by-item status table.

- [ ] Build ID/document/model/hash-aligned canonical index; use a local provider with no external spend if available. Reject stale/permuted index; compare frozen baseline and independent holdout without changing old labels to force success.
- [ ] Verify remaining retrieval misses through source-backed aliases/semantic matching, never inferred facts such as quietness.
- [ ] Live LLM calls only under the USD0.10 hard budget, recording model/usage/max bound; if account access/budget cannot support a claim, preserve NOT_VERIFIED and ask for the exact prerequisite.
- [ ] Exercise weather/maps/SMTP/Postgres/Docker only where available and authorized; local mock proves handling, not live delivery. Ask for missing real test recipient/deploy target when dependent work is concrete.
- [ ] Fresh independent whole-change review, targeted fixes, complete checks; mark each B/I/M/D item fixed, verified, mitigated or explicitly pending with evidence and required input. Never claim all44 fully closed if real facts/providers remain unknown.

## Coordination and approval record

The user requested implementation of the complete audited description and answered the material runtime/flight/budget questions. No separate redundant design approval is needed. Task1/2/3 have disjoint file ownership and run in parallel under the developer's proactive delegation instruction; file/interface collisions are resolved before edits. Root integrates shared config and delivery after workers finish. Review is against a captured current-tree baseline, not HEAD (which would mix earlier integration changes).
