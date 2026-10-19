# No-website food branch discovery, 19 October 2026

The bounded batch covers 30 previously unenriched cafe/restaurant records within 949m of EXPO. It yielded five branch bindings: Dami, Тәп-Тәтті, two Dodo branches, and Gasteria MEGA Silk Way. The two additive artifacts contain39 attributable fields and97 exact dine-in item prices. Missing attributes remain unknown.

Gasteria's primary merchant menu explicitly identifies MEGA Silk Way, Cabанбай62, and onsite placement. Only publisher-visible main-menu items are included; no ingredients are inferred. The publisher timestamp2026-04-14 and menu version136 are preserved. The publisher's loaded frontend verifies primary-price division by100. RawHTML, publicmenu JSON and frontendprice-unit proof are cached withSHA256. This is the menu served when checked; it is not described as newly updated in October.

Dami hours conflict across sources and are withheld. Its directory menus/price page has an explicit26March2026 update; the currentexact-itemprice assertions are not copied. Dodo facts identify delivery/pizzeria formats, with no invented dine-in item prices. Тәп-Тәтті's08:00–22:00 completeweeklyschedule is extracted from publicdata bound to its matchedfirmID, never inferred from an opens-at message.

Joule27 has an explicit Yandexclosure statement, exactMangilik57A address and matchingphone. It is a separate reviewed-source candidate for root to apply. TattiLatte has an explicit closedmarker in searchresults with exactUlyDala6/3+phone, but directsource403; it remains a closurecandidate with incompletefetch. No canonical deletion or exclusion was performed here.

The remaining statuscounts are six identitydisputes, four historical/unverifiedlisting cases and thirteen incompletecurrent-source checks. There are zero confirmed no-information results and zero claims of exhaustive source search. Wrong-address Totem, moved/different Whoopie and CroissantFactory points, SignoraViva's possible rename/replacement and unrelated BakerStreet retail are retained as unresolved. SearchHTTP404, sourceHTTP403/429 and absentresults never mean closed.

# Resumable wider queue

`discovery-queue.py` prepares allremainingno-websitefoodrows, excludes acceptedsidecars, prioritizes EXPO and appends per-provider evidence to `discovery-queue-events.jsonl`. It writes no POI data or exclusion decisions. Run:

```sh
.venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --limit 2000 --max-requests 2500 --delay 1.25
```

At launch there were1091 remainingrows. Public2GIS andBingrespond; YandexMapssearch returned429 and is held behind a persistentprovider circuit. Google429 and DuckDuckGohumanchallenge were not bypassed. A403/429 or challenge immediately stops furthercalls to that provider. `--prepare-only` materializes a currentsummary fromdurableevents withoutnetwork. `--retry-incomplete` can revisitordinarysourceerrors but respectsproviderblocks. Resume skips alreadyrecordedattempts and reuses unchangedrowbindings; changedcanonicalrows invalidate their oldattempts.

Minimumthree distinct successful sourcechecks and an explicitcompletedhumanreview are required before the queue can label no-information. Threeemptypages alone are insufficient. Everycandidate remains unreviewed, with exactname plus exactaddress or independentcoordinates within200m required for lateracceptance. The widerpass is discovery, not verifiedenrichment.

Eightfocusedrunner checks cover404/429/challenge handling, third-source blocks, no-information gates, resume/latest-attempt aggregation and candidate-only publication.
