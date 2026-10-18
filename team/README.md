# Astana Walk AI — план команды

Кейс: **НИЦ Smart City — «ИИ-помощник по прогулкам в городе Астана»** (хакатон Build with AI).
Делаем RAG-систему: пользователь пишет, где он и чего хочет, а система выдаёт **1–3 конкретных места** рядом с ним. У каждого места есть «почему», время на посещение, «что делать там», метка источника и уверенность в режиме работы.

---

## 1. Роли

| # | Роль | Файл с задачами | Ветка | Папка (зона владения) |
|---|---|---|---|---|
| 1 | **Backend / LLM** (API, оркестрация, генерация, guardrails) | [01_backend.md](01_backend.md) | `feature/backend` | `backend/` |
| 2 | **Data & RAG Engineer** (автосбор POI, индекс, поиск) | [02_data_rag.md](02_data_rag.md) | `feature/data-rag` | `data/`, `rag/` |
| 3 | **Frontend** (чат + карта, UX, приватность локации) | [03_frontend.md](03_frontend.md) | `feature/frontend` | `frontend/` |
| 4 | **QA / Eval / Docs** (тест-сценарии, метрики, этика, презентация, видео) | [04_qa_docs.md](04_qa_docs.md) | `feature/qa-docs` | `tests/`, `eval/`, `docs/`, корневой `README.md` |

**Правило №1: каждый меняет только файлы в своей папке.** Тогда при слиянии веток не будет конфликтов. Если нужно что-то поменять в чужой папке, напиши владельцу.

---

## 2. Как это работает (высокий уровень)

```text
[Frontend]  чат + карта, гео округлено до ~100 м
     │  POST /api/recommend
     ▼
[Backend]  1) валидация + маскирование PII + проверка на injection
           2) разбор запроса LLM → JSON {категории, время, режим, ограничения, ориентир}
           3) локация: GPS (округлённый) → ориентир («возле Mega Silk Way») → спросить
           4) радиус = f(время, пешком/авто)
           5) ──► rag.search(...)  ◄── [Data & RAG]  POI-база (OSM + др.) → ChromaDB
           6) фильтры в коде: расстояние, режим работы, дети, доступность
           7) LLM выбирает 1–3 места ТОЛЬКО из кандидатов → JSON с «почему / время / что делать»
           8) проверка ответа: poi_id существует, расстояния считает код, метки источника
     ▼
[Frontend]  карточки + точки на карте + «какие данные использованы»

[QA]  golden-сценарии → прогон eval → метрики → документ сценариев + презентация + видео
```

**Стек (общий):**
- Python 3.11+, FastAPI, pydantic
- LLM: OpenAI API (gpt-4o-mini или аналог) или Gemini. Провайдер выбирается через `.env`
- Эмбеддинги: `text-embedding-3-small` (мультиязычные) либо `bge-m3` локально
- Векторная БД: ChromaDB (локально, persistent)
- Поиск: гео-префильтр + dense + BM25 → RRF (BM25 нужен для точных названий: «Хан Шатыр», «Байтерек»)
- Данные: OpenStreetMap (Overpass API) + Wikipedia/Wikidata + сайты мест, сбор автоматизирован скриптом
- Frontend: React + Vite + Leaflet (OSM-тайлы)
- Eval: свой скрипт + LLM-as-a-Judge (метрики в духе RAGAS: faithfulness, relevancy)
- Трассировка (опционально): Langfuse

Подробнее см. конспекты в корне проекта: [rag.md](../rag.md), [data_extraction.md](../data_extraction.md), [ai_security.md](../ai_security.md), [prompting_memory_tools.md](../prompting_memory_tools.md), [ai_engineering.md](../ai_engineering.md).

---

## 3. КОНТРАКТЫ (договоримся один раз и не меняем без обсуждения)

Благодаря контрактам все четверо работают параллельно с первой минуты: фронт работает на моках, бэкенд на фикстуре, RAG отдаёт функцию по сигнатуре.

### 3.1 Схема POI (файл `data/processed/pois.json`, это массив таких объектов)

```json
{
  "id": "osm:node/123456",
  "name": "Байтерек",
  "name_en": "Bayterek Tower",
  "name_kk": "Бәйтерек",
  "lat": 51.12825,
  "lon": 71.43049,
  "category": "viewpoint",
  "tags": ["смотровая", "символ города", "фото"],
  "description": "Монумент высотой 97 м со смотровой площадкой…",
  "description_source": "wikipedia",
  "address": "просп. Нуржол, 14",
  "opening_hours": "Mo-Su 10:00-21:00",
  "phone": null,
  "website": "https://…",
  "rating": 4.7,
  "rating_count": 12000,
  "wheelchair": "yes",
  "kid_friendly": true,
  "source": "osm",
  "source_url": "https://www.openstreetmap.org/node/123456",
  "updated_at": "2026-10-18"
}
```

- `category` берётся из enum: `cafe, restaurant, bar, nightlife, museum, gallery, theatre, cinema, park, viewpoint, monument, attraction, playground, mall, library, coworking, sport, other`
- `description_source` берётся из `osm | wikipedia | website | llm_generated`. Если описание сгенерировано LLM, это **обязательно** помечается так.
- Поля, о которых ничего не известно, ставим в `null`, а не выдумываем. `wheelchair` принимает `yes | limited | no | null`.

### 3.2 Интерфейс RAG (Python, его отдаёт Data & RAG, вызывает Backend)

```python
# rag/retriever.py
def search(query: str, lat: float | None, lon: float | None,
           radius_m: int = 2000, categories: list[str] | None = None,
           top_k: int = 15) -> list[dict]:
    """Возвращает POI (схема 3.1) + поля distance_m (int|None) и score (float), отсортировано по score."""

# rag/geo.py
def resolve_landmark(text: str) -> dict | None:
    """'Mega Silk Way' -> {"lat": .., "lon": .., "label": "ТРЦ Mega Silk Way"} или None."""

def haversine_m(lat1, lon1, lat2, lon2) -> int: ...

# rag/hours.py
def open_status(opening_hours: str | None, dt: datetime) -> tuple[str, str]:
    """-> (status, confidence): status ∈ open|closed|unknown, confidence ∈ high|low|none."""
```

### 3.3 HTTP API (его отдаёт Backend, вызывают Frontend и QA)

**`POST /api/recommend`**

Request:
```json
{
  "query": "Я возле Mega Silk Way, хочу прогуляться 30–60 минут",
  "location": { "lat": 51.089, "lon": 71.416 },
  "time_budget_min": 60,
  "mode": "walk",
  "profile": { "with_kids": false, "tourist": false, "accessibility": false, "group_size": 1 },
  "lang": "ru",
  "now": "2026-10-18T19:30:00+05:00"
}
```
- `location` может быть `null`, тогда бэкенд ищет ориентир в тексте запроса.
- Фронт округляет координаты до **3 знаков** (~100 м) ещё до отправки.
- `mode` принимает `walk | car | transit`, `lang` принимает `ru | kk | en`. Все поля, кроме `query`, необязательные.

Response:
```json
{
  "request_id": "b1f…",
  "used_context": {
    "location_source": "gps_rounded",
    "location_label": "~ район Mega Silk Way",
    "radius_m": 1500,
    "time_budget_min": 60,
    "mode": "walk",
    "filters": ["прогулка", "парк"],
    "now": "2026-10-18T19:30:00+05:00"
  },
  "recommendations": [
    {
      "poi_id": "osm:way/987",
      "name": "Центральный парк",
      "category": "park",
      "lat": 51.152, "lon": 71.433,
      "distance_m": 650,
      "travel_min": 8,
      "why": "Ближайшая большая зелёная зона, подходит под 30–60 мин прогулки",
      "visit_min": [30, 45],
      "what_to_do": "Пройти по набережной Есиля до колеса обозрения, затем кофе у входа",
      "open_status": "unknown",
      "open_confidence": "none",
      "source": "poi_data",
      "source_url": "https://www.openstreetmap.org/way/987",
      "rating": 4.6
    }
  ],
  "route": { "order": ["osm:way/987", "osm:node/555"], "total_min": 70 },
  "notes": ["Режим работы «Кафе X» неизвестен, лучше уточнить перед визитом"],
  "disclaimer": "Рекомендации основаны на открытых данных POI. Точные координаты не сохраняются."
}
```
- `source` принимает `poi_data | generated` (идеи «что делать», которых нет в данных, помечаются как `generated`)
- `route` равен `null`, если мини-маршрут не строился
- Ошибки: `422` при невалидном вводе, `200` с пустым `recommendations` и `notes: ["Не удалось определить локацию…"]`, если локации нет

**`POST /api/recommend/photo`** (multipart/form-data) — мультимодальный режим «сфоткай, что видишь».
Поля: `image` (файл JPEG/PNG/WEBP, ≤ 8 МБ, обязательно) и необязательные `query`, `time_budget_min`, `mode`, `lang`, `now`, `with_kids`, `tourist`, `accessibility`, `group_size`.
- Ответ в том же формате, что у `/api/recommend`.
- Если место узнано, `used_context.location_label` заканчивается на `(по фото)`, а первая строка `notes` начинается с «По фото … определили: …».
- Если не узнано, `recommendations: []` и `notes` с просьбой указать ориентир.
- Фото не сохраняется, EXIF (в том числе GPS) удаляется до отправки в модель.

**`GET /api/pois?lat=&lon=&radius_m=`** возвращает POI для карты (краткие поля: id, name, category, lat, lon).
**`GET /api/health`** возвращает `{"status":"ok","pois":1234,"llm":"ok"}`.

---

## 4. Git-процесс

### Один раз (делает Backend, то есть ты)
```bash
cd "Smart City"
git init -b main
# .gitignore: .env, __pycache__/, .venv/, node_modules/, data/raw/, rag/chroma/, .cache/
git add team/ *.md "FINAL Задачи_хакатона.docx.pdf" .gitignore
git commit -m "docs: team roles and contracts"
git remote add origin https://github.com/<org>/astana-walk-ai.git
git push -u origin main
```

### Каждый участник
```bash
git clone https://github.com/<org>/astana-walk-ai.git && cd astana-walk-ai
git checkout -b feature/<роль>       # backend | data-rag | frontend | qa-docs
# … работа только в своей папке …
git add <своя папка> && git commit -m "feat(<роль>): …"
git push -u origin feature/<роль>
```

### Слияние
- Сливаем через **Pull Request в `main`**, а не ветки друг в друга.
- **Порядок merge:** `data-rag` → `backend` → `frontend` → `qa-docs`. Именно так зависимости и идут.
- Мержим **промежуточно на каждом чекпоинте**, а не один раз в конце, чтобы интеграционные баги вылезали рано.
- Перед PR подтяни свежий main: `git fetch origin && git rebase origin/main`
- Секреты (`OPENAI_API_KEY` и т.п.) храним только в `.env`. В репо кладём только `.env.example`.

---

## 5. Чекпоинты (общие для всех)

| Чекпоинт | Что должно быть | Кто блокирует |
|---|---|---|
| **CP0. Старт** | Все прочитали контракты, создали ветки. Frontend на моках, Backend на фикстуре | — |
| **CP1. Данные** | `pois.json` ≥ 300 POI Астаны + `rag.search()` работает | Data & RAG |
| **CP2. End-to-end** | Фронт → API → RAG → LLM → карточки на экране (merge data-rag + backend + frontend) | Backend |
| **CP3. Качество** | Golden set прогнан, худшие кейсы исправлены, метрики в таблице | QA (+ все чинят) |
| **CP4. Сдача** | Документ сценариев, этика/privacy, презентация 5–7 мин, видео на YouTube, README | QA (+ все) |

---

## 6. Критерии жюри и кто за что отвечает

| Критерий (по важности) | Главный ответственный |
|---|---|
| 1. Релевантность и полезность | Data & RAG (поиск) + Backend (генерация) |
| 2. Контекстуальность (расстояние, время, режим работы) | Backend (фильтры, радиус) + Data (`open_status`, гео) |
| 3. Качество объяснений «почему» | Backend (промпт) |
| 4. UX / понятность демо | Frontend |
| 5. Креативность (мини-маршрут, мультиязычность, доступность, группы) | Backend + Frontend |
| 6. Этика и приватность | Frontend (округление гео) + Backend (без логов координат) + QA (документ) |
| 7. Завершённость (доки, сценарии, презентация) | QA / Docs |

**Фокус (совет организаторов):** 3 сильных сценария вместо всех сразу.
1. «Я возле Mega Silk Way, 30–60 минут погулять»: прогулка + мини-маршрут
2. «Еду с ребёнком, где рядом площадка или интерактивный музей»: фильтр по профилю
3. «Я турист, 2 часа до вылета»: время, режим работы, честная неуверенность
