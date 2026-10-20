# Event feed collection and refresh

The event feed reads the persisted event archive. Its collector reads the Astana listings on [Ticketon](https://ticketon.kz/astana) and [Sxodim](https://sxodim.com/astana/afisha), normalizes embedded schema.org JSON-LD and optionally links a venue to a POI. Events with unknown venue coordinates remain available to the feed. Venue matching remains a separate requirement for route suggestions.

From the repository root, refresh with the existing CLI:

```sh
PYTHONPATH=backend .venv/bin/python -m pipeline.cli events
```

The command updates `data/processed/events.jsonl` by source identity. It retains ended events, records absent from the latest listings, and prior records from inaccessible sources. It does not implement a deletion policy: a vanished page does not prove cancellation or justify removing historical content. The initial archive only covers records collected previously; it is not a complete historical catalogue.

The newsfeed reads this dedicated, mutable event archive in both `DATA_SNAPSHOT_MODE=legacy` and `canonical`. Its API reloads the file for each request, so an atomic refresh becomes visible without restarting or republishing the POI catalogue. Recommendations retain their own immutable POI/event bundle and venue eligibility rules; this change does not alter them. The newsfeed has no POI joins and deliberately adopts event updates independently. The event collector and its scheduled workflow do not publish POI bundles or move the `data/processed/current` pointer.

Existing IDs survive updates. A source and its event URL identify a series, with an exact source ID or title/venue/address/start combination as a fallback when a URL is unavailable. Separate source records are retained so the API can group likely duplicates while preserving attribution and source links. Repeated requests do not create a new publication or discovery date.

| Field | Meaning |
| --- | --- |
| `schedule_kind` | `continuous` for a start/end interval; `sessions` when the source supplied actual sub-events. A generated `[start]` marker does not imply a one-day exhibition. Legacy records without the field are inferred conservatively by the API. |
| `published_at` | Explicit event `datePublished`, or publication metadata on the event detail page. Sxodim details supply a matching `Article.datePublished`, an explicit publication meta tag, or a visible `Дата публикации` day. Exact source timestamps retain their timezone and precision; a visible day alone becomes `YYYY-MM-DD`. Remains unknown when the source supplies no valid publication date. |
| `first_seen_at` | Stable earliest known collection time. Existing records are backfilled from their own previous `fetched_at` during a successful merge, including retained archive rows. |
| `fetched_at` | The latest time this record was observed by the collector. This is collection freshness, not the feed publication sort key. |
| `description`, `image_url` | Plain description and image URL supplied by the event source. Missing editorial metadata on a later refresh does not erase previously collected values. |
| `price_from` | Explicit source price; numeric `0` is preserved as free, `null` means unknown. Missing prices are never assumed free. |
| `source_venue`, `source_address`, `source_lat`, `source_lon`, `source_city` | Source venue evidence, retained separately from a possible POI resolution. |
| `match_status`, `match_method`, `match_candidates`, `poi_id` | Venue resolution diagnostics. Ambiguous branches remain unresolved; a common partial name is insufficient. |

Invalid coordinates and Ticketon's known shared placeholder are removed from the usable map point while source evidence is preserved. Explicit non-Astana city records are rejected. Astana records without coordinates remain in the archive. The feed should use `published_at` and then `first_seen_at` for recency; `fetched_at` updates must not move an old event to the top.

The command prints a report and writes `events_refresh.json` next to the archive. `status` is `ok`, `partial` or `failed`; `sources` contains each source's status, collected count and errors. Per-source `empty` means no rows were returned without an access error. An inaccessible source is never reported as a successful empty source. `events_unresolved.json` records retained venue ambiguities. The archive is replaced atomically only after complete serialization. With no accepted refreshed records, its existing bytes remain intact.

The new [events-refresh workflow](../.github/workflows/events-refresh.yml) proposes a refresh every two hours and supports manual dispatch. It runs the collector tests, saves diagnostics and opens or updates a review PR. A total collection failure fails the job and does not open a misleading data PR; a partial refresh can propose updated accessible-source records with source errors included in the report. It does not merge or deploy. The existing weekly full-data workflow is unchanged. Adding this workflow locally does not execute it or push any branch.

Requests use an identifying user agent, a one-second delay for uncached fetches, a 15-minute listing/Ticketon-event cache and a 72-hour Sxodim-detail/venue cache. Each unique Sxodim event detail is fetched once per collection. Publication enrichment accepts only `https://sxodim.com/astana/event/...` URLs; an Article must identify that event through `mainEntityOfPage`, `url` or `@id`, and an explicit canonical URL must agree. An inaccessible or invalid detail contributes source diagnostics without discarding its listing event or erasing a previously collected publication date. `dateModified`, offer `validFrom`, event occurrence dates and image upload folders never supply a publication date.

A live check on 2026-10-20 confirmed that [«Любимая Астана»](https://sxodim.com/astana/event/obzornaya-ekskursiya-po-gorodu-lyubimaya-astana) has the visible publication day `05.06.2024` and Article `datePublished` of `2024-06-05T15:12:00+05:00`; [«Cancel culture»](https://sxodim.com/astana/event/expert-talk-cancel-culture-kak-kultura-otmeny-vliyaet-na-biznes) has `2026-09-24T11:01:00+05:00`. Sxodim's listing Event JSON-LD omitted those dates. Publication describes the original source page, which may advertise later recurring sessions.

There is no CAPTCHA, waiting-room or access-block bypass. An ordinary Ticketon request entered a redirect loop; Ticketon publication metadata is therefore unverified in this environment, and its previous records remain available. No source extraction can guarantee coverage of events missing from the inspected listings, sold-out session details or JavaScript-only content.
