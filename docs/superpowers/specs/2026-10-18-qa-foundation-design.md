# QA foundation for Astana Walk AI

## Intent and authorized scope

Prepare the QA/Eval/Docs role from `team/04_qa_docs.md` for Smart City, using the first case in the hackathon PDF. Backend, RAG, UI and real POI data do not exist yet. Build the test infrastructure now; do not implement those teams' product code or claim to have tested it. The user explicitly prohibits Git commits without further permission. All Git operations in this task are read-only; no commits, staging, pushes, branch changes, or merges.

## Deliverables

- Independent contract and semantic validators with positive and deliberately broken synthetic examples.
- At least 40 labeled user scenarios spanning the five organizer examples, RU/KK/EN, invalid input, unknown location, time, accessibility, privacy and attacks. POI relevance labels remain unannotated until a real dataset exists; synthetic IDs must never masquerade as real OSM data.
- Offline pytest suite for QA infrastructure, opt-in live API/data/RAG tests, and a readiness command that fails when required application components/evidence are absent.
- An explicit live evaluation CLI reporting response validity, geometric/time consistency, hallucinated IDs, response rate, hit/recall when labels exist, latency, failures and not-evaluated checks. No secret keys or real user requests in fixtures/reports.
- An optional LLM judge with an explicit execution switch, validated scores and provenance; judge results are supplementary and never replace deterministic safety checks.
- Honest documentation: scenarios and limitations, product concept, RAG approach, privacy verification checklist, demo/pitch scripts, integration guide and current readiness report. Presentation/video are preparation only until a working UI and measured results exist.

## Shared interfaces

`eval/validators.py`:

```python
def validate_pois(pois: list[dict]) -> list[str]: ...
def validate_response(payload: object, request: dict, pois: list[dict], expect: dict | None = None) -> list[str]: ...
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float: ...
```

Return human readable violations; never silently fix inputs or call the network. Enforce shape before semantic checks so malformed values produce violations, not exceptions. `expect` controls outcome, categories, radius and forbidden output tokens. POI data may be incomplete; unknown facts must stay unknown. Missing optional fields cannot establish a negative factual claim.

`eval/metrics.py`:

```python
def retrieval_metrics(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> dict: ...
def latency_percentiles(values_ms: list[float]) -> dict: ...
```

Use unique IDs, separate hit@k and recall@k, return null values for unannotated relevance or no latency samples. No made-up score for missing evidence.

Golden-set file is a JSON list. Each entry has `id`, `scenario`, `request`, `expect`, `tags`. `request` follows team HTTP API. `expect` contains `status_codes` (list), `outcome` (`recommendations`, `clarification`, `rejection`, `validation_error`, `safe_response`), optional `count_between`, `max_distance_m`, `categories_any`, `forbidden_output`, and `relevant_poi_ids` (empty until human-labeled). `tags` is a list of strings. All data is synthetic; real landmark names in questions are inputs, not asserted ground truth.

Runner CLI: `python -m eval.run_eval --base-url http://127.0.0.1:8000 --pois data/processed/pois.json --output-dir eval/runs/local`. It reads the above scenarios, sends only each `request`, validates responses, writes report.json/results.md, returns nonzero for failed checks or unexecuted scenarios. Run metadata includes dataset/scenario hashes, Git HEAD and dirty status, base URL, model label if supplied, timestamp, repeats and validation scope. It never calls the LLM judge implicitly.

Readiness CLI: `python -m eval.check_readiness --root . --output eval/readiness.md`; missing product, data or required evidence yields nonzero. It must distinguish presence checks from real measured execution. Default offline test success establishes only QA-tool correctness.

## Decisions resolving source ambiguities

- No-location requests are allowed to return `200`, zero recommendations, and a useful note; ordinary supported requests require 1-3 recommendations. An empty answer never improves quality scores by removing the denominator.
- The README's illustrative 70-minute route under a 60-minute budget and inconsistent IDs/distances are not golden fixtures. Validators use independently checked synthetic coordinates.
- A route must reference unique recommended POIs and fit the budget. Its total cannot be less than declared visit minima and straight-line lower bounds at the documented mode speeds. Approximate walking distance is compared with a tolerance; geometric plausibility is not proof of real pedestrian access.
- Unknown opening hours require an unknown status. Never infer wheelchair access, quietness, sockets, ratings or current events from missing data. General prose faithfulness is a judge/human check, not a regex-proven guarantee.
- Full privacy, logging, map and race-condition checks need implementation-specific integration. Explicitly document them as pending rather than passing a stand-in.
- Paid model calls and YouTube publication are not performed during preparation. No credentials are needed for the offline suite.

## Acceptance

Offline tests pass and include broken examples rejected by validators and CLI failure propagation. Missing implementation produces explicit skipped live tests and a failing readiness report. The final report states actual counts and pending checks. The original `team/` task files remain intact. HEAD is unchanged.
