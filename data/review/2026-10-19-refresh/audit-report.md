# Whole-catalog public-source audit

Generated: 2026-10-18T23:39:34.006259+00:00. User as-of label: 2026-10-19.

Records covered: **14,006**. Listed website rows: **5,896**. Distinct source fetch results: **4,553**.

Rows with missing applicable fields: **14,006**. Rows without current branch confirmation: **13,939**.
Rows with incomplete or unavailable website checks: **11,222**. Completed exhaustive searches: **0**. Deletion eligible: **0**. Confirmed permanent closures: **0**.

Fresh exact branch identity matches: **67**; fetched generic/unmatched source rows: **2,743**; incomplete branch checks: **11,196**. Current operation is separately unproved: **0** verified operating rows.

## Fetch outcomes

| Outcome | Distinct URLs |
|---|---:|
| blocked_robots | 981 |
| blocked_unsafe_url | 5 |
| http_error | 207 |
| incomplete_body_limit | 15 |
| incomplete_redirect_limit | 3 |
| incomplete_robots_unavailable | 1,331 |
| network_error | 64 |
| retry_not_completed_host_outage | 35 |
| successful_fetch | 1,912 |

## Applicable field gaps

| Field | Missing | Applicable rows |
|---|---:|---:|
| address | 5,521 | 14,006 |
| category | 0 | 14,006 |
| cuisine | 2,105 | 2,105 |
| description | 0 | 14,006 |
| kid_friendly | 14,003 | 14,006 |
| lat | 0 | 14,006 |
| lon | 0 | 14,006 |
| menu_url | 2,105 | 2,105 |
| name | 0 | 14,006 |
| opening_hours | 11,791 | 13,871 |
| phone | 5,971 | 13,871 |
| price_range | 2,105 | 2,105 |
| source_description | 13,737 | 14,006 |
| website | 8,110 | 14,006 |
| wheelchair | 13,701 | 14,006 |

## Interpretation

- A successful HTTP fetch is not proof of current operation.
- Listed websites include chain homepages and social profiles; official ownership is not independently established.
- No-URL, robots denial, HTTP or network failures are incomplete checks, never a closure or proof of absence.
- This pass checks known source URLs only; it is not an exhaustive web search and authorizes no deletions.
- No exhaustive 2GIS or general web search/index is available in this pass; public listed 2GIS URLs alone do not close that coverage gap.
- Overture STAC catalog links are release-level references, not exact branch pages; no generic SPA requests are issued per row.
- Raw JSON-LD may describe other branches; all candidate facts require identity review and source rights review.
- Availability/closure is unknown unless a separate branch-specific source explicitly establishes it.

## Uncompleted retry tail

Network pass status: **partial_host_outage**. **35** URL retries were not completed after repeated host outages: {"wa.me": 35}.
Earlier per-target observations remain archived. These rows are explicitly `retry_not_completed_host_outage`; this report does not claim that every target was successfully fetched or freshly rechecked.

## Current OSM source checks

Source IDs: 5,807; canonical rows: 5,592; outcomes: {"incomplete": 5807}.
Read-only API policy: https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances

One-off documented read-only API consumer retrieval; sequential bounded source-ID batches, no indexing/API credential use; stop endpoints after three repeated overload failures.

Category-specific counts and denominators are in `summary.json`; every canonical ID is represented in `rows.jsonl`. Raw responses and redirect/DNS metadata are retained in `cache/`. Candidate branch facts are separate in `candidates.jsonl`.
