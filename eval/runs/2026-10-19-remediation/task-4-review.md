# Independent Task 4 / model-index-budget review

Comparison: current working tree against the captured
`.superpowers/sdd/2026-10-19-audit-remediation/baseline`, preserving unrelated dirty
integration work. Reviewed Ayat llm/generate/config/provider health, secondary
llm/generate/intent, runtime_support/provider_health, canonical_index and its CLI,
and scripts/live_model_probe. No real provider call was made by this reviewer.

## Findings and disposition

### R4-01 — spending reservations were not shared (blocking, fixed by root)

Initial `BudgetTransport` cached a separate ledger object and asyncio lock per
instance. Two instances created before either request each accepted a reservation
of about USD0.06 against the same USD0.10 ceiling; both requests reached the
transport and the last save could overwrite the other attempt. `--out` also
selected a new cost ledger, bypassing the overall task budget on another run.

Parent explicitly authorized the reviewer to add
`tests/test_probe_budget.py::test_two_guard_instances_share_one_reserved_budget_before_sending`.
It uses only real HTTPX/SDK boundaries with `httpx.MockTransport`: two guards,
one shared temporary ledger, two140k-byte text requests, max output1800.
RED observed **two** sent requests vs expected one. Root added OS file locking,
read-modify-save under lock, UUID reservation updates and a fixed repository-wide
ledger independent of output directory; the persisted cap only decreases.
Three budget tests now pass, including same-ledger two-instance concurrency and
failed-request reservation retention across restart. No paid test requests.

### R4-02 — additional SDK status errors escaped fallback (blocking, fixed by root)

An actual `AsyncOpenAI` client with MockTransport returning HTTP422 caused
`ayat_backend.app.llm.parse` to raise `UnprocessableEntityError` instead of
returning the template-fallback sentinel. HTTP402 generic APIStatusError and409
ConflictError had the same exception-list gap. Inline local reproduction printed
`uncaught exception: UnprocessableEntityError`.

Root broadened handling to `openai.APIStatusError`/APIConnectionError while
retaining the bounded deadline and the separate BadRequest retry. Added actual
SDK402/409/422 regressions. Fresh combined SDK and budget run:

`.venv/bin/python -m pytest tests/test_probe_budget.py ayat_backend/tests/test_model_failures.py -q`
→ **10 passed**, 0.31s.

### R4-03 — secondary readiness certified invalid application output (blocking, repaired under explicit parent authorization)

A real `OpenAI` SDK client with MockTransport returned the JSON object
`{"categories":1,"recommendations":"bad"}`. Both
`intent.llm_intent(...)` and `generate.llm_generate(...)` rejected it with None,
but `llm.provider_status()` reported **ok + verified_at** because chat_json recorded
success before the application schemas were accepted. An unrelated A/B override
could also verify the configured decision-model chain. Unknown candidate IDs
could be rejected by generation while health still claimed success.

Parent changed the initial report-only scope and explicitly assigned the repair
of backend/app/{llm,intent,generate}.py plus its new regression test to this
reviewer; root will independently review those changes. No other production
files were edited by the reviewer during this review task.

Repair:

- chat_json accepts optional local `validate_output` callback. Intent passes the
  actual Intent validator; generation passes the actual LlmAnswer validator plus
  at least one known candidate ID or an explicit empty abstention.
- Provider role success is recorded only after acceptance, for an actual model
  belonging to that configured role chain. An unrelated override does not certify
  the defaults. Configuration identity includes models/account/endpoint/reasoning
  effort and is captured before the request.
- Facts-only deterministic rendering stays unchanged; the validator callback is
  not sent to the provider or traces.
- New backend/tests/test_provider_proof.py observed **3 RED / 1 passing control**
  before repair, covering bad schemas, unrelated override, unknown candidate IDs
  and successful role validation. All four pass after repair.

Parent additionally authorized updating the local privacy spy in
`tests/test_backend_safety_local.py`: it now records system/user and actual
role/name/model metadata, excluding the local validator callback. This fixes JSON
serialization of a bound method while preserving every raw PII and exact-GPS
assertion. No privacy assertion was weakened.

Fresh relevant integration run:

`.venv/bin/python -m pytest tests/test_backend_safety_local.py backend/tests/test_provider_proof.py backend/tests/test_integration_rag.py backend/tests/test_grounded_generation.py -q`
→ **22 passed**, 2.60s.

Fresh combined proof/privacy ordering run:

`.venv/bin/python -m pytest backend/tests/test_provider_proof.py tests/test_backend_safety_local.py -q`
→ **19 passed**, 0.45s.

Another agent's `/tmp/delivery-all-first.txt` captured the original three RED
provider assertions while production code was being changed: new test file
mtime03:09:43; llm.py fix03:10:07; long run finished03:10:23. Its process imported
old code at collection. The reviewer post-fix broad run had no proof failures;
fresh combined runs above do not reproduce test-state pollution. Parent notified.

## Standards

No additional documented repository-standard violations identified in the
reviewed scope. No AGENTS.md/CONTRIBUTING.md/CODING_STANDARDS.md source was present
for this worktree. Safety findings above concern behavior and specification,
not stylistic preferences. Baseline comparison used the captured current-tree
files rather than HEAD, avoiding attribution of prior integration work.

## Spec / verified safeguards

- SDK incomplete/truncated/refusal/schema-invalid cases reach fallback within the
  existing per-parse deadline; newly found generic status failures are also caught.
- Both factual generation paths render why/action from candidate facts; arbitrary
  model card prose, summaries and secondary notes cannot assert facilities as data.
  Creative ideas remain separately labelled; accepted visit bounds are clamped.
- Readiness separates configured from recent evidence, requires both configured
  roles and expires/fails/reconfigures without a health-triggered provider call.
- Canonical index stores ordered IDs, document digest, model/repo/dimension,
  policy/review hashes and matrix hash. Loader rejects order/document/model/policy
  drift and corrupt matrices. CLI uses the actual adapted canonical view; legacy
  matrices remain separate. Reviewed these paths plus the existing local index
  permutation/policy/corruption regressions; no paid embedding provider is used.

Initial targeted root-scope suite before R4-02/03 repairs:

`.venv/bin/python -m pytest ayat_backend/tests/test_model_failures.py ayat_backend/tests/test_grounded_generation.py backend/tests/test_grounded_generation.py ayat_backend/tests/test_canonical_index.py tests/test_provider_health.py tests/test_probe_budget.py -q`
→ **15 passed**, 0.34s. Existing tests alone did not cover the review findings.

## Actual provider evidence inspected, not executed by reviewer

Read `eval/runs/2026-10-19-remediation/live/live-model.json` and
`provider-cost.json` without emitting credentials/prompts. Six HTTP200 Responses
calls, fixed gpt-4.1-mini standard pricing, actualUSD **0.0064264**, conservatively
reservedUSD **0.0379228** within the USD0.10 cap. Three local HTTP request cases
(RU/KK/EN) have passed non-null checks and real_llm_mode; observed elapsed5488,
4365,3324ms. Health changed configured/unready→ok/ready with verified_at and dense
retrieval enabled for snapshot4e9b6ecc5b4c455f9c0443714afb91b2.

This evidence supports those three recorded calls/configuration only. The report
correctly retains `human_text_review=NOT_EVALUATED`; null category/safety checks
are not evidence that those scenario-specific checks ran. It is not a blanket
model-quality, external venue-truth or production-delivery certification.

## Broad-run qualification and handoff

The reviewer's `.venv/bin/python -m pytest -q` after secondary repair and before
privacy-spy adaptation completed **891 passed,73 skipped,6 failed,12 subtests**,
55.46s. Four failures were PII[email/phone/iin] and exact-GPS spy serialization,
now repaired and passed with unchanged privacy assertions. Two concurrent curated
data expectations were root-owned:
`test_real_master_is_preserved_and_all_source_ids_remain_available` and
`test_current_baiterek_and_all_directory_hours_have_field_source`. Parent is
updating those explicit curation expectations. Per parent's request, no new broad
run was started until the parallel edits freeze.

No other reproduced blocking issue remains in the reviewed root implementation
after the fixes above. Root must independently review the reviewer's R4-03 repair
and run the final frozen whole-tree suite; this report does not self-approve that
repair or label a concurrently changing whole tree green.

## R4-04 — generic action templates asserted facilities and competing durations (blocking, repaired under parent's new assignment)

The root's real live probe exposed remaining WHAT_TO_DO claims despite safe
why-rendering: playground benches and20–40minutes, park main alley/bench by water,
monument plaque, café dessert/table20–40minutes, mall food court/cinema/warmth,
water park minimum hours, assumed tickets/online sales/rental/age policies and
other category-derived details. Library/coworking special cases did not protect
all other categories or direct consumers of the table.

Parent explicitly assigned WHAT_TO_DO in ayat_backend/app/i18n.py and extensions
to test_grounded_generation.py. New regression exercises every33category in all
three languages, checking both the underlying template and its rendered action
with unknown field facts. RED: **58 failed,44 passed**, including numeric duration,
price/age-style values and unsupported benches/outlets/quiet/menu/plaque/food-court
claims. Replaced the entire table with concise category-appropriate suggestions,
using only generic actions or requests to check local conditions. No concrete
facilities, dated events, special menu items, ticket channels, durations, prices
or age limits are supplied by the generic action. All flight/hours/other i18n
strings outside WHAT_TO_DO remain unchanged. Index document construction is
unchanged; no index rebuild was performed by reviewer.

Fresh focused verification:

`.venv/bin/python -m pytest ayat_backend/tests/test_grounded_generation.py ayat_backend/tests/test_temporal_safety.py ayat_backend/tests/test_api.py -q`
→ **153 passed**, 7.61s.

UI “Новое” inspection (no UI change): Explore.jsx passes isNew when a POI ID was
absent from the previous response; PlanPanel uses diffPlans.added. This is a
selection-change badge, not an assertion that a venue opened recently or its
facts were freshly verified. No defect found for that badge.

The source fingerprint changed with this action-text repair; prior live probe
records remain valid historical evidence for their recorded source revision.
Root owns final frozen verification and any budget-guarded rerun needed to bind
live evidence to the final source revision.

## Final readonly follow-up review — client rotation, return arithmetic and probe observer

Reviewed the subsequent root patches without production/test edits:

- Ayat client identity now includes credentials, parse/generation models and
  service tier. The cached client rotates on identity change, closes its previous
  client, and parse captures the configuration before awaiting provider calls.
  An in-flight old call therefore does not certify new credentials. Probe's
  injected budget-guarded SDK explicitly receives the matching configuration
  identity, so the first parse does not replace it with an unguarded client.
- Recommendation.return_min exposes the deadline-destination return leg for each
  alternative. Evaluator C4 includes travel + serialized visit + return, and
  separately rejects a response whose reported/actual spend exceeds the original
  structured request budget. Route arithmetic continues counting each leg/visit
  and the single back leg exactly once.
- S4's expected empty result follows the approved unknown-flight buffer of180min
  plus road uncertainty: sightseeing cannot fit two hours before departure. This
  is a policy-consistent scenario expectation, not evidence of a feasible outing.
- Found and locally reproduced one remaining evaluator edge: `if e.get("budget_max")`
  ignored the new explicit zero maximum. A valid empty response reporting60min
  incorrectly passed C4 against budget_max0. Root fixed the condition to
  `is not None` with RED→GREEN regression. Fresh readonly reproduction now rejects
  that response.
- Optional browser_seconds observer calls the original recommendation handler
  once, returns its result, and captures the browser phase separately. The report
  requires source-before/source-after fingerprints to match, and when browser
  observation is requested it requires observed rows using actual LLM mode.
  There is no additional provider path outside the same guarded SDK. This code
  inspection does not itself constitute a new browser/live-provider run.
- OS-locked, reload-before-reserve, fixed-path spending ledger remains enforced
  before dispatch; failed requests retain their conservative reservation and
  multiple guard instances cannot each reuse the same remaining budget.

Fresh frozen-source test command:

`.venv/bin/python -m pytest ayat_backend/tests/test_model_failures.py ayat_backend/tests/test_eval_guards.py ayat_backend/tests/test_temporal_safety.py tests/test_probe_budget.py -q`
→ **61 passed**, 4.33s.

Source fingerprint before and after that verification was identical:
`233622c9c05f1437eefd175f0caa62d91524574b39140a72ddb6eecebec99b3a`.
The inspected cost ledger still has exactly **6 attempts**, actualUSD0.0064264,
reservedUSD0.0379228, capUSD0.10. No paid call was made by this reviewer and no
additional paid probe was present at this checkpoint.

**Final scoped verdict:** no reproduced blocking defect remains in these root
follow-ups after the zero-bound repair. Approved within this reviewed scope.
Previous live artifacts remain evidence for their recorded source revision;
the final source-stable/browser-enabled path still needs its own executed report
if claimed as final live/browser verification. Whole-tree delivery/readiness and
unrelated live integrations remain outside this scoped verdict.


## D08 publication attribution and M01 wheelchair wording follow-up

Root assigned this narrowly scoped repair after the final live probe exposed
licensed Wikipedia prose with an unrelated primary OSM place link. No provider
calls, data refresh, eligibility/store changes or index changes were made.

Changed production files: `ayat_backend/app/schemas.py`,
`ayat_backend/app/service.py`, `frontend/src/api.js`,
`frontend/src/components/PlaceCard.jsx`, and
`frontend/src/locales/messages.json`. Added regressions:
`ayat_backend/tests/test_description_attribution.py` and
`frontend/tests/description-attribution.test.js`.

The API now returns `description_attribution`, defaulting to `[]`, with entries
containing `source`, `title`, `url`, `license`, `license_url`, `attribution` and
`notice`. A Wikipedia source excerpt is published only when its declared
CC-BY-SA-4.0 license has a matching licensed Wikipedia article in source_refs.
The primary venue source_url is preserved. Incomplete, conflicting or unsafe
article metadata withholds the excerpt. Structured fact templates retain their
existing publication behavior. The UI links the actual article and license,
shows contributor attribution and a localized shortening notice. Older API or
saved responses without attribution do not display Wikipedia prose.

Wheelchair yes/limited/no labels now describe wheelchair accessibility according
to the source. They no longer infer literal steps or assert OSM as the field's
source. RU, KK and EN labels were added without changing other translations.

Read-only canonical inspection found 218 licensed Wikipedia descriptions,
including 96 whose primary source_url is OSM. All 218 currently have complete
matching article attribution and publish through the guarded helper; none were
withheld. Unknown/unlicensed prose is still governed by the existing upstream
policy. Canonical bytes and source records were not rewritten.

RED/GREEN evidence:

- `.venv/bin/python -m pytest ayat_backend/tests/test_description_attribution.py -q`
  — RED 3 failures before the repair, GREEN 3 passed afterwards.
- `cd frontend && node --test tests/description-attribution.test.js`
  — RED 6 failures before the repair, GREEN 6 passed afterwards; renders the
  real TrustList component through Vite SSR and tests the real API mapping.
- `.venv/bin/python -m pytest ayat_backend/tests/test_description_attribution.py ayat_backend/tests/test_grounded_generation.py ayat_backend/tests/test_temporal_safety.py ayat_backend/tests/test_api.py -q`
  — 166 passed in 7.15s.
- `cd frontend && npm test` — 20 passed.
- `cd frontend && npm run build` — passed; existing >500KB chunk advisory.
- `.venv/bin/python -m pytest -q` — 1021 passed, 73 skipped,
  12 subtests passed in 43.43s. Skips are explicitly gated external backend,
  dataset, PostgreSQL and browser integrations; this is not live UI evidence.

Production changes frozen and handed to the independent D08 reviewer. No new
live/provider verification is claimed by this follow-up.
