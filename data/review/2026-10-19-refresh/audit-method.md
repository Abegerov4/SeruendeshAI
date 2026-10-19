# Whole-catalog source audit method

The audit is an evidence sidecar. It never edits the master catalog, a published snapshot, runtime code, or eligibility decisions. The input is frozen in `eval/runs/2026-10-19-catalog-refresh/source-audit/input-pois.json` before network work starts. Each canonical ID appears once in `rows.jsonl`.

## Interpretation

- A listed website is not automatically an independently verified official website. The field includes chain homepages, social profiles, public directories and messaging landing pages.
- `source_url` identifies the catalog's source and remains separate from `listed_website`. Overture STAC links identify a source release, not an exact branch page, so no per-record generic Overture SPA requests are issued.
- `successful_fetch` means a bounded public HTTP response was obtained. Branch identity additionally requires a complete explicit name/alias match and matching address or geographic separation of at most 150 metres. Explicit address conflicts and distant coordinates prevent a match.
- A matched identity does not prove current operation. Every candidate retains `operating_status: unknown` and requires review.
- `no_url`, network errors, HTTP errors, robots denial and unavailable sources are incomplete checks. A 404, absent hours, absent API item or empty result never establishes permanent closure.
- This pass does not perform an exhaustive internet or 2GIS search. Therefore `search_complete`, `deletion_eligible`, `no_data_after_completed_search`, and confirmed permanent closures remain false/zero. Lack of branch confirmation must not be converted to deletion.
- Missing fields use category-specific applicability. Food venues require menu, cuisine and price coverage; parks and monuments do not require menus; monuments do not require opening hours. `source_description` is distinct from a generated template description.

## Network safeguards

Only public, unauthenticated HTTP(S) GET requests are made. Website fetches are deduplicated by normalized URL. HTTP and DNS concurrency are bounded at eight; each host is serialized with at least 0.8 seconds between requests and advertised crawl delays are respected. Requests have bounded bodies and request deadlines. Private/internal addresses, credentials in URLs, unsafe schemes and ports are rejected. DNS addresses are checked and pinned for the connection, including redirect targets; HTTPS keeps the original SNI and Host. Connections close after each request to avoid sharing an IP-pinned TLS session between virtual hosts. Proxy environment settings and automatic redirects are disabled.

Website robots rules are enforced. A narrowly allowlisted exception applies only to documented Overpass read-only consumer API endpoints, using the [published public-instance policy](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances). API use is sequential, bounded to exact existing source IDs, and endpoints stop after three repeated overload/network failures; that stop state survives resumption. Redirects outside the allowlist regain ordinary website robots enforcement.

All three configured public Overpass endpoints failed during execution. Their attempted responses and errors are archived. The 5,807 requested OSM source IDs, covering 5,592 canonical rows, are explicitly incomplete. The cached Kazakhstan PBF was inspected only as a possible historical fallback: its replication timestamp is `2026-10-17T20:20:51Z`, and it is not counted as current branch verification.

## Artifacts and review interface

The output directory contains:

- `fetches.jsonl`: append-only HTTP observations; repeated attempts preserve earlier outcomes.
- `cache/`: retained source responses and fetch metadata. New response bodies include content hashes in their filenames, so refreshes do not overwrite an earlier body.
- `rows.jsonl`: one row per canonical ID, exact source and website status, applicable fields and gaps, current identity status, and explicit deletion/search flags.
- `candidates.jsonl`: JSON-LD and known Dodo/Marwin/CityPass directory facts, with canonical ID, source ID where available, identity evidence, original facts, source URL, actual fetch time and raw cache hash. These facts require review.
- `audit-osm-*`: exact requested IDs, public API outcomes, per-ID incomplete observations, endpoint stop state and policy rationale.
- `summary.json` and `report.md`: exact counts, category denominators and limitations.

Actual acquisition timestamps come from the UTC clock. The user's requested `2026-10-19` as-of label is stored separately and is not substituted for a fetch timestamp. Ratings are taken only from explicit JSON-LD review ratings on a five-point scale, with their source preserved; neither source confidence nor popularity becomes a visitor rating. Dated hours are not flattened into an undated regular schedule. Raw menu and price links remain candidates.

The first attempt exposed DNS queue starvation, and a later attempt exposed malformed redirect handling. The affected initial results were retained and retried after regression tests. Older redirect metadata that logged the final URL is recovered conservatively using the SHA-256 cache key for the original requested URL; raw bodies and actual acquisition times remain unchanged.

The final network pass was stopped gracefully at the parent's explicit request after repeated `wa.me` timeouts. Its exact unrefreshed tail is 35 URLs; `audit-host-outage.json` retains their original observations and the repeated host failures. The report labels these `retry_not_completed_host_outage`, with `network_pass_status: partial_host_outage`. There are 4,518 bounded target outcomes and 35 uncompleted retries, rather than a claim that all 4,553 targets were freshly checked. The final artifact contains 67 exact identity candidates, of which 51 rows have 137 candidate fact values; operation remains separately unknown. The frozen `audit-review-checkpoint-67.jsonl` preserves the exact reviewed candidate IDs, facts and raw source hashes.

## Reproduction

Resume only the initial failed observations without repeating later completed attempts:

```sh
.venv/bin/python -m data.catalog_audit \
  --output eval/runs/2026-10-19-catalog-refresh/source-audit \
  --concurrency 8 --timeout 10 --delay 0.8 \
  --retry-incomplete --retry-before 2026-10-18T23:15:00+00:00
```

Rebuild source-aware reports and candidate extraction without network access:

```sh
.venv/bin/python -m data.catalog_audit \
  --output eval/runs/2026-10-19-catalog-refresh/source-audit --report-only
```

The host-outage archive is an explicit final deferment record. A later recovery run must reconcile its deferment entries against actual fresh checks; report-only preserves the recorded partial status.

Focused verification: `.venv/bin/python -m pytest data/tests/test_catalog_audit.py -q`. The tests were written and observed failing before each corresponding implementation change. The initial cycle had 20 expected missing-module failures followed by 20 passing tests. Later regressions separately reproduced unbounded DNS work, redirect failures, incomplete resume behavior, unsafe API redirect scope, overwritten raw bodies, slow-stream deadlines, invalid geographic wrapping, ignored crawl delays and deeply nested untrusted JSON-LD.
