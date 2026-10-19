# D08 final independent review

Reviewed 2026-10-19 after the attribution implementation was frozen. Verdict: **pass; no blocking reproduction found in this scope**. This review changed only this report.

## Canonical provenance and publication

An independent offline scan read all14,006 canonical records from selected immutable bundle `4e9b6ecc5b4c455f9c0443714afb91b2`. The master SHA remains `803dcffdb4473abddfc97be9cab5a41bc663ee74afc67c560f1723b42f8c1e63`.

The full master contains218 nonempty Wikipedia source descriptions labelled `CC-BY-SA-4.0`. Of these,96 have a primary `source_url` pointing to OpenStreetMap. All218 now produce one complete attribution entry that matches an original Wikipedia `source_refs` URL and licence and the description's own article URL; none were silently attributed to the primary OSM place link. No mismatches or missing metadata were found. Twenty-six canonical excerpts exceed300characters and are bounded when published; the source-excerpt notice is present.

These are two different population scopes:201 of the218 records have canonical category `other` and serve as origin records rather than recommended destinations. The current2,750-place eligible primary pool contains17 of these licensed Wikipedia descriptions, all17 with OSM primary place URLs. All17 serialized correctly in RU, KK, and EN, including validation through `Recommendation`.

The implementation preserves the place's existing primary URL and publishes the description's own article separately under `description_attribution`. Its entries include source, title, article URL, licence, licence URL, contributor attribution, and a localized shortened-excerpt notice. The article must be a valid HTTPS Wikipedia article URL, carry matching `CC-BY-SA-4.0` source evidence, and agree with the description's explicit URL when supplied. Ambiguous article identities, incomplete matching attribution, unsupported source prose, and invalid URLs are withheld. Structured fact templates remain distinguishable and do not acquire Wikipedia attribution.

Actual examples inspected include:

- `osm:node/4894937300`: primary OSM node URL; description linked to [Национальный музей Казахстана](https://ru.wikipedia.org/wiki/Национальный_музей_Казахстана), retaining its saved article title, contributor attribution, article provenance, and CC-BY-SA4.0 metadata.
- `osm:relation/16002498`: primary OSM relation URL; description linked to [Парк Жеруйык](https://ru.wikipedia.org/wiki/Парк_Жеруйык). Duplicate original reference records for the same article do not create duplicate or conflicting public attribution.
- `osm:way/1196402246`: primary OSM way URL; description linked to [Астанинский ботанический сад](https://ru.wikipedia.org/wiki/Астанинский_ботанический_сад), separate from its place URL and independently verified hours evidence.

These links identify stored source provenance; no live source or legal review was performed during this final code review. Unknown licences did not become publication permission.

## Frontend and accessibility labels

I inspected the real `toPlace`, `restoreSaved`, `TrustList`, and details-dialog integration. The real trust panel renders the actual article URL, contributor attribution, clickable [CC-BY-SA4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/), and the response's localized excerpt notice. An older Wikipedia response or saved card without attribution has its excerpt withheld. Saving/restoring current attribution does not substitute the primary place URL.

An additional independent check passed actual backend `_item` responses through Vite SSR, `toPlace`, the real `TrustList`, and `restoreSaved`:51 localized payloads covering all17 eligible Wikipedia places. Every article link, licence link, notice, excerpt, and saved attribution roundtrip matched. No copied source text is reproduced in this report.

Accessibility values `yes`, `limited`, and `no` use neutral wheelchair-access wording qualified as according to the source. They no longer turn `wheelchair=no` into a claim of steps or assert OSM as the field source. Existing preference wording expresses the user's requested filter; this review's attribution correction concerns facts asserted about individual places.

## Fresh checks and limits

```text
.venv/bin/python -m pytest ayat_backend/tests/test_description_attribution.py ayat_backend/tests/test_team_data.py ayat_backend/tests/test_canonical_index.py ayat_backend/tests/test_api.py -q
55 passed in8.95s

cd frontend && npm test
20 passed;0 failed
```

The backend tests include complete attribution, missing references/licence, mismatched article, unsafe URL, and unlicensed-source suppression. The frontend tests execute actual rendered components, legacy missing-attribution suppression, and neutral accessibility labels. My separate whole-master scan found218 matching attributed Wikipedia publications,0 withheld licensed excerpts, and0 errors. `git diff --check` passed.

The selected dense matrix still loaded successfully against the unchanged2,750-place document/policy view. No eligibility/store/index change was needed. Network/provider use was disabled in independent data/runtime checks; no paid calls, email, deployment, source-page fetching, canonical-data edits, or index regeneration occurred.

The latest frontend test run emitted a non-failing Vite HMR port24678 collision warning from the other saved-component test harness (`frontend/tests/saved.test.js` still enables HMR); all20 tests completed successfully. Root owns the final build, live HTTP/UI checks, and regenerated source-fingerprint evidence after the freeze. I did not claim those separately owned checks here.
