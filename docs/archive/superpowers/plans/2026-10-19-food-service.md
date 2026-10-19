# Confirmed Food Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Confirm meal budgets and service times from exact-branch evidence while improving actual affordable-menu coverage.

**Architecture:** Extend existing place_details evidence with optional cost and serving-hour assertions. Compute totals on the server and filter known unavailable kitchens at arrival; keep base prices and unknowns visible. Publish reviewed source additions against the immutable master and offline index.

**Tech Stack:** Python, Pydantic, Decimal, pytest, React, existing Node tests, local e5-small.

**Spec:** docs/superpowers/specs/2026-10-19-food-service-design.md

## Global Constraints

- Facts must identify the exact branch, with URL, quotation and date; unknown fees are not zero.
- A dine-in hard budget requires a complete cost statement for one offering; delivery prices never prove dine-in costs.
- Preserve the canonical master, source IDs, other agents' work and existing factual safeguards.
- No paid API calls; the global USD0.10 cap and disabled SMTP remain in force.
- Commit and push big-data is authorized; never force push. Coordinate immutable publication with catalog_refresh_review.

## Review Focus

- Unknown or stale fee evidence must not become a confirmed affordable meal.
- Fees/minimums apply to the same one-offering price and currency; booleans/NaN/infinity/unsupported units cannot form totals.
- Venue hours, kitchen hours and menu serving hours must remain independent, including overnight and estimated arrival boundaries.
- Conflicting or wrong-city sources must not change exact-branch facts or manufacture closure.
- New data must not drop existing full menus, service facts or atomic index consistency.

### Task 1: Evidence, totals and service-window filtering

**Files:** data/place_details.py; new data/meal_cost.py; ayat_backend/app/evidence.py; ayat_backend/app/food.py; ayat_backend/app/retrieval.py; ayat_backend/app/planner.py; ayat_backend/app/service.py; data/tests/test_place_details.py; new ayat_backend/tests/test_food_service.py; ayat_backend/tests/test_food_requirements.py.

**Interfaces:** consumes existing Evidence/MenuItem. Produces validated optional menu cost/serving_hours, kitchen_hours facts, computed total_price and cost_status in accepted_details; match_food accepts optional arrive_at and rejects known closed kitchen/offering. One source-bound offering remains required across all wishes.

- [x] Write failing behavior tests: price1800 +10% fee costs1980; limit1900 rejects; missing cost/stale/wrong branch/invalid numeric cost yields no total; explicit inclusive zero is accepted; min payable2500 is respected; delivery and per-100g cannot prove one meal budget.
- [x] Run targeted tests and record expected failures before implementation.
- [x] Extend validation, calculate Decimal totals and gate hard budgets on complete costs. Keep existing base-price fixtures meaningful by supplying explicit cost evidence only in known-complete fixture cases.
- [x] Write/run failing arrival tests: venue open but kitchen closed; arrival crosses kitchen closing; lunch window ended; unknown kitchen does not claim confirmed hours; overnight window remains correct.
- [x] Implement service-window filtering before target/radius relaxation and expose derived totals without mutating stored evidence.
- [x] Run data tests and affected food/retrieval/API tests; commit only owned paths.

### Task 2: Card presentation and reviewed data

**Files:** frontend/src/components/PlaceFacts.jsx; frontend/src/locales/messages.json; frontend/tests/place-facts.test.js; data/sources/place_food_service_2026-10-19.json; data/review/2026-10-19-food-service/*; eval/runs/2026-10-19-catalog-refresh/publish_refresh.py.

**Interfaces:** consumes Task1 total_price/cost_status and kitchen_hours; source sidecar retains schema_version1 and immutable master hash. New non-overlapping branch records enter the existing publisher; overlaps are held unless their exact source identity agrees and individual assertions can be preserved safely.

- [x] Write/run failing card tests for base versus full cost, unknown fees, source-bound kitchen hours and menu service window.
- [x] Display totals and unknown cost labels with sources in RU/KK/EN, preserving base menu prices and delivery labels. Run frontend tests/build.
- [x] Review actual merchant menu and map sources; emit only exact accepted evidence. Record wrong-city/missing/ambiguous/blocked results separately. No minimum accepted-count guarantee.
- [x] Extend publisher to include the reviewed food-service sidecar without dropping prior menus; validate all emitted facts/costs at runtime and test conflict/overlap handling.
- [x] Commit owned UI/source/publisher changes once tests pass.

### Task 3: Classification, publication, report and push

**Files:** data/review/2026-10-19-food-service/classification-review.json; data/processed/.snapshots/*; docs/food_service_2026-10-19.md; eval/runs/2026-10-19-food-service/*.

**Interfaces:** accepted category reviews use existing fact_reviews contract and exact branch sources. Publication consumes Tasks1-2 and the completed catalog-discovery snapshot.

- [x] Review explicit branch rubrics for incorrect food categories; apply supported corrections through fact reviews, preserve conflicts and unrelated-city evidence as held. Keep false closure counts separate.
- [x] Wait for catalog_refresh_review publication completion, then publish accepted additions and corrected views with offline e5; verify master hash, source preservation, active IDs and index hash/matrix consistency.
- [x] Run full project Python suite, frontend suite/build and deterministic real-HTTP cases for unsupported meal, budget/fee boundary, kitchen window and follow-up constraints. No external model calls.
- [x] Obtain independent source/code review; fix material findings with a failing regression and covering tests.
- [ ] Write precise accepted/held/missing counts, reproduction and limitations; credential-scan staged files, commit and push big-data, verify remote SHA.
