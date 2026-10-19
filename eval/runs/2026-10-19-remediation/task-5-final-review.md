# Final independent delivery/evaluation review

Scope: current Docker/Compose/CI, bootstrap bundle, health profiles, primary Ayat evaluator and readiness gate against I01–I10. Review was read-only except the separately assigned B07 correction in `query.py`, `service.py` and temporal tests. No provider calls, external SMTP, source refresh, production data mutation, commit or deploy was performed. WHAT_TO_DO/template grounding was excluded as requested because its owner was implementing it in parallel.

## Findings found during review — all resolved and independently rechecked

### 1. I05 — scheduled canonical refresh drops the mandatory fact-review sidecar

`data/run_pipeline.py` copies prior `field_evidence.json` and selected runtime sidecars, but omits `fact_reviews.json`. The current selected bundle contains that policy file; `data.snapshot.publish_snapshot()` correctly refuses to remove an existing policy sidecar without a reviewed removal.

Reproduced entirely in a private temporary directory: create an offline one-POI canonical export; publish it with a valid, empty, SHA-bound `fact_reviews.json`; add a second source POI; rerun the same offline refresh. Actual result:

```json
{"refresh":"blocked","reason":"Snapshot rejected: missing_policy_sidecar:fact_reviews.json","old_version_retained":true}
```

The failure preserved the active snapshot safely but prevented I05 acceptance. **Resolved by the curator.** Independent rerun of the exact private one-to-two-POI reproduction now succeeds, retains `fact_reviews.json`, and confirms its hash matches the new canonical bytes. The new policy preserves identical-record confirmations, moves changed confirmations to pending with history, retains disputes/quarantine, and rejects stale bindings/source-ID loss. Independent targeted data publication/refresh verification: **30 passed in 0.25s**.

### 2. I07 — independent C4 ignores the original structured request budget

`ayat_backend/eval/run_eval.py::run_checks()` takes its budget solely from `response.used_context.time_budget_min`. A regression in runtime budget interpretation can therefore be repeated by the evaluator rather than detected.

Reproduced from the valid historical HTTP response fixture without changing repository files: remove route, retain one real POI, set `travel_min=1`, `visit_min=[25,25]`, `visit_suggested_min=25`, response budget 165, and original `scenario.request.time_budget_min=10`. Actual result:

```json
{"request_budget":10,"advertised_context_budget":165,"actual_travel_plus_visit":26,"C1":true,"C4":true}
```

The already added audit regressions correctly reject visit 120 against response budget 10 and the 127-minute fake route. **Resolved by root.** The original-request cap is now enforced; the same request 10/context 165/travel+visit 26 reproduction independently returns C4=False. Explicit return travel and zero-valued budget annotations are also covered by the new guard tests.

### 3. I09 — the Python lockfile is absent from the source fingerprint

`eval/run_eval.py::source_fingerprint()` includes Ayat source and `pyproject.toml`, but `.lock` is not an included extension and `ayat_backend/uv.lock` is not an explicit config. Docker installs dependencies using this lockfile with `--frozen`.

Reproduced in an isolated temporary tree: change only `ayat_backend/uv.lock` from revision 1 to revision 999; source fingerprint remains identical:

```json
{"lock_changed":true,"source_fingerprint_changed":false}
```

**Resolved by root.** `uv.lock` and `.python-version` were added to the fingerprint with a stale-evidence regression. The identical isolated lockfile mutation independently now changes the fingerprint.

## Final verdict

**No remaining blocking delivery/evaluation finding in the reviewed scope.** All three issues discovered above were fixed by their owners and independently rechecked. This is an I01–I10 delivery/evaluation review, not a claim of externally deployed service, paid-provider quality certification, or completed submission artifacts. B07 dual-duration behavior is verified on the final query/service code.

## Acceptance review

| Audit | Current evidence | Assessment |
| --- | --- | --- |
| I01 | Root Compose primary `web` builds/runs Ayat on 8001; original backend is a separate `secondary` profile on 8002. Local script uses the same Ayat entrypoint. Current auth/saved/meta contract is that runtime's OpenAPI. Direct diffs against the captured baseline confirm the Compose entrypoint switch, frontend build stage and pytest CI replacement. Root executed the new primary image smoke and restart/resume successfully. | Runtime selection fixed. Fresh-image execution was supplied by root; not rerun by this reviewer. |
| I02 | Selected immutable bundle resolves and hash-validates 17 artifacts, including quarantine, overrides, field evidence, fact reviews, graph and canonical index. Docker copies `data/` and `runtime_support/`; it no longer omits policy files. | Delivery structure fixed. Current snapshot membership/count changes are reviewed in the data task; historic 2751 is not asserted as a permanent target. |
| I03 | Docker frontend stage runs `npm ci`/Vite build and copies `/web/dist`; current UI root/assets/saved deep link/auth/saved are exercised by smoke. | Fixed for primary Docker delivery. |
| I04 | Refresh workflow runs from root using `python -m data.run_pipeline`; the exact `--help` invocation passed locally before any collection. Imports of eligibility, snapshot, pipeline, Ayat categories/team adapter and runtime provider-health support passed. | Namespace/import failure fixed. Fresh CI installation itself was not repeated during this read-only review. |
| I05 | Refresh now targets the canonical publisher, and safety gates preserve old versions. | Fixed after the reproduced sidecar omission; controlled refresh now promotes a complete review-bound bundle. |
| I06 | CI invokes pytest across Data/RAG/both backends/QA with real canonical dataset and explicit local RAG/backend flags; includes `big-data`, frontend tests/build and fresh Docker restart smoke. | Prior unittest-discovery/test-coverage gap fixed in workflow. Full hosted GitHub Actions execution was not claimed. |
| I07 | Independent final route arithmetic and actual suggested visits are included; the two original reproductions are covered by tests. | Fixed, including original-request budget binding, required returns and zero caps. |
| I08 | CLI uses explicit failures/counters, nonzero result on HTTP/schema/semantic/provenance failure, and a provenance companion. Targeted500-path and gate rejection tests passed. | Original false-success behavior fixed. |
| I09 | Primary runtime/schema/profile/live-HTTP/snapshot/canonical hash/scenario/source/Git identity is validated. Fixture/in-process evidence cannot establish live readiness; dirty Ayat source changes invalidate evidence. | Fixed, including the lockfile gap found during this review. |
| I10 | Provider state is role/config scoped with expiry and verified timestamps; health does not issue provider calls. Template and LLM readiness are distinct; invalid/unrelated/unknown-candidate proof tests passed. | Prior configured-is-verified claim fixed. External live LLM readiness is outside this unpaid review. |

Disabled external SMTP is the chosen operating mode. Earlier actual localhost STARTTLS and API503 checks remain in `delivery-evidence.json`; no external SMTP was enabled during this review.

## Commands and observed verification

- `.venv/bin/python -m pytest ayat_backend/tests/test_eval_guards.py ayat_backend/tests/test_eval_provenance.py tests/test_readiness.py tests/test_provider_health.py backend/tests/test_provider_proof.py ayat_backend/tests/test_graph_snapshot.py -q` → **43 passed in 0.60s**.
- `.venv/bin/python -m data.run_pipeline --help` → success; no network collection.
- `docker compose config --quiet` → success.
- Import smoke for `data.eligibility`, `data.snapshot`, `data.run_pipeline`, `ayat_backend.app.categories`, `ayat_backend.app.team_data`, `runtime_support.provider_health` → success.
- `resolve_snapshot('data/processed')` → selected version `4e9b6ecc5b4c455f9c0443714afb91b2`, all 17 artifact hashes validated. Artifacts: canonical POIs/leisure, source manifest/stats, boundaries, river, graph, gazetteer/events, quarantine/overrides, field evidence/fact reviews/review manifest, canonical index manifest/vector file.
- The exact blocker reproductions above were executed against temporary files/data only.
- Root-owned final integration/hosted CI/provider-proof refresh may supersede these observations after fixes. No claim is made that merely having these files establishes complete submission readiness.

## Separately assigned B07 correction

During this review root reassigned the concrete dual-duration bug: “I have 10 minutes for coffee before domestic flight in 5 hours” and its Russian equivalent discarded the free-time limit. Added nine RED cases, then corrected parsing and the effective window. Free time and deadline are parsed independently; adjacent hours+minutes are summed; clock deadlines keep unrelated free durations; explicit request UI budget retains its documented precedence over text; otherwise text free time limits the deadline window. Explicit rule durations also take precedence over contradictory model parsing. Domestic 120/international 180/unknown 180 plus separate 15-minute road uncertainty are unchanged.

Changed only `ayat_backend/app/query.py`, `ayat_backend/app/service.py` and `ayat_backend/tests/test_temporal_safety.py` for that assignment. Initial temporal+unit verification: 56 passed; Ayat/API suites: 282 passed. The original synthetic cafe with 14-minute outbound travel now produces no recommendation for the textual 10-minute free-time limit despite a five-hour-later flight. Final combined temporal/API/evaluator/readiness/provider-proof checks: **118 passed in 10.11s**. No production changes followed the freeze.

Final independent endpoint read at `http://127.0.0.1:18019/api/health`: runtime Ayat, template ready, LLM off; snapshot identity matched the local selected 17-artifact bundle and POI count was 2750. The review did not perform a paid provider call.

## Final readonly budget-settlement review

Reviewed the final `BudgetTransport` update in `scripts/live_model_probe.py` without modifying production code or the live ledger. **No blocking cap/settlement issue found in the exercised text-only probe path.** No provider requests were made by this review.

The mutation boundary uses an OS lock and reloads the shared ledger inside that lock, reconciles before reservation and after mutation, then atomically replaces the ledger file. Existing attempts remain in the history. A reservation is settled to computed cost only after HTTP200 with nonnegative integer input/output usage; booleans are excluded by exact type checking. Failures, cancellation, missing/invalid usage, non200 and in-flight attempts retain their original upper reservation. The configured cap can only become more restrictive.

Verification:

- `.venv/bin/python -m pytest tests/test_probe_budget.py -q` → **4 passed in 0.12s**, including successful sequential settlement, retained failed/restarted reservation and simultaneous two-instance in-flight cap enforcement.
- Independent temporary-ledger checks for missing, negative, floating, boolean, string and null usage all retained the full reservation, recorded no settled aggregate actual cost and blocked the next request. Mock responses only; no network connection.
- Independent non200 cases201/400/429/500 with otherwise valid usage all retained the full reservation.
- Independent **separate OS processes** raced against the same temporary ledger with an existing paid historical attempt. Exactly one mock request was sent, the other was rejected before send, historical attempt remained, and reconciled actual+uncertain reservation stayed below the cap.
- Read-only live-ledger snapshot during root's final probe:19 attempts, known actual cost **$0.0194804**, actual-plus-uncertain/in-flight reservation **$0.0241104**, cap **$0.10**. Independent in-memory reconciliation matched the recorded actual cost. These values are an observation during an active root-owned run, not the final cost report; the ledger was never written by the reviewer.

No actual API key, account cookie, raw request or provider prompt was read or printed. The review's temporary mock ledgers and process barriers were automatically removed. Root owns final provider/browser execution and its final spend report.
