# Mobile Audit Completion Implementation Plan

**Goal:** Resolve the four remaining findings authorized by the user: landscape layout, oversized event poster, small action targets and low-contrast text.

**Architecture:** Retain the existing visual identity, shared navigation and in-memory workspace recovery. Align the mobile JS and CSS breakpoint at 1023/1024 px so large phones keep the mobile layout in landscape. Keep the event summary ahead of bounded poster art on mobile, enlarge standalone hit areas without overlapping calendar cells, and use darker semantic muted text colors.

**Spec:** The four remaining findings listed immediately before the user's “давай исправляй”; original audit `.impeccable/critique/2026-10-20T16-09-05Z__frontend-src.md`.

**Constraints:** No dependencies or remote mutations; preserve all previous frontend work and unrelated dirty data. Keep desktop layout at 1024 px and above. Preserve poster artwork with contain fitting. Keep standard action targets at least 44×44 px where space permits, including 7 calendar columns at 320 px. Normal functional text contrast must reach 4.5:1; logos/disabled elements are handled separately.

1. **Landscape shell — root.**
   - [x] Add and observe a failing browser regression for a 932×430 walking workspace with visible navigation/composer and no header overlap.
   - [x] Normalize mobile/desktop media thresholds after workers finish; align initial view and Explore detection.
   - [x] Correct short-screen navigation clearance, keep keyboard viewport recovery working, verify portrait→landscape and event return.
2. **Poster hierarchy — poster worker.**
   - [x] Put title/facts/price/source action before the poster on mobile, bound artwork height and retain full image.
   - [x] Preserve desktop and archived/error behavior; adapt stale mobile-order assertions and run meaningful regression checks.
3. **Contrast — contrast worker.**
   - [x] Measure rendered location/auth/other muted copy; adjust scoped semantic text colors without changing layout.
   - [x] Check RU/KK/EN and actual contrast with clean axe/computed styles, excluding logotype and disabled exceptions.
4. **Touch targets — touch worker.**
   - [x] Enlarge chat/filter/map/header/details/calendar controls, preserving narrow-screen fit and no overlapping dates.
   - [x] Verify actual hit boxes and interaction at 320/390/430 plus short landscape.
5. **Integration and verification — root.**
   - [x] Run all browser and unit tests, build, diff checks and one detector pass.
   - [x] Inspect rendered portrait/landscape/mobile events and desktop, then request an independent final review.
   - [x] Stop owned services/browser sessions and record completed evidence and remaining physical-device limits.

Execution: root and three independent workers own distinct surfaces; root normalizes threshold strings only after worker edits finish. Previous baseline: 47 browser / 29 unit tests passed in the navigation-recovery task.


Observed implementation evidence:
- Landscape regression initially failed because the mobile bar disappeared at 932×430. A second regression reproduced portrait→landscape falsely setting keyboard-open state; both pass after matching JS/CSS thresholds, reserving bottom navigation space and gating shrink detection on input focus or an already observed keyboard.
- Short-landscape filters initially extended above the viewport. Fixed/scrollable positioning now keeps the panel reachable with and without the keyboard.
- Poster tests cover portrait, square and landscape artwork at 320/390/430 px; event facts/actions precede bounded, uncropped mobile artwork while desktop keeps its original image priority.
- Standalone mobile controls measure at least 44×44 px, including seven distinct 44 px calendar columns in a 318 px dialog at 320 px viewport width. Small inline attribution/credits remain inline.
- Rendered RU/KK/EN contrast checks corrected location/auth/placeholder/saved/filter text to at least 4.5:1; enabled outside-month calendar dates use the existing calendar muted color #53664f after independent review (6.21:1 on white, 5.46:1 in range and4.92:1 on hover).
- Independent final review found and reproduced desktop header clipping and brand/Nearby overlap at 1024–1100 px. Nine locale/width regressions passed after compact spacing and nonshrinking logo. Boundary probes then found RU1251 and KK1251/1280 clipping; 27 header regressions now cover RU/KK/EN, empty/populated state and 1024–1440 px. Compact styling extends through1399 px; independent loaded KK1399/1400 visual and browser checks pass, with full nav icons restored at1400 px. No Important/Critical findings remain in the reviewed scope.
- Verification screenshots: `.impeccable/critique/evidence/mobile-audit-completion-2026-10-20/` (portrait event, narrow calendar, landscape chat/filters, desktop RU/KK).
- Automated visual testing uses installed Chromium/Google Chrome. Physical iPhone/Safari testing has not been performed.

- One preliminary full run stopped at60/61 passes because an external OpenStreetMap tile remained unfinished during an isolated image harness’s default navigation load wait. Trace showed local app scripts/API completed promptly and the image component test had not started. The final expanded suite passed79/79 (2.4m), including both image tests. A final color-only calendar refinement then passed6/6 targeted events checks (9.6s).


Final verification and cleanup:
- Full browser suite: **79/79 passed** using installed Google Chrome, including27 responsive header cases and the earlier navigation/error/keyboard recovery regressions.
- Unit suite: **29/29 passed**. Production build succeeded after the final calendar color change; the existing large-chunk advisory remains.
- `git diff --check` passed. Whole-source design detector returned only the known map-arrow CSS triangle false positive at `live.css:111`; final header/calendar scoped detector returned no findings.
- RU/KK/EN rendered checks and independent review are complete; no Important/Critical issue remains in the reviewed four-finding scope.
- Root/worker/reviewer browser sessions are closed. Owned Vite5177 and temporary backend8000 were stopped; temporary audit SQLite files removed. No dependency, commit, push, deployment or unrelated data edit was made.
