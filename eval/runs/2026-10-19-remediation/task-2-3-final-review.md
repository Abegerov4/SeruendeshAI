# Final Task 2 / Task 3 correctness review

Reviewed 2026-10-19. No remaining blocking reproduction found in the requested scope after the B07 correction. This is a scoped review, not a statement that all 44 audit items or all external services have been verified.

## Temporal behavior and captured baseline

The captured baseline `_item` was executed independently from its AST against the same synthetic candidate and current data types: outbound travel14min, airport return36min, requested visit25min, explicit budget10min, flight deadline300min, buffer135min. Baseline returned a5min visit and `[5,5]` advertised interval, producing55min total against10min available. Current `_item` returns `None`. A later flight does not override a shorter explicit budget, and final serialization cannot invent5min without room.

An additional real B07 parsing defect was reproduced during review and sent to root before this report. For `I have 10 minutes for coffee before domestic flight in 5 hours` and `У меня 10 минут свободного времени, внутренний рейс через 5 часов`, the earlier implementation parsed the300min deadline but lost the10min free-time budget. The real service then used165min and emitted a45min cafe visit despite the user's10min limit. Root corrected separate duration extraction and binding of parsed free time.

Fresh independent replay now reports free-time10, flight deadline300, effective budget10, zero cards, and no route for all of:

- `I have 10 minutes for coffee before domestic flight in 5 hours`
- `У меня 10 минут свободного времени, внутренний рейс через 5 часов`
- `Менде 10 минут бос уақыт бар, ішкі рейс 5 сағаттан кейін`
- `Ішкі рейс 5 сағаттан кейін, кофе ішуге 10 минутым бар`
- `Хочу кофе на 10 минут, внутренний рейс через 5 часов`

Replays used the real parser, ranking, service, and final serialization with a synthetic cafe at51.135/71.43, origin51.128/71.43, `want_route=false`, `now=2026-10-19T11:00:00+05:00`, and no structured time budget. Provider/network access was disabled. Existing structured-budget precedence and compound durations have dedicated regressions.

`main.py` supplies `load_graph` with the selected snapshot's `walk_graph.npz`. A missing bound graph yields labelled straight-line fallback; it does not silently load an unrelated legacy graph. Temporal, graph-bound startup, and route-ownership tests passed below.

## Immutable data and common eligibility

Fresh offline inspection of the selected bundle confirmed:

| Check | Result |
|---|---|
| Selected version | `4e9b6ecc5b4c455f9c0443714afb91b2` |
| Bundle artifacts with validated SHA/byte count |17|
| Canonical master SHA256 | `803dcffdb4473abddfc97be9cab5a41bc663ee74afc67c560f1723b42f8c1e63` |
| Canonical records / distinct original source IDs |14,006 /14,607|
| Primary / secondary eligible records |2,750 /2,750, identical ID sets|
| Review decisions / reviewed canonical places |66 /30|
| Accepted / disputed decisions |62 /4|
| Reviewed fields |category30, opening_hours26, internet_access6, kid_friendly3, name1|
| Dense matrix |2,750×384, finite; maximum unit-norm error1.1920928955078125e-7|

Canonical bytes match the pre-curation master hash. Reviews affect derived views; original canonical rows, source IDs, source records, and conflicting reports remain available. Loading `canonical_index.load_index` checked ordered IDs, documents, model identity/dimension, policy/code hashes, artifact SHA, shape, and finite values; no encoder or paid provider was invoked.

All six exclusions resolve unambiguously to actual canonical owners, remain in the master, and are absent from both eligible pools:

- `osm:way/230409020`
- `osm:node/4529345494`
- `overture:3dda9f68-24a5-4047-a0a0-101ce0a047fc`
- `overture:5b26880c-5614-4d74-a83d-06d45ed76b94`
- `overture:67740c18-c915-4b60-871a-3199c23aebe8`
- `citypass:81`

No quarantine ID was unmatched or ambiguous. Alem.AI facts belong to the verified `osm:way/454857501`; the conflicting CityPass location does not inherit them.

The four disputed schedules are `null` in both runtime views: Bayterek `osm:way/230401645`, Palace `citypass:88`, military museum `citypass:98`, Seifullin museum `citypass:89`. Their source disagreements remain explicit rather than being resolved by publication order. National Museum retains its monthly last-Tuesday closure, including a direct closed result at noon on2026-10-27.

All six reviewed CoffeeBoom branches expose supported Wi-Fi. No power or quietness fact was inferred from Wi-Fi, a cafe category, or source wording. Only the three scoped accepted child-suitability decisions are applied (Central Park, Puppet Theatre, Zheruyik); Alem's age/program description does not become a universal suitability, safety, or free-entry assertion. Evidence remains source-reported at the recorded check date, not a claim of onsite truth today. Unknown licensing remains unknown; no publication permission is inferred. Primary citations and unsupported/report-only fields are in [scenario-verification.md](scenario-verification.md).

Explicit resolution of Wi-Fi conflicts requires all conflicting field and amenity source IDs, a reason, and `resolves_conflicts=true`. Only the effective conflict flag is removed after a valid resolution; original canonical flags/evidence are retained. Publisher gates reject dropped policy sidecars unless explicit reviewed removal evidence is supplied.

## I05 refresh correction completed during this task

Root obtained user approval for the refresh policy before implementation. I changed only `data/run_pipeline.py` and added `data/tests/test_pipeline_review_refresh.py`; this portion is implementation verification rather than an independent code review of my own patch.

Refreshing a published reviewed snapshot previously failed with missing `fact_reviews.json`/other policy sidecars. The pipeline now validates the prior review binding before carrying it forward and binds the result to the exact new published master bytes. Only equality of the entire old and new canonical row preserves an accepted decision. A changed row becomes pending, keeps its original evidence, and appends the original decision plus previous canonical SHA to `review_history`; unchanged subsequent refreshes cannot promote it. Disputes carry unchanged and continue masking facts. Prior quarantine decisions are retained and unioned with local decisions; a missing or empty local file cannot clear them. Other missing review sidecars are preserved.

The new integration tests use actual atomic publication in temporary directories. They cover source additions without source-ID loss, unchanged accepted facts, changed-row pending/history behavior, changed disputed schedules, retained quarantine with an empty local file, stale prior binding rejection, and refused source loss with the old active pointer/history unchanged. The initial three tests were observed failing for missing sidecars before the implementation; all five now pass. No active data bundle or dense artifact was republished by this implementation task.

## Verification and limits

Fresh runs:

```text
.venv/bin/python -m pytest ayat_backend/tests/test_temporal_safety.py ayat_backend/tests/test_graph_snapshot.py ayat_backend/tests/test_team_data.py ayat_backend/tests/test_store_canonical.py ayat_backend/tests/test_event_identity_safety.py ayat_backend/tests/test_canonical_index.py data/tests/test_snapshot_safety.py data/tests/test_review_disputes.py rag/tests/test_snapshot_policy.py tests/test_backend_temporal_local.py -q
108 passed in10.03s

.venv/bin/python -m pytest data/tests/test_pipeline_review_refresh.py data/tests/test_pipeline.py data/tests/test_snapshot_safety.py data/tests/test_review_disputes.py -q
31 passed in0.26s
```

These suites overlap; their counts are not additive. `git diff --check` passed. Runtime invariants and exact B07 replays above were re-executed separately with `LLM_ENABLED=false`, `EMBED_MODEL=off`, `WEATHER_ENABLED=false`, blank SMTP settings, and socket connections disabled. Source priority follows the explicitly approved owner/host policy; the cached source evidence was inspected rather than fetched again during this final review.

No paid calls, emails, production deployments, or master-data writes occurred in this review. Existing [delivery-evidence.json](delivery-evidence.json) documents an earlier localhost SMTP capture and disabled-SMTP check; I read that evidence but did not rerun or claim its service checks here. Fresh primary readiness/provider proof and final deployment remain root's separately owned evidence, and source-fingerprint reports must be regenerated after the final code changes.
