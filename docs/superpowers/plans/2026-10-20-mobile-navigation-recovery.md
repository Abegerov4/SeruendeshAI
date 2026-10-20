# Mobile Navigation and Start Sheet Implementation Plan

> **For agentic workers:** Use executing-plans for the shared mobile shell; delegate the independent recovery controls and final review. Track completed checks below.

**Goal:** Open the initial mobile start chooser from the bottom, retain bottom navigation in Events, and repair closely related navigation/recovery bugs.

**Architecture:** Move the existing five-item mobile navigation from Explore into Workspace. Keep the walking workspace mounted but hidden on other public routes, with route-sensitive effects suspended. Render the initial mobile chooser as a bottom-aligned native dialog; preserve desktop chooser behavior and existing product styling.

**Tech Stack:** Existing React/Vite, native dialog, Lucide, Playwright, node:test. No new dependencies.

**Spec:** User request in this conversation: initial mobile window appears from bottom; bottom homebar remains on Events and allows return; inspect analogous bugs. Prior audit: `.impeccable/critique/2026-10-20T16-09-05Z__frontend-src.md`.

## Global Constraints

- Work in the existing linked worktree; preserve unrelated dirty data files.
- Preserve the five current walking navigation destinations and desktop composition.
- Keep private walking context in memory for the current workspace/account lifetime.
- Do not request GPS or recommendations merely by opening the first screen.
- Bottom sheet must dismiss with its close button, Escape and outside tap; address errors remain recoverable.
- Keep navigation and content clear of each other and safe areas on narrow screens.
- No publishing or remote account mutations; leave code reviewable in this worktree.

## Review Focus

- Direct links to events/archive/detail/saved still show working mobile navigation.
- Returning to chat/map/places/plan retains the result and draft, with one visible navigation only.
- Hidden walking workspace cannot keep a top-layer dialog or keyboard state over other pages.
- Start sheet fits 320×568, including address entry and failed lookup; desktop start chooser stays inline.
- Authentication/account changes retain the existing workspace isolation; empty Plan leads to usable chat.

### Task 1: Reproduce primary mobile regressions

**Files:** `frontend/tests/browser/mobile-navigation.spec.js`; temporary Playwright config uses the root Vite on port 5177.

- [x] Add behavioral tests for bottom-aligned start dialog, its dismissal/recovery and lack of automatic API/GPS.
- [x] Add tests for persistent navigation from direct event routes and returning to walking views with results/draft intact.
- [x] Run tests on existing implementation and record expected failures.

### Task 2: Shared shell and bottom sheet

**Files:** `frontend/src/main.jsx`, `frontend/src/pages/Explore.jsx`, `frontend/src/components/MobileNavigation.jsx`, `frontend/src/site-navigation.css`, `frontend/src/mobile-app.css`, `frontend/src/components/Chat.jsx` if active scroll effects require guarding.

**Interfaces:** Workspace owns `view`, passes `tab`, `setTab`, `active`, `onPlacesCountChange` into Explore. MobileNavigation consumes `path`, `view`, `onSelect`, `count`. Explore calls `onPlacesCountChange(real.length)` and renders no navigation of its own. RouteOverview consumes `onAsk`.

- [x] Extract shared navigation and render it once for public pages; hide duplicate mobile header navigation.
- [x] Preserve walking workspace on route transitions and disable route-sensitive hidden UI effects.
- [x] Open the initial mobile StartChooser inside a bottom-aligned named native dialog with focus handling, safe-area sizing and scrollable content.
- [x] Pass `onAsk={() => showTab('chat', false)}` to the empty-plan recovery control.
- [x] Make primary regression tests pass, adapting existing mobile start selectors to the intentionally moved dialog.

### Task 3: Independent recovery controls and bug hunt

**Files:** delegated agent owns `frontend/src/components/Layout.jsx` AuthHeader only, `frontend/src/components/RouteOverview.jsx`, scoped `frontend/src/life.css`, `frontend/tests/browser/mobile-recovery.spec.js`.

- [x] Red/green test: mobile auth back link has a meaningful name and usable hit area.
- [x] Red/green test: empty Plan offers 'Спроси Серу' and returns to editable chat.
- [x] Independent audit confirmed lost feed pagination/scroll and archive origin on detail errors.
- [x] Repair these two event navigation defects with red/green browser tests in Events/EventDetail/EventCard.
- [x] Keep a guest-accessible saved collection entry in mobile Places after removing the duplicate header menu.

### Task 4: Verification and review

- [x] Run `npm test`, relevant browser regressions and the existing browser suite; record any baseline failures separately.
- [x] Run `npm run build` and one Impeccable detector pass over changed UI targets, checking false positives.
- [x] Inspect rendered mobile start, events, return and keyboard-sized viewports in Chromium plus desktop.
- [x] Fresh agent reviews the final diff for behavior, hidden effects, navigation and account isolation.
- [x] Stop owned servers/browser sessions; report changes and any remaining device-testing limits.

Progress: existing worktree verified; node baseline 29/29 passing. User's requested small-change direction supplies authorization; no additional approval handoff needed.

Final verification: full browser suite 47/47 passed (Chrome/Chromium, 1.1m); npm test29/29 passed; production build passed; git diff --check clean. Review found a 320px keyboard clipping edge; a new failing visualViewport300 regression now passes after focus/error reveal. Independent final review clean. Impeccable detector: only the existing false positive on the route-arrow CSS triangle in live.css:111. Mobile screenshots inspected at320/390; physical Safari/iOS and real touch keyboard remain untested. Owned browser, Vite and backend stopped. Changes left uncommitted for review.
