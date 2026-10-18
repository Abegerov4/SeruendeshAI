# Роль 2 — Data & RAG Engineer

**Ветка:** `feature/data-rag`  **Папки:** `data/`, `rag/`  **Merge:** первый

Ты отвечаешь за знания системы. Нужно **автоматически** собрать датасет POI Астаны (организаторы прямо требуют, чтобы сбор был автоматизирован), почистить его, проиндексировать и отдать бэкенду функцию поиска. Плохие данные убивают весь RAG, поэтому от тебя зависит главный критерий жюри — релевантность.

Контракты (схема POI, сигнатуры `rag.*`) описаны в [README.md](README.md#3-контракты-договоримся-один-раз-и-не-меняем-без-обсуждения).

---

## Структура папок

```text
data/
  collect/
    osm_overpass.py      # Overpass API → сырые POI Астаны (bbox города)
    enrich_wiki.py       # описания из Wikipedia/Wikidata (по тегу wikidata/wikipedia в OSM)
    enrich_web.py        # (опц.) описание с сайта места через Jina Reader / BeautifulSoup
    enrich_llm.py        # короткое описание по тегам, если ничего нет → description_source="llm_generated"
    normalize.py         # приведение к схеме, категории, дедупликация, валидация
  run_pipeline.py        # ОДНА команда: собрать → обогатить → нормализовать → pois.json
  raw/                   # кэш сырых ответов (в .gitignore)
  processed/pois.json    # итоговый датасет (коммитим!)
  stats.md               # сколько POI по категориям, % с описанием/часами/рейтингом
rag/
  build_index.py         # pois.json → эмбеддинги → ChromaDB (rag/chroma/, в .gitignore)
  retriever.py           # search(...) — гео + dense + BM25 + RRF
  geo.py                 # haversine_m, resolve_landmark
  hours.py               # open_status (парсер OSM opening_hours)
  requirements.txt
```

---

## Задачи

### Этап 1 — автосбор данных (цель CP1: ≥ 300 POI, лучше 800+)
- [ ] **Overpass API** (бесплатно, легально, есть часы работы и теги). Bbox Астаны ≈ `51.05,71.25,51.25,71.60`. Теги:
  `amenity=cafe|restaurant|bar|pub|cinema|theatre|library|arts_centre|coworking_space`, `tourism=museum|gallery|attraction|viewpoint|artwork`, `leisure=park|playground|garden|sports_centre`, `historic=monument|memorial`, `shop=mall`, `club=*`/`amenity=nightclub`
- [ ] Берём `name`, `name:kk`, `name:en`, координаты (для way/relation центр), `opening_hours`, `phone`, `website`, `wheelchair`, `wikidata`, `wikipedia`, `addr:*`
- [ ] **Описания:** Wikipedia/Wikidata по ссылке из OSM → первые 1–2 предложения. Если источника нет, LLM генерирует 1 предложение **по тегам**, а `description_source="llm_generated"` (жюри смотрит, честно ли помечены источники)
- [ ] **Рейтинг/популярность:** в OSM их нет. Варианты: прокси популярности (есть статья в Wikipedia, число языковых версий, тег `tourism`); 2GIS/Google Places только если позволяют ToS/ключ (`[VERIFY]`). Нет данных, значит `null`
- [ ] **Нормализация:** маппинг тегов → `category` (enum из контракта), удаление дублей (одно имя и < 50 м), отбрасываем POI без имени, `kid_friendly` = playground / зоопарк / детские теги
- [ ] Кэш на диск (`data/raw/`), `try/except` + таймауты, уважать rate limit Overpass
- [ ] `python data/run_pipeline.py` пересобирает всё одной командой. Это и есть «автоматизация сбора» для презентации
- [ ] **Сразу** (в первый час) закоммить `pois.json` хотя бы на 50 POI, чтобы бэкенд перешёл с фикстуры на реальные данные

### Этап 2 — индекс и поиск
- [ ] **Текст для эмбеддинга** (чанк = одно POI, резать не нужно):
  `"{name} ({name_en}). Категория: {category}. Теги: {tags}. {description}. Адрес: {address}"`
- [ ] Эмбеддинги `text-embedding-3-small` (или `bge-m3`). Модель одна для документов и запросов. Проверь вручную 5–10 запросов на русском и казахском
- [ ] ChromaDB persistent, в metadata лежат `id, category, lat, lon, kid_friendly, wheelchair`
- [ ] `search()`:
  1. гео-префильтр: haversine ≤ `radius_m` (если координат нет, поиск по всему городу)
  2. фильтр `categories` (если передан)
  3. dense top-30 + **BM25** top-30 (нужно для точных названий вроде «Хан Шатыр», «Mega Silk Way»)
  4. объединение через **RRF** (k=60), не складываем сырые скоры
  5. лёгкий буст за близость и популярность → top_k, к каждому добавляем `distance_m` и `score`
- [ ] `resolve_landmark("Mega Silk Way")`: BM25/fuzzy по именам POI → координаты. Иначе берём Nominatim (с кэшем). Список ориентиров (ЭКСПО, Байтерек, Хан Шатыр, аэропорт, вокзалы) вшей словарём для надёжности
- [ ] `open_status(opening_hours, dt)`: разобрать частые форматы OSM (`Mo-Su 10:00-22:00`, `Mo-Fr …; Sa-Su …`, `24/7`, переход через полночь). Непонятный формат или `null` даёт `("unknown","none")`. **Никогда не угадывать.** Учитывай часовой пояс Астаны (UTC+5)

### Этап 3 — проверка качества (вместе с QA)
- [ ] `data/stats.md`: число POI по категориям, % с описанием / часами / wheelchair / рейтингом. Это слайд для презентации
- [ ] Recall@5 на golden-запросах от QA: попадает ли ожидаемое место в топ-5. Если плохо, чини в порядке retrieval → текст для эмбеддинга → данные
- [ ] Проверь глазами 20 случайных POI: адекватна ли категория и не мусор ли описание

---

## Подсказки из конспектов
- Overpass/скрапинг, кэш, robots.txt, Jina Reader: [data_extraction.md](../data_extraction.md) §2.1, §4.2–4.5
- Hybrid + RRF, код BM25: [rag.md](../rag.md) §2.4, §9.5
- Индексация Chroma, metadata-фильтр: [rag.md](../rag.md) §9.3–9.4
- «Для структурированных данных фильтруй кодом, а не векторами» (гео, часы): [rag.md](../rag.md) §2.1
- Описания из веба являются untrusted, инструкции из них не исполняем: [ai_security.md](../ai_security.md) §2.3

## Что ты отдаёшь
- `data/processed/pois.json` (по схеме) + `data/run_pipeline.py`
- `rag/` с функциями `search`, `resolve_landmark`, `haversine_m`, `open_status` **ровно по сигнатурам**
- Инструкцию: `pip install -r rag/requirements.txt && python data/run_pipeline.py && python rag/build_index.py`

## Definition of Done
- [ ] ≥ 300 POI, все с координатами и категорией; ≥ 60% с описанием; источник описания помечен
- [ ] `search("кофе тихо", 51.128, 71.430, 1500)` возвращает кафе в радиусе, отсортированные по релевантности
- [ ] Recall@5 ≥ 0.7 на golden-запросах QA
- [ ] Unit-тесты на `open_status` (5–10 случаев, включая полночь и `null`) и `haversine_m`
- [ ] PR `feature/data-rag` → `main` смержен **первым** (до CP2)
