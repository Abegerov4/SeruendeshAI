# Events Feed Implementation Plan

> **For agentic workers:** execute the scoped tasks below; the root coordinates integration and independent review. Initially local-only; on 20 October the user authorized a feature commit and push to the new branch `new-feature/events`.

**Goal:** Ship the agreed event feed in the existing application, with a calendar date/range filter and real source data.

**Architecture:** FastAPI exposes the dedicated mutable event archive with session-aware filtering. The collector preserves history and stable discovery dates; React consumes its API and uses an accessible custom month-grid calendar without dependencies.

**Tech Stack:** React 19, Vite, lucide-react, FastAPI, Python 3.12, pytest, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-events-feed-design.md`

## Global Constraints

- Work in the existing linked worktree `big-data`; preserve unrelated local data changes.
- Commit and push only the event feature to `new-feature/events`, as subsequently requested by the user. Preserve unrelated catalogue changes outside the commit. No invented event records in the application.
- Maintain the approved prototype's minimal feed and the existing project's brand/header.
- Timezone is Asia/Almaty. Announcement time and occurrence time are distinct.
- Keep source attribution and fail honestly when upstream collection is unavailable.

## Review Focus

- Events with sparse discrete sessions must not match days between sessions.
- Unknown prices must remain distinct from free admission.
- Multi-day date-only ends and timezone offsets must preserve inclusive dates.
- Incomplete/failed source refresh must retain history without bumping first-seen order.
- Keyboard calendar, cancelled dialogs and stale network responses must preserve applied state.

### Task 1: Snapshot event API

**Owner:** events_backend. **Files:** `backend/app/event_feed.py`, router registration in `backend/app/main.py`, `backend/tests/test_event_feed.py`, API documentation.

- [x] Write and run failing behavioral tests for list/detail, announcement ordering, cross-source dedupe, session-aware date/archive boundaries and query validation.
- [x] Implement GET `/api/events` and `/api/events/{event_id}`. Params: view, q, category, source, price, date_from, date_to, month, offset, limit. Response includes items/total/paging, today, categories/months and updated_at. Feed reads its dedicated mutable event archive independently of the POI snapshot and route venue eligibility, in both catalogue modes.
- [x] Run scoped tests; report contract and coverage.

### Task 2: Persistent event collection

**Owner:** events_collection. **Files:** `backend/pipeline/events.py`, `backend/tests/test_events_collection.py`, `docs/events-feed-refresh.md`, optional dedicated PR-only refresh workflow.

- [x] Write and run failing tests for archive preservation, source failure, first-seen stability, JSON-LD metadata and free-price handling.
- [x] Normalize source publication/description/images and merge refreshes without discarding archive or source records. Report source health. Do not require a matched POI for an Astana feed event.
- [x] Verify parsing against ordinary accessible upstream content, run scoped tests and document refresh/restrictions.

### Task 3: Event UI and calendar

**Owner:** events_frontend. **Files:** `frontend/src/pages/Events.jsx`, `frontend/src/components/EventCalendar.jsx`, `frontend/src/events.js`, `frontend/src/events.css`, source assets and event tests.

- [x] Write and run failing date/request tests; implement API client and calendar day/range utilities.
- [x] Implement approved list/archive/detail views, real source labels, search/facets/date filter, loading/error/empty/pagination states. Cancel superseded requests.
- [x] Implement native-dialog month grid with month navigation, range preview, apply/reset/cancel and keyboard support.
- [x] Add browser interaction tests and translation entries; run unit/browser tests and build.

### Task 4: Project integration and verification

**Owner:** root. **Files:** main.jsx, Layout.jsx, locale messages, scoped header styles, integration notes if needed.

- [x] Add global navigation and all event routes/title handling; retain existing pages and responsive header behavior.
- [x] Apply event UI translations for RU/KK/EN.
- [x] Run local backend/frontend with real snapshot. Check list/detail/archive/calendar and source links end to end; render desktop/mobile.
- [x] Review combined implementation independently, fix material findings, run relevant regression suites/build and diff checks.
- [x] Leave the feature reviewable and report remaining upstream/environment limits. Subsequent commit/push authorization is recorded above.

## Progress

- Existing worktree confirmed. Frontend baseline: 17 tests passed. Backend baseline started.
- User's execution authorization covers integrating the approved mockup and adding the calendar; no additional design approval is needed.
- User subsequently requested commit and push to a new events branch. The requested `new feature/events` is normalized to the Git-valid `new-feature/events`.

## Final verification

### Compact cards, adaptive detail and publication correction

- User approved the compact feed and adaptive detail page. Natural image dimensions select landscape, portrait or square layout; complete posters remain visible on the detail page, and failed images reset to a compact fallback. Feed descriptions and exact announcement clocks were removed.
- Publication and first discovery have distinct labels. Sxodim's matching Article metadata supplies the original publication timestamp; neither modification dates nor refresh timestamps are used. Ticketon publication remains unverified because ordinary requests reach its waiting room.
- The local archive was enriched with explicit publication dates for all 99 Sxodim records. Exactly `published_at` changed on those rows; all 202 IDs, schedules, prices, first-seen and refresh timestamps were preserved. The API now returns the tour publication as `2024-06-05T15:12:00+05:00`, with its independent discovery time `2026-10-20T16:07:50+05:00`.
- Current build passed; 28 frontend unit tests, 31 browser tests and 109 focused backend tests passed. Browser cases include desktop/mobile orientation, cached/replaced/failed images, source versus discovery dates, the original publication year, price/source actions, navigation and existing app behavior.
- Detail-page source actions use a red Sxodim button and green Freedom Ticketon button, including hover, active and keyboard-focus states. Computed desktop/mobile text contrast is at least 4.79:1; normal, hover and active states were checked against WCAG AA. Production build and the 28 frontend / 109 focused backend checks were rerun before the feature commit.
- After adopting publication dates, three live API/browser scenarios passed again; an additional live tour scenario passed for the exact 2024 publication, separate 2026 discovery label, complete landscape poster on desktop/mobile and absence of the misleading announcement badge in the feed. Real desktop/mobile renders were inspected. API counts remain 195 upcoming and 5 archived. The live search legitimately returns both source records because their occurrence intervals differ; verification selects the Sxodim record by stable ID.
- Full repository run: 1644 passed, 160 skipped, 165 subtests passed; four unrelated failures remain. The catalogue test below was already failing before this feature. Photo tests `infra/photos/tests/test_card_photos.py::test_readiness_retries_startup_and_fails_on_bad_credentials` and `::test_readiness_exhaustion` lack `botocore`; `rag/tests/test_snapshot_policy.py::test_search_and_lookup_hold_same_version_during_promotion` lacks `backend.app.rag_adapter`. No unrelated catalogue or environment fixes were made.

### Initial integration checks

- Production build passed; frontend unit tests: 24 passed. Browser regressions: 18 passed, including 6 event scenarios and 12 existing application scenarios.
- Real API/browser smoke: 3 passed, including pagination, deep links, archive, calendar/filter composition, mobile navigation and RU/KK/EN at 320px. Single-server built SPA/API/detail/assets smoke passed.
- Final focused backend suite: 86 passed (event API, collector, venue identity and existing route-store behavior). Full backend suite before the final collector date-only-end boundary fix: 636 passed, with the same pre-existing catalogue-count failure seen at baseline. The final boundary fix passed its targeted regressions.
- Existing failure: `tests/test_team_data.py::test_real_master_is_preserved_and_all_source_ids_remain_available` expects 2742 adapted places; current user catalogue supplies 2736. It was present before implementation (558 passed, 1 failed).
- Mechanical design detectors: no findings on new event UI or shared navigation; desktop/mobile renders inspected.
- Real archive: 202 source records; 195 upcoming + 5 archived after excluding two outside-Astana records at verification time. All 140 original IDs retained, legacy first-seen dates backfilled, 96 source-proven schedule kinds added.
- Ordinary live Sxodim fetch returned 96 records with images/descriptions. Ticketon entered a waiting-room redirect loop; previous 103 Ticketon records retained, refresh status explicitly partial. Scheduled PR-only workflow prepared locally, not executed remotely.
- Final review fixes: incomplete source schedule preservation, explicit single-session semantics, independent mutable feed across catalogue modes, continuous interval display, pagination across duplicate-only pages, and date-only end inclusivity.
- Pre-existing user-change diff hash remains `4b40637d44dd581bd9b7863034b09576d82c6897ac02bf018643e63024ab4f61`. Index empty; no commits or pushes.
