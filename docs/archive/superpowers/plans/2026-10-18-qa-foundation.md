# Astana Walk QA Foundation Implementation Plan

> **For agentic workers:** Execute the tasks within the already authorized QA scope; use independent agents for disjoint files and a fresh final reviewer. No Git write operations are authorized.

**Goal:** Deliver useful, reproducible tests before the application exists, without presenting fixtures as product validation.

**Architecture:** Pure validators and metrics form the shared boundary. Offline tests exercise them against deliberately valid/broken synthetic examples; opt-in integration tests and evaluation call the actual application later. A readiness gate exposes absent components and missing evidence.

**Tech Stack:** Python 3.11+, pytest, httpx, jsonschema; no model credentials required for offline checks.

**Spec:** `docs/superpowers/specs/2026-10-18-qa-foundation-design.md`

## Global Constraints

- Do not commit, stage, push, merge or switch branches. Preserve Git HEAD.
- Do not write backend, frontend, RAG or real POI datasets for other roles.
- Never equate fixture checks with real application correctness.
- Use the exact shared interfaces and golden-set shape in the spec.
- Preserve original `team/` documents. Store synthetic POIs under `tests/fixtures/`.
- Do not perform paid model calls or publish external artifacts.

## Review Focus

- Malformed API responses return useful violations rather than crashing the validator.
- Empty successful responses cannot produce a misleading zero-hallucination success report.
- Missing live dependencies are visible skips; readiness still fails.
- Dataset/source facts stay authoritative over generated IDs, statuses and coordinates.
- CLI network, JSON, judge and output errors return nonzero with usable evidence and no secrets.

### Task 1: Contract validators and metrics

**Files:** `eval/validators.py`, `eval/metrics.py`, `eval/schemas/*.json`, `tests/test_validators.py`, `tests/test_metrics.py`.

**Interfaces:** Produce the functions in the spec; schemas follow the team HTTP/POI contracts with documented ambiguity decisions.

- [x] Write independent positive/broken examples; run and observe missing-behavior failures.
- [x] Implement pure schema/semantic checks and metrics.
- [x] Run covering tests; record the outcome and assumptions.

### Task 2: Evaluation, readiness and optional judge

**Files:** `eval/run_eval.py`, `eval/check_readiness.py`, `eval/judge.py`, their `tests/test_*` files.

**Interfaces:** Consume Task 1 functions and the golden-set shape; produce machine-readable and human-readable evidence.

- [x] Write CLI/transport tests proving errors and missing components fail.
- [x] Implement explicit live runner, readiness gate, and opt-in judge without hidden network calls.
- [x] Run covering tests, including controlled HTTP failures and report denominators.

### Task 3: Scenarios and honest submission preparation

**Files:** `eval/golden_set.json`, `docs/test_scenarios.md`, `docs/qa_strategy.md`, `docs/product_concept.md`, `docs/rag_approach.md`, `docs/ethics_privacy.md`, `docs/presentation/*`, `docs/demo_script.md`.

**Interfaces:** Produce golden-set entries consumed by Task 2 and product integration tests.

- [x] Build at least 40 synthetic cases with independently stated outcomes.
- [x] Prepare requirement mapping, integration/limitations guidance and pitch/demo scripts; no fictitious results.
- [x] Validate case shape and documentation against actual CLI behavior.

### Task 4: Integration, independent review and evidence

**Files:** `pytest.ini`, `requirements-qa.txt`, `tests/conftest.py`, `tests/test_api_contract.py`, `tests/test_safety.py`, `tests/test_rag.py`, `tests/test_dataset.py`, `tests/test_golden_set.py`, root `README.md`, `eval/results.md`.

**Interfaces:** Explicit `--live-api` / dataset / RAG options; absent applications never pass a readiness gate.

- [x] Add opt-in tests for API/data/RAG contracts; ordinary offline execution stays network-free.
- [x] Run the whole suite and expected failing readiness command; record precise pass/skip counts.
- [x] Have a fresh agent review spec compliance and code quality, fix significant issues, rerun relevant checks.
- [x] Produce current status and a portable QA archive for the user. Check unchanged HEAD and no staged changes.

## Completion record

QA preparation complete and independently reviewed. Own QA suite: 320 passed, 0 failed, 57 explicitly skipped product checks. Latest whole-repository snapshot: 377 passed, 4 failures in concurrently developed Data, 57 skipped; details and JUnit preserved in eval/evidence and docs/qa_findings.md. This does not mark the application ready. No Git writes; HEAD unchanged.
