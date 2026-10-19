# City services refresh — 19 October 2026

Published source sidecar: `data/sources/city_services_2026-10-19.json`.
Validated API: `data.city_services.load_city_services()` returns `CityServicesCatalog`;
use `.model_dump(mode="json")` for normalized dictionaries.
`departures_on(service, date)` returns only exact-date verified departures.

Eight services, six named operators, eleven explicit ticket offers. Eleven public
pages were fetched successfully at 2026-10-18 23:13:29–30 UTC (19 October in
Asia/Almaty). Two returned gambling/SEO titles and were excluded as source
anomalies: the Visit Astana mosque and murals detail pages. Their captures are
retained for review. No paid or LLM/embedding calls were used.

Services: RedBus Astana; Dual.KZ parks and river package; Blue Necklace boat
cruise; National Museum Gold halls tour; Astana Opera theatre lesson; Tamyr tea
ceremony; Tamyr ethno tasting; Nurzhol walking tour.

RedBus boarding is before the main entrance to Baiterek. The official operator's
2GIS boarding link is preserved. Every 14/16-bank attraction is explicitly
`pass_by`, separate from the boarding stop. Ambiguous canonical POI records and
operator office addresses were not assigned boarding geometry.

No exact-date departures are published. RedBus's 12.10–18.10 notice omits its
year; other advertised session times are undated. Neither establishes a last
departure on 19 October. Provider duration (60–90 vs 120 minutes), child-age
boundary (free through age 3 vs concession starting age 3), FAQ currency symbol,
and legacy stop-table disagreements remain explicit conflicts.

Museum ~2000 KZT is an advertised average spend, not a confirmed ticket price.
The parks package's 250 у.е. is not converted to USD/KZT. The boat's 20000 KZT
rental and 4000 KZT per participant are additive. Tamyr's later booking notice
omits the year and contradicts an earlier walk-in statement; both are retained.

Verification: observed missing-module failures before implementation, then 13/13
service tests passed. A broader data run during the other agent's implementation
had 286 passes and three in-progress catalog-audit failures (missing
`osm_id_batches`, missing `osm_observations`, missing `content_flags`). The root
agent owns final integrated verification. Hashes for catalog and service module
are recorded in `services-audit.json`.

Frontend integration: source-backed service cards now consume `service_results`
alongside POI cards. A single service is remembered for follow-up questions;
unrelated/ambiguous results and a new chat clear that context. Source conflicts
remain visible and conflicting ticket offers are hidden. Additive prices retain
their separate units and conditions. Service-only answers no longer show the
empty-places message or a zero-minute walking plan.

Frontend verification: observed red tests for missing service mapping, follow-up
identity, card renderer, chat guidance and the empty-results guard; final
`npm test` passed 42/42 and `npm run build` succeeded. Vite reports a 553.02 kB
chunk-size warning. An isolated browser rendered the real RedBus catalog card at
390 px with no horizontal overflow, exercised both disclosure sections and
verified the provider map link, three source links and 19 October Almaty check
dates. `services-card-mobile.png` and `services-card-expanded-mobile.png` retain
the visual check. `services-preview.html` is a review fixture, not app content.

Ordinary place cards also render accepted branch facts, at most three menu entries, and prices with source/check date, channel and unit. Average check is labelled separately; delivery is explicit. A second isolated browser check used the actual RUMI Mega Silk Way sidecar row at390px: three menu entries, source links and no horizontal overflow (`services-food-card-mobile.png`).
