# Backend QA tests implementation plan

**Goal:** Extend the existing QA suite against `team/04_qa_docs.md`, retaining its scenarios, validators and explicit evidence limits.

**Spec:** `team/04_qa_docs.md`, `team/README.md` section 3, existing `eval/golden_set.json`.

**Architecture:** A test-only fixture runs the actual FastAPI app in process with a temporary POI file and disabled external providers. Existing golden expectations and response validators judge its visible behavior. Separate tests instrument the provider boundary and inspect the actual collected dataset.

**Constraints:** Work on `Aslan`; no commits or pushes. Preserve `data/` bytes and existing tests. Only QA files change. Do not fix production code or weaken requirements to conceal failures. Local keyword fallback and synthetic provider replies do not prove real RAG, model quality, multilingual prose quality or production readiness.

## Tasks

- [x] Add isolated `qa_backend` to `tests/conftest.py`: actual app and POI loader, temporary fixture, cleared response/settings/client caches, empty provider keys; expose `client`, `pois`, `set_pois()` and instrumentable modules. Teardown must restore test state.
- [x] Run the existing 64 golden requests through the actual local API in `tests/test_backend_golden_local.py`. Keep original outcomes and validators; distinguish contract defects from missing fixture coverage.
- [x] Add provider-bound privacy, poisoned retrieved text, response allowlist/factual integrity and failed-provider tests in `tests/test_backend_safety_local.py`; reuse `tests/fixtures/poi_injection.json`. Make representative tests fail under test-only weakened guards to demonstrate sensitivity.
- [x] Extend dataset checks and add `tests/test_backend_dataset_local.py`: exact administrative polygon, provenance, description attribution, quarantine separation, actual loader/map/recommendation behavior. No dataset mutation or artificial record cap.
- [x] Execute the new tests and the full existing suite. Retain truthful failures with reproductions and requirement references in `docs/qa_findings.md`; document commands and evidence limits. Do not turn unavailable model/UI/RAG integrations into successful checks.

## Verification

`.venv/bin/python -m pytest tests backend/tests data/tests --pois data/processed/pois.json --live-backend -q`

`.venv/bin/python -m pytest tests/test_backend_golden_local.py tests/test_backend_safety_local.py tests/test_backend_dataset_local.py --pois data/processed/pois.json -q`

Record test counts, failing node IDs, dataset hash and test scope. Confirm the collected POI file hash is unchanged.

Completed: 549 passed / 42 failed / 40 skipped. Failing assertions are retained and diagnosed; production fixes are outside this QA task. Evidence: `eval/runs/2026-10-18-backend-local/`. All 367 backed-up Data files and the golden set remain byte-identical.
