# Frozen scenario retrieval holdout — 2026-10-19

20 new queries in Russian7, Kazakh7 and English6 cover all30 source-reviewed canonical places. Labels were authored without inspecting retriever/model outputs or tuning retrieval. Existing35-query dataset bytes remain unchanged.

Dataset seal: `aea8b4e0452bde50f202930ae3bda1bf49069f6a6fed49a2e36dc3dd053caa98`. Evidence artifact SHA-256: `2b66ff7991fd403f305bfb12e5043bb14ca3ac3df9e789df4dd02725e7300f6a`.

## Evaluation boundary

Every positive label has canonical IDs, source URLs, supporting fields and explicit scope. Named judgments are complete only within the30-place reviewed set. Other catalog results remain unjudged, including duplicate records and aliases. The broad free-Wi-Fi question supplies six known positive branches; unknown Wi-Fi elsewhere is not a negative. Generic cuisine alternatives also remain partial known-positive labels where other menus are unknown.

These judgments support bounded retrieval MRR/recall/nDCG diagnostics. They do not establish full-catalog precision, current availability, scenario safety or all requirements for a recommendation. Source URLs are provenance, not extra query inputs. No unknown sockets/quiet/accessibility claim is used. TUMO is an enrolled program for ages12–18; greenhouse facts remain subfacility-scoped.

Freeze rule: do not revise labels after seeing benchmark output. Evidence corrections require a new version and a documented reason.

## Queries and provenance

| ID | Language / scenario | Frozen query | Relevant canonical IDs | Evidence |
|---|---|---|---|---|
| sh01 | ru / cafe_work | Покажи кофейни Астаны, где сам филиал прямо указывает бесплатный Wi-Fi. | `osm:node/4543944911`; `osm:node/10295608316`; `osm:node/12917112809`; `overture:6fb348c5-c760-40c1-8afd-94b32cde5400`; `overture:21bc4233-9d79-4931-877d-0ca435d4083a`; `osm:node/10170946742` | [source1](https://coffeeboom.kz/ru/cf/coffeeshops/v-mikrorayone-samal/); [source2](https://coffeeboom.kz/ru/cf/coffeeshops/na-zhes/); [source3](https://coffeeboom.kz/ru/cf/coffeeshops/na-turan/); [source4](https://coffeeboom.kz/ru/cf/coffeeshops/u-dvortsa-shkolnikov/); [source5](https://coffeeboom.kz/ru/cf/coffeeshops/na-kenesary/); [source6](https://coffeeboom.kz/ru/cf/coffeeshops/v-abu-dabi-plaza/) |
| sh02 | ru / child | Где на проспекте Республики посмотреть с ребёнком кукольный спектакль? | `osm:node/2349675581` | [source1](https://visitastana.kz/ru/about-city/what-to-see/gkkp-teatr-kukol-akimata-goroda-astany/) |
| sh03 | ru / child | Нужен именно океанариум Ailand с детским билетом, а не всё развлекательное здание. | `citypass:63` | [source1](https://ailand.kz/ru/attractions/ocean-ru/) |
| sh04 | ru / tourist | Хочу сравнить два символа Астаны: Байтерек и триумфальную арку Мәңгілік Ел. Какие места искать? | `osm:way/230401645`; `citypass:84` | [source1](https://visitastana.kz/ru/map/); [source2](https://visitastana.kz/ru/about-city/what-to-see/triumfalnaya-arka-m-gilik-el9679/) |
| sh05 | ru / tourist | Ищу Дворец мира и согласия, где экскурсии описаны на казахском, русском и английском. | `citypass:88` | [source1](https://visitastana.kz/ru/about-city/what-to-see/dvorets-mira-i-soglasiya/); [source2](https://astana-piramida.kz/contacts) |
| sh06 | ru / tourist | Что найти для знакомства с наследием: дом-музей ювелира Берика Алибая или литературный музей Сакена Сейфуллина? | `citypass:120`; `citypass:89` | [source1](https://visitastana.kz/ru/about-city/what-to-see/dom-muzey-berika-alibaya-/); [source2](https://visitastana.kz/ru/about-city/what-to-see/gosudarstvennyy-muzey-imeni-s-seyfullina/) |
| sh07 | ru / evening | В MEGA Silk Way выбираю ужин: итальянский ресторан, морепродукты или паназиатская кухня. | `osm:node/12093489323`; `osm:node/6404769885`; `osm:node/13397061026` | [source1](https://restaurants.mega.kz/ru/?sm=2) |
| sh08 | kk / cafe_work | Самал 11 мекенжайындағы CoffeeBoom-да тегін Wi-Fi бар ма? | `osm:node/4543944911` | [source1](https://coffeeboom.kz/ru/cf/coffeeshops/v-mikrorayone-samal/) |
| sh09 | kk / child | Он үш жастағы оқушыға Alem.ai ішіндегі TUMO шығармашылық технология бағдарламасын іздеп жүрмін. | `osm:way/454857501` | [source1](https://alem.ai/en/) |
| sh10 | kk / child | Балалар ойнайтын алаңы бар саябақ іздеймін: Орталық саябақ немесе Жерұйық жарай ма? | `osm:relation/15957444`; `osm:relation/16002498` | [source1](https://visitastana.kz/ru/about-city/what-to-see/tsentralnyy-park/); [source2](https://visitastana.kz/ru/about-city/what-to-see/park-zheruyyk/) |
| sh11 | kk / walk | Есіл жағасындағы Триатлон саябағында жүгіру мен велосипед тебуге арналған жолдарды тапқым келеді. | `osm:way/1363058986` | [source1](https://visitastana.kz/ru/about-city/what-to-see/triatlon-park-astana/) |
| sh12 | kk / walk | Сарайшық 13/1-дегі Жетісу саябағын көрсетші. | `osm:way/69232075` | [source1](https://visitastana.kz/ru/about-city/what-to-see/park-zhetysu/) |
| sh13 | kk / walk | Бейбітшілік және келісім сарайының айналасындағы Президент саябағында серуендегім келеді. | `osm:way/112177946` | [source1](https://visitastana.kz/ru/about-city/what-to-see/prezidentskiy-park/) |
| sh14 | kk / tourist | Республика 2 мекенжайындағы әскери-тарихи музейге кіріп, әскери техника көргім келеді. | `citypass:98` | [source1](https://visitastana.kz/ru/about-city/what-to-see/voenno-istoricheskiy-muzey-vooruzhennykh-sil-respubliki-kazakhstan/) |
| sh15 | en / cafe_work | Which CoffeeBoom is on Zhenis Avenue 28 and explicitly offers free Wi-Fi? | `osm:node/10295608316` | [source1](https://coffeeboom.kz/ru/cf/coffeeshops/na-zhes/) |
| sh16 | en / walk | I want the greenhouse complex at Astana Botanical Garden on Orynbor, rather than just an outdoor park. | `osm:way/1196402246` | [source1](https://www.astanabotsad.kz/ru); [source2](https://www.astanabotsad.kz/ru/novosti/zha-zhmys-kestesi) |
| sh17 | en / walk | Find the Atyrau pedestrian bridge over the Yesil for a city walk. | `osm:way/1239177393` | [source1](https://visitastana.kz/ru/map/) |
| sh18 | en / tourist | I am looking for Kazakhstan history and ethnography at the National Museum on Tauelsizdik Avenue 54. | `osm:node/4894937300` | [source1](https://visitastana.kz/ru/about-city/what-to-see/natsionalnyy-muzey-respubliki-kazakhstan/); [source2](https://nmrk.kz/ru/) |
| sh19 | en / tourist | Where is ForteBank Kulanshi Art Space on Dostyk 8/1 for contemporary art exhibitions? | `overture:e2157a69-731f-461d-a2cf-ff1bb56406b3` | [source1](https://visitastana.kz/ru/map/) |
| sh20 | en / evening | At MEGA Silk Way, suggest French bakery food, pilaf, or gourmet street food for an evening meal. | `osm:node/12293708057`; `overture:38122d40-1d49-4e81-8427-0c49b65114cf`; `osm:node/13397061028` | [source1](https://restaurants.mega.kz/ru/?sm=2); [source2](https://abr.kz/restaurant/coco) |

## Case-specific scope

- `sh01`: Known source-reported free Wi-Fi at six separately identified branches. Other venues have unjudged Wi-Fi, so this is a known-positive set rather than an exhaustive city list.
- `sh02`: Named street plus children puppet performances identifies the puppet theatre at Respubliki3. Performance availability and times are outside scope.
- `sh03`: Aquarium sub-attraction only; child ticket is reported, but age band, safety, accompaniment and current ticket stock are unjudged.
- `sh04`: Two explicitly named monuments; identity and reported physical features only. No Bayterek hours or arch interior/roof access inferred.
- `sh05`: Palace identity and three reported tour languages. Conflicting public hours are excluded.
- `sh06`: Both explicitly named museums are relevant alternatives: jeweller collection and literary collection. Child programs and unresolved Seifullin hours are excluded.
- `sh07`: Within the reviewed set these cuisine alternatives identify Del Papa, Ocean Basket and Luckee Yu in this mall. Specific day availability, last orders and booking are excluded; full catalog alternatives are unjudged. Other reviewed venues with unknown detailed cuisine remain unjudged.
- `sh08`: Exact Samal11 CoffeeBoom branch with reported free Wi-Fi. No chain-wide projection, sockets or noise claim.
- `sh09`: TUMO enrolled creative-technology program is explicitly for ages12–18 at the real Alem.aiB1 building. Does not label the misplaced citypass81 record or promise walk-in museum admission to the program.
- `sh10`: The two named parks explicitly report children playgrounds. No onsite safety, staffing, surface condition or accessibility judgment.
- `sh11`: Named Triathlon park and reported running/cycling paths. Not a route-distance or safe-route judgment.
- `sh12`: Exact named park and address. No hours, entry price or wheelchair inference.
- `sh13`: The Presidential park around the Palace of Peace, rather than another same-name park. Only reported walking/cycling paths and location.
- `sh14`: Military-history museum at Respubliki2 with reported equipment pavilion and free entry. Conflicting opening hours and duplicate museum geometries are not separately judged.
- `sh15`: Exact Zhenis28 branch only; owner reports free Wi-Fi. No facts from other CoffeeBoom locations or unknown amenities.
- `sh16`: Parent canonical Botanical Garden is relevant for its explicitly reported greenhouse subfacility at Orynbor14D/14E. This is not an independent greenhouse canonical or outdoor park hours label.
- `sh17`: Named Atyrau bridge, included in the city walking program. Public hours, accessibility and route feasibility unjudged.
- `sh18`: National Museum identity, address and reported collection scope. No availability query; maintenance exceptions are not discarded or tested here.
- `sh19`: ForteBank gallery at Dostyk8/1, not the separate Kulanshi centre at the Palace. Current exhibition program and ticket availability unjudged.
- `sh20`: Reviewed mall alternatives are PAUL, Rumi and COCO. Cuisine and branch identity only; no date-specific opening, last-order or booking guarantee. Other catalog matches unjudged. Other reviewed venues with unknown detailed cuisine remain unjudged.

## Preserved baseline

`eval/datasets/astana_retrieval_v2.json` retains all35 old queries and labels unchanged. File SHA-256 before and after holdout creation: `aa146a675a7ba6f09959f5c12fc8e6723c0424efd8938d9039c5558074c98c8b`. No retriever, model, production data or previous label file was edited.
