# Автосбор POI Астаны

Данные роли `02_data_rag`. Основной UI-runtime — `ayat_backend/`, дополнительный — `backend/ + rag/`. Оба применяют единые quarantine и fact reviews. Master содержит 14 006 записей и 14 607 source ID; безопасный набор рекомендаций — 2 750 мест. Исходный master сохранён без изменения байтов. [Результаты устранения аудита](../docs/reports/audit_remediation_2026-10-19.md).

Рекомендуется Python 3.12. В текущей рабочей папке среда `.venv` уже подготовлена. Установка с нуля через доступный `uv`:

```bash
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r data/requirements.txt
.venv/bin/python data/run_pipeline.py
```

При использовании обычного Python сначала создайте среду командой `python3.12 -m venv .venv`, затем установите зависимости через `.venv/bin/python -m pip install -r data/requirements.txt`.

Первая сборка обращается к источникам. Если Overpass недоступен, используется публичный региональный файл Geofabrik Казахстана: он существенно больше городского набора, поэтому загрузка может занять десятки минут. Overture читается пространственным фильтром из GeoParquet. Для повторной сборки из уже сохранённых ответов, без сети:

```bash
.venv/bin/python data/run_pipeline.py --offline
```

`--refresh` обновляет ответы источников. `--sources osm overture wikimedia web geonames` позволяет явно выбрать источники. Числового лимита нет. Если границу города получить не удалось, экспорт останавливается; `--allow-bbox` явно разрешает приблизительное ограничение прямоугольником. Ошибки источников отражаются в manifest. Неуспешный или пустой сбор не должен заменять сохранённые пригодные данные.

Результаты:

- `processed/pois.json` — полный набор по схеме команды; широкие категории бизнеса, услуг и инфраструктуры сохраняются как `other`.
- `processed/pois_leisure.json` — подмножество категорий еды, прогулок, культуры, спорта и досуга; удобно для первого индекса рекомендаций.
- `processed/source_manifest.json` — даты, релизы, ошибки, ограничения, источники и качество сборки.
- `processed/stats.json` и `stats.md` — количество, категории, заполненность, доля исходных описаний и шаблонов.
- `processed/boundary.geojson` — использованная административная геометрия OSM relation 3087155.
- `processed/unlocated_facts.json` — записи каталогов без надёжно сопоставленных координат; они не попадают в POI с выдуманными координатами.
- `processed/quarantined_pois.json` — исходные записи с выявленными существенными противоречиями, временно исключённые из рекомендаций. Решения и ссылки на доказательства записаны в `quality_overrides.json`; при изменении ошибочных исходных значений правило перестаёт применяться.
- `raw/` — исходный кэш, региональный PBF и служебные отчёты; уже исключён из Git.
- `source_research.json` — ранее проверенный каталог из 39 источников и инструментов, включая ограничения доступа. Это исследование вариантов, а не утверждение, что все перечисленные сервисы импортированы в датасет.
- `quality_review.md`, `review/2026-10-19-data-audit/review_sample.json`, `review/2026-10-19-data-audit/verification.json` — проверенная выборка, обнаруженные ограничения и результаты проверок конкретного снимка данных.

У каждого POI есть `source_records`: первичные ID, ссылки, дата получения, релиз и лицензия, где она установлена. Поля `raw_tags`, `raw_taxonomy`, `source_refs` сохраняют дополнительные данные источников. Неизвестные часы, рейтинг, доступность и пригодность для детей остаются `null`. Популярность или уверенность Overture не превращаются в рейтинг посетителей. Часы из источников требуют разбора в `rag.hours`; неизвестный формат нельзя считать открытым заведением.

Короткие описания из структурированных полей отмечены `description_kind="structured_template"` и `description_source_detail`. Значение `description_source` указывает происхождение использованных фактов в рамках существующего enum; оно не означает, что автор источника написал шаблон. Исходные описания имеют `description_kind="source"`. LLM не использовалась. Шаблон не подтверждает тишину, Wi-Fi, розетки, цены или другие отсутствующие атрибуты. В статистике эти два вида текста считаются отдельно.

`amenity_facts` сохраняет явные интернет-атрибуты вместе с source ID/URL и исходными датами. `wlan` добавляет Wi-Fi в поиск, `yes` означает только интернет неизвестного типа. Отрицание, fee без access и неизвестные значения не создают положительных Wi-Fi-тегов; `customers` не означает бесплатный доступ для всех. При противоречии источников положительное утверждение подавляется. Тишина, розетки и скорость из этих атрибутов не выводятся.

При offline-пересборке короткие source-описания CityPass/MEGA извлекаются из известных HTML-кэшей только для существующих source ID, после точного восстановления Wiki-кэша. Спорные тексты хранятся в `held_descriptions` и не индексируются. Явные имена объединённых записей доступны поиску как aliases. Дата экспорта не заменяет исходную дату проверки факта.

Дедупликация консервативна: одинаковое имя или явный языковой вариант, расстояние менее 50 м и совместимая категория. Транслитерированные варианты одного адреса сопоставляются, разные явно указанные дома, помещения и этажи сохраняются. Проверенные сопоставления каталога и отдельно рассмотренные записи используют явные связи с исходным POI. Различающиеся часы/адреса/доступность/телефоны/сайты не пропадают: записываются в `field_conflicts`. Часть дублей с разными названиями или разнесёнными центрами больших зданий может остаться; каждый объект не следует считать вручную подтверждённым действующим заведением.

При выборочной проверке обнаружены ошибочная координата записи аэропорта, неверная ссылка университета на статью о министерстве и подозрительный список из 19 кухонь у одного кафе. Первый объект помещается в карантин, неверная статья не используется, а спорные кухни остаются только в исходных полях. Эти решения не исправляют источник за его автора и не заменяют проверку остальных мест.

Лицензии неоднородны: OSM/Geofabrik — ODbL, Wikidata — CC0, Wikipedia требует атрибуции и соблюдения лицензии статьи, GeoNames — CC BY 4.0, Overture имеет обязательства первичных источников. Для местных сайтов общая лицензия на повторное распространение не установлена; сохраняются фактические поля и ссылки, без копирования фотографий и длинных текстов. Итоговому смешанному набору не приписывается единая открытая лицензия. Каталоги, недоступные из-за ограничений или отсутствия ключа, не обходятся. Avtobus/Infobus и 2GIS не используются как бесплатная постоянная база POI. Факты, цены и подтверждения филиалов, собранные 19.10 со страниц 2ГИС, удалены 20.10 из рабочего среза и `sources/` (лицензия 2ГИС запрещает извлечение и хранение); архивы проверки `review/2026-10-19-*` и `eval/runs/2026-10-19-*` удалены целиком, они остались только в истории git.

GeoNames дополняет ориентиры и названия физических объектов из полного дампа Казахстана; населённые пункты, административные единицы и общие гидрографические названия не добавляются как заведения. Дата модификации каждой записи сохраняется отдельно: свежая дата файла не делает старую запись актуальной. В частности, часть записей гостиниц имеет дату 2015 года и неизвестный текущий статус.

Проверка:

```bash
.venv/bin/python -m pytest data/tests -q
.venv/bin/python -m pytest --pois data/processed/pois.json -q
```

Сборка и проверки не выполняют коммитов и пушей.

### Versioned publication and offline review

`python -m data.run_pipeline --offline --raw-dir PATH --output-dir PATH`
now builds a complete immutable bundle under `OUTPUT/.snapshots/VERSION`, checks
source-ID preservation, 90% count/category retention and required source health,
and atomically replaces `OUTPUT/current` only after all checks. Rejections retain
a `*.rejected.json` explanation and staged evidence. A partial bootstrap is labelled
partial; a partial required source cannot replace an existing usable snapshot.
Existing fixed exports remain available for explicit legacy consumers. On a new
output directory, compatibility file symlinks follow `current`; runtime readers
must still bind a version to avoid separate reads straddling a promotion.

Python APIs:

- `data.snapshot.publish_snapshot(processed_dir, artifacts, required_sources=(), approved_removed_ids=(), approved_removed_sidecars=None, fault=None)`
  returns `SnapshotHandle(path, version, manifest)`. `artifacts` maps flat filenames
  to JSON values, UTF-8 strings or bytes. POIs, leisure, source manifest and stats
  are mandatory. Source removal requires an explicit reviewed ID list; deliberate
  large category/count changes require a separately reviewed new baseline.
- `data.snapshot.resolve_snapshot(processed_dir, legacy=False)` resolves once and
  verifies all file hashes. No current pointer means legacy fixed exports;
  a corrupt active bundle fails rather than falling back silently.
- `rag.retriever.catalog()` binds the process's search, map/ID and origin catalog
  to one version. The full `pois` catalog retains origin-only records; `eligible`
  is a separate index set. Restart the process to adopt a promoted version.
- `ayat_backend.app.store.load_store()` freezes POIs, reviews, gazetteer, river
  and events from the selected version; `manifest.snapshot_path` identifies the
  same graph/dense sidecars for runtime startup. `DATA_SNAPSHOT_MODE=legacy`
  explicitly selects fixed files. Never mutate a published version in place.

Both runtimes use `data.eligibility` for normalized review IDs, origin-only /
suspicious classification policy and conflict masking. The canonical files and
all source IDs remain unchanged. Unlicensed source narrative is withheld from
derived publication until its specific reuse terms and attribution are reviewed.
Hours evidence contains source ID/URL, acquisition, source revision and check
dates separately; normalization dates do not establish checked freshness.

Generate review queues without network calls:

```sh
python -m data.review --as-of 2026-10-19 --output-dir data/review/2026-10-19
```

An optional `--raw-dir` reads original cached candidates to recover legacy field
provenance. The command emits reproducible `quality_review.json` and
`field_evidence.json`: five scenario curator samples, true/false/unknown/conflicting
field states, freshness work, license holds, classification reviews, explicit
keep/merge/unresolved duplicate decisions and graph coverage/component diagnostics.
`confirmed` means an attributed source assertion; it does not imply a recent
human check. `data/duplicate_decisions.json` records evidence-backed decisions.
These diagnostics do not prove an entrance, accessible crossing, bridge or venue
is usable today. Pending source and field checks remain pending.

### Curator accepted-fact overlay (no canonical rewrite)

`fact_reviews.json` beside `pois.json` is an optional, version-bound overlay. Both
runtimes call `data.eligibility.apply_fact_reviews(rows, payload,
canonical_sha256=SHA256_OF_ORIGINAL_POIS_BYTES)`. The publisher validates this
schema/hash before pointer replacement. A stale overlay fails closed. Publish a
new bundle containing the unchanged POI bytes, all existing sidecars, and the
review overlay; restart consumers. Never edit a published bundle in place.

```json
{
  "schema_version": 1,
  "canonical_sha256": "exact SHA256 of unchanged pois.json bytes",
  "reviews": [{
    "canonical_id": "osm:way/230401645",
    "field": "opening_hours",
    "value": "source-backed literal schedule",
    "status": "accepted",
    "source": "official_venue",
    "source_id": "official:stable-page-identifier",
    "source_url": "https://venue.example/hours",
    "checked_at": "2026-10-19",
    "acquired_at": "2026-10-19T12:00:00+05:00",
    "source_updated_at": null,
    "reviewed_by": "curator identity",
    "evidence_excerpt": "short exact supporting source excerpt"
  }]
}
```

The example is a schema template, **not an accepted fact**. `status` can be
`accepted`, `pending`, or `rejected`; only accepted records change the derived
view. Accepted facts require source/source ID, HTTP(S) URL, ISO check date,
reviewer and supporting excerpt. One accepted decision per canonical ID/field is
allowed. All identifiers must exist. Supported fields: `opening_hours`,
`wheelchair` (`yes`/`limited`/`no`), `kid_friendly` (boolean), `category`, `name`,
`aliases`, `name_en`, `name_kk`,
`internet_access`, `power_supply`, `socket`, `charging_station`, `indoor`,
`entrance`, `kids_area`, `lit`. False facts are literal `false` or `no`, never
inferred from missing evidence. Pending unknowns remain unknown.

Existing disputes remain masked unless the accepted decision also includes
`"resolves_conflicts": true`, a `resolution_reason`, and `resolved_source_ids`
covering **every** disputed source ID for that field. Original values/disputes
remain under `canonical_*`; source_records and IDs are preserved. Review metadata
and accepted field evidence remain attached. The overlay does not authorize
publishing unlicensed narrative or establish route/entrance accessibility.


Publication must preserve any prior `quarantine.json`, `quality_overrides.json`,
`field_evidence.json` and `fact_reviews.json`; omitting one rejects the new version
and leaves the current pointer unchanged. To deliberately retire a sidecar, pass
`approved_removed_sidecars={"filename.json": {"reason": "review rationale",
"reviewed_by": "curator", "reviewed_on": "YYYY-MM-DD",
"evidence_urls": ["https://supporting.example/review"]}}`. The approval is
recorded verbatim in the bundle manifest. Do not drop a hash-bound overlay during
refresh without a reviewed retirement or an explicitly rebound replacement.

Accepted `category` values must belong to `data.collect.normalize.CATEGORIES`.
Accepted `name`, `name_en` and `name_kk` are literal nonempty names of at most 300
characters, without markup/control characters or surrounding whitespace.
`aliases` is a list of 1–50 such names, unique ignoring case. Their original
values remain under `canonical_category`, `canonical_name`, `canonical_aliases`;
source records/IDs and master bytes are retained. These identity changes require
the same accepted source, URL, check date, reviewer and excerpt as every fact.

A Wi-Fi conflict can originate from `amenity_facts` plus
`conflicting_internet_access`, even without a `field_conflicts` entry. Explicit
resolution must list every prior internet-access source ID as well as any field
conflict IDs. Only a valid accepted resolution clears that one effective conflict
flag; original quality flags and amenity assertions remain auditable under
`canonical_quality_flags` and `canonical_amenity_facts`. Unrelated flags survive.

### Source checks and canonical dense index (2026-10-19)

`review/2026-10-19/scenario-verification.json` records30 source-reported places
(six each for walk, cafe/work, child, tourist, evening), source URLs and limits.
`processed/fact_reviews.json` contains62 accepted runtime fields and4 unresolved
schedule reviews (`status: disputed` with attributed `reports`, date/reviewer/reason).
Disputed fields are withheld by both runtimes. Six exact CoffeeBoom branches have
reported WLAN; sockets and quietness remain unknown. Published descriptions/images
were not copied from these rights-reserved sources. Source checks are not onsite
verification. The remaining catalog has not been manually verified.

The accepted baseline is published through `processed/current` as an immutable,
hash-checked bundle. `source_manifest.json` retains its original collection status;
this is not a claim that all sources were freshly recollected. A rejected offline
partial rebuild was not promoted. Runtimes bind POIs, reviews, events and graph to
one version on startup; restart to adopt a newly published bundle.

Primary e5-small index:2750x384, local ONNX embeddings, no paid embedding calls.
`canonical_index_manifest.json` binds ordered IDs, document hash, model/dimension,
policy hashes and vector artifact hash. Stale/corrupt indexes fall back to BM25.
To stage a new index for an active bundle:

```bash
python -m ayat_backend.pipeline.canonical_embed --model e5-small --output-dir /tmp/canonical-index-stage
```

Do not edit an active bundle. Publish its new reviewed artifacts plus staged
`manifest.json` renamed to `canonical_index_manifest.json` and its vector artifact
through `data.snapshot.publish_snapshot`; normal refreshes without a rebuilt
matching index use BM25. Historical fixed files remain available in explicit
`DATA_SNAPSHOT_MODE=legacy` mode. A missing sidecar cannot silently erase a prior
quarantine/fact-review policy.

## Removed snapshot versions (2026-10-20)

Only the version `current` points to is served or compared on publish (`data/snapshot.py`). The seven earlier
bundles in `processed/.snapshots/` (~575 MB) were removed from the working tree; reports in `docs/reports/` and
`eval/runs/` that cite them stay reproducible from git history:

`10dd87fc9f254f5a87374b88b0cfd349`, `4e9b6ecc5b4c455f9c0443714afb91b2`, `95972c2d4cf34fdf975b1af9b4b4efda`,
`afd497bafc4f4a689e3fb416661c3f7e`, `b479f2445492454782a09e8d95495ae7`, `c0d3e2f710f64d399c01c97b853ca05d`,
`d0cd7698c2c64d5fac64ffdd12351faa` — restore one with
`git checkout 062b9b8 -- data/processed/.snapshots/<version>`.

The audit sample and its verification moved to `review/2026-10-19-data-audit/` (they describe that snapshot;
nothing reads them at run time).
