# Discovery queue checkpoint

Frozen at 2026-10-19T06:08:55.948882+00:00. Session 60592 finished successfully: all **1091 launch rows** have bounded public 2GIS/Bing outcomes from **2182 actual requests**. The pass ended at 2026-10-19T00:52:42.566963+00:00; no background process remains. This finishes the bounded discovery pass, not branch verification or an exhaustive internet search. Confirmed no-information results: **0**. Exhaustive branch searches: **0**.

Outcomes: {"candidates_found": 1364, "skipped_provider_block": 1091, "incomplete_source_error": 230, "search_returned_no_candidates": 588}. The versioned condensed ledger records actual request URLs, source hashes, errors and candidate URLs. Raw response text, the original live ledger and HTTP caches remain local and ignored. The complete local ledger SHA-256 is `61d79e2ca20a3b6b26823c032e0cd924eedddceb53b7b60db8114ef926e2fa1f`.

The public 2GIS search URL uses the name alone; its query metadata also retains the canonical address for review. Bing URLs include the canonical name/address. Exact distinctive name plus matching address or independently checked coordinates within 200 m is required. Address conflicts and possible rebrands remain held. A source's lack of an attribute means unknown.

Yandex Maps search returned 429 before the pass and was skipped for every row without new requests. Google returned 429 and DuckDuckGo required a human challenge during earlier feasibility probes. No block was bypassed. A minimum of three distinct successful providers plus an explicit completed human review is required before a no-information conclusion; neither two providers nor three empty pages establishes that conclusion.

## Continue later

Review the versioned branch decisions and accepted sidecar before another network pass. To retry only ordinary source failures while respecting persistent blocks, use the local resumable runner after choosing an explicit new bounded pass:

```sh
.venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --providers 2gis bing --retry-incomplete --limit 2000 --max-requests 460 --delay 1.25
```

The runner prepares a new queue from the unchanged master and excludes already accepted detail rows; its row count may therefore be smaller than the original 1091. Do not relabel this frozen launch cohort. Successful provider attempts are skipped, ordinary failures can be retried, and persistent provider circuits remain respected. Never delete or mark closed from an empty result, 404, timeout or challenge. The discovery runner never modifies canonical rows, quarantine or accepted facts.
