# HTTP API (контракт для фронтенда)

API реализует **командный контракт** из `team/README.md` §3.3 (ветка `main`): поля `recommendations`, `poi_id`, `open_status`/`open_confidence`, `source: poi_data | generated`, `route.order`, плоский `used_context`, `GET /api/pois`, `GET /api/health`. Поверх контракта есть **дополнительные поля**: подробный статус часов, пешие метры по графу улиц, «выйти до», бейджи, события, полилинии маршрута, погода. Фронт может их использовать, а может игнорировать.

- Базовый URL локально: `http://localhost:8000`, Swagger: `/docs`.
- Машиночитаемая схема: [`docs/api/openapi.json`](api/openapi.json).
- Реальные ответы для моков: [`docs/api/examples/`](api/examples/).

```bash
npx openapi-typescript ../docs/api/openapi.json -o src/api/schema.d.ts   # TS-типы
```

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/recommend` | 1–3 рекомендации + опционально мини-маршрут |
| POST | `/api/recommend/photo` | то же, но старт определяется по фото известного места (multipart) |
| GET | `/api/pois?lat=&lon=&radius_m=` | POI вокруг точки для карты (кратко) |
| GET | `/api/health` | `{"status":"ok","pois":2271,"llm":"ok", …}` |
| GET | `/api/meta` | ориентиры для «Я возле…», категории, версия данных, `features` |
| POST | `/api/feedback` | «место закрыто / часы неверны» (хранятся только счётчики) |
| GET | `/api/auth/me` | текущий пользователь; гостю `200 {"user": null}` |
| POST | `/connector/mcp` | MCP-коннектор (Streamable HTTP), см. [MCP.md](MCP.md) |

CORS открыт для `localhost:5173`, `127.0.0.1:5173` и доменов `*.vercel.app`, `*.netlify.app`, `*.pages.dev`.

## POST /api/recommend

### Запрос (контракт §3.3 + необязательные расширения)

```jsonc
{
  "query": "Я возле Mega Silk Way, хочу прогуляться 30–60 минут",
  "location": {"lat": 51.089, "lon": 71.416},   // округлить до 3 знаков на клиенте; null → ищем ориентир в тексте
  "time_budget_min": 60,
  "mode": "walk",                                // walk | car | transit
  "profile": {"with_kids": false, "tourist": false, "accessibility": false, "group_size": 1},
  "lang": "ru",                                  // ru | kk | en; если запрос явно на другом языке — ответ на нём
  "now": "2026-10-18T19:30:00+05:00",            // необязательно (демо/тесты)
  // расширения (необязательные):
  "landmark": "mega_silk_way",                   // ключ из /api/meta вместо GPS
  "want_route": null,                            // null = авто, true/false = принудительно
  "weather": null                                // демо-подмена погоды: {"temperature_c":-20,"feels_like_c":-28,"wind_ms":8}
}
```

- В `profile` значение `true` включает режим. `false` значит «не указано», и тогда режим может определиться из текста («с ребёнком», «коляска»).
- Точка старта по приоритету:
  1. ориентир в тексте («возле Байтерека»);
  2. `location`;
  3. `landmark`.
- Если нет ни одного из трёх, вернётся `200` с пустым `recommendations` и `notes: ["Не удалось определить локацию…"]` (по контракту).

### Ответ

```jsonc
{
  "request_id": "3f2a9c1b7e10",
  "lang": "ru",
  "summary": "Подобрал 2 места рядом: …",
  "used_context": {
    // контракт
    "location_source": "landmark",            // gps_rounded | landmark | none
    "location_label": "Mega Silk Way",
    "radius_m": 1760, "time_budget_min": 60, "mode": "walk",
    "filters": ["турист", "Парк"], "now": "2026-10-18T15:00:00+05:00",
    // расширения для блока «Что я учёл»
    "location": {"source": "text_landmark", "label": "Mega Silk Way", "lat": 51.089, "lon": 71.407, "precision_m": 50},
    "local_time": "15:00", "weekday": "воскресенье", "is_holiday": null, "is_dark": false,
    "weather": {"description": "9°C (ощущается 6°C), ветер 5 м/с", "max_outdoor_min": 60, "source": "Open-Meteo.com (CC BY 4.0)", …},
    "speed_kmh": 4.1, "party": "solo",
    "parsed_from_query": {"categories": [], "preferences": ["park", "landmark"], "needs": [], "parser": "llm+rules (gpt-6-luna)", …},
    "relaxations": [], "funnel": {"total": 2271, "within_reach": 132, "after_filters": 48, "shown": 2},
    "data_sources": ["OpenStreetMap (ODbL)", …], "data_built_at": "…", "privacy": "Локация округлена до ~100 м…",
    // вспомогательный судья OpenAI Decisions API (null, если не запускался: нет ключа, таймаут)
    "ai_check": {"engine": "OpenAI Decisions API · gpt-6-luna",
                 "intent": {"with_kids": 0.96, "indoor": 0.98, "night": 0.09, "quiet": 0.08, "unusual": 0.09, "about_city": 0.9},
                 "intent_applied": ["indoor"],            // что из намерения изменило поиск
                 "checked": 10, "latency_ms": 217,        // сколько карточек проверено и за сколько
                 "dropped": [{"poi_id": "osm:w37884583", "name": "Парк влюбленных", "match": 0.07}]}
  },
  "recommendations": [{
    // контракт
    "poi_id": "osm:w123456", "name": "Аллея мира и согласия", "category": "park",   // enum из 18 значений (§3.1)
    "lat": 51.09, "lon": 71.41,
    "distance_m": 1290,                // по прямой (haversine), как в контракте
    "travel_min": 18,                  // по реальному графу улиц (пешком) / оценка (авто, транспорт)
    "why": "…", "visit_min": [20, 45], "what_to_do": "…",
    "open_status": "open",             // open | closed | unknown
    "open_confidence": "low",          // high (часы из OSM) | low (выведено: открытая территория / праздник) | none (нет данных)
    "source": "poi_data",              // poi_data | generated (идея ИИ)
    "source_url": "https://www.openstreetmap.org/way/123456",
    "rating": null,                    // открытых рейтингов по Астане нет
    // расширения
    "rank": 1, "category_detail": "park", "category_label": "Парк", "icon": "trees",
    "match": 0.84,                     // Decisions API: вероятность, что место подходит под запрос; null без проверки
    "walk_distance_m": 1640,           // реальная длина пешего пути
    "travel_mode": "walk", "visit_suggested_min": 25,
    "leave_by": null,                  // «выйти до HH:MM» при дедлайне (рейс/поезд)
    "opening": {"status": "always", "confidence": "medium", "label": "Открытая территория — часы не ограничены", "raw": null, "next_change": null},
    "source_label": "Данные POI",      // или «Идея ИИ»
    "data_sources": ["osm", "wikidata"], "popularity": 0.12,
    "features": ["освещение вечером"], "accessibility": "unknown",
    "badges": ["outdoor", "free"],     // indoor, outdoor, kids, popular, hidden_gem, event, night, free, ai_idea
    "event": null,                     // {"title","starts_at","url","source","price_from"} для Ticketon/Sxodim
    "address": "…", "description": "…", "description_source": "osm|wikipedia|template|generated"
  }],
  "route": {                            // null, если маршрут не нужен или не помещается
    "order": ["osm:…", "osm:…"], "total_min": 58,             // контракт
    "legs": [{"from_id": "start", "to_id": "osm:…", "distance_m": 650, "travel_min": 9,
              "polyline": [[51.1, 71.4], …], "geometry": "network"}],   // [lat, lon] сразу для Leaflet
    "fits_budget": true, "returns_to_start": true, "summary": "Мини-маршрут: A → B. Всего ≈ 58 мин (…)"
  },
  "considered": [{"name": "Starbucks", "reason": "закрыто к моменту прихода"}],
  "notes": ["…"],
  "disclaimer": "Ответ сформирован ИИ на основе открытых данных…",
  "ai_generated": true,
  "llm": {"mode": "llm", "model": "gpt-6-luna", "latency_ms": 3300,   // mode = template, если LLM недоступен
          "usage": {"input_tokens": 4203, "output_tokens": 261, "cost_usd": 0.0011}},  // cost_usd = null, если цены модели нет в config
  "off_topic": false   // true: запрос не о местах/прогулках ("напиши код") -> recommendations = [], объяснение в summary и notes
}
```

### Что показывать в карточке
- «650 м · 9 мин пешком»: метры из `walk_distance_m` (или `distance_m`), минуты из `travel_min`.
- «Почему:» `why`, «Что делать:» `what_to_do`, «≈ `visit_min[0]`–`visit_min[1]` мин».
- Бейдж часов: цвет по `open_status`, текст из `opening.label`. Для `open_confidence: "none"` писать «часы неизвестны».
- Метка источника по `source`: «📍 Данные POI» или «✨ Идея ИИ».
- Ссылка «Источник» по `source_url`. Ссылки берутся только из данных, LLM их не генерирует.
- По желанию: `features`, `badges`, `leave_by`, `event`, `description`.
- Под выдачей блок «Что я учёл» из `used_context`, затем `notes` и `considered`, мелким шрифтом `disclaimer`.

### Ошибки
- `422`: невалидный ввод.
- `429`: больше 30 запросов в минуту.
- `500`: `{"error": {...}}`.

Если LLM недоступен, ответ всё равно `200`, с `llm.mode: "template"`.

## POST /api/recommend/photo
`multipart/form-data`: `image` (JPEG/PNG/WebP, до 8 МБ, обязательно), `query?`, `landmark?` (ключ ориентира, используется, если фото не узнано), `lang?` (`ru|kk|en`).
Фото декодируется с лимитом пикселей, EXIF (включая GPS) удаляется и не читается, картинка уменьшается до 1024 px и пересжимается в JPEG. LLM выбирает место только из закрытого списка: ориентиры из `/api/meta` и ~40 самых популярных POI. Параллельно OpenAI Decisions API выбирает место из того же списка с вероятностью. Если оба ответа совпали, уверенность «высокая». Если судья уверен, что на фото ничего из списка, догадке vision не верим. Фото не сохраняется.

Ответ: обычный ответ `/api/recommend` плюс поле `photo_guess`:

```jsonc
"photo_guess": {"recognized": true, "place_id": "nurzhol", "kind": "landmark",   // kind: landmark | poi | null
                "name": "Бульвар Нуржол", "confidence": "high",                  // low | medium | high
                "description": "Цветочная аллея и фонтаны на фоне высоток",
                "probability": 0.69}                                              // Decisions API; null, если не совпал с местом
```

Если место не узнано (или `confidence: low`) и `landmark` не передан, ответ `200` с `recommendations: []`, а в `summary`/`notes` просьба написать ориентир.
Ошибки (тело `{"error": "<код>"}`): `413 photo_too_large`, `415 unsupported_media_type|unsupported_format`, `422 image_required|invalid_image|invalid_form|invalid_lang`, `429`, `503 photo_unavailable` (LLM не настроен; см. `features.photo` в `/api/meta`).

## GET /api/pois
`?lat=51.128&lon=71.43&radius_m=1500&limit=300` возвращает `[{"id","name","category","category_detail","lat","lon"}]`, отсортировано по расстоянию.

## GET /api/meta
Ориентиры (`key`, `name`, `lat`, `lon`) для выпадающего списка «Я возле…» плюс 33 детальные категории с подписями RU/KK/EN.
Флаги возможностей: `"features": {"password_reset_email": false, "photo": true, "mcp": true}` (`password_reset_email`: настроен SMTP; `photo`: настроен LLM).

## GET /api/auth/me
Залогиненному пользователю: `200 {"id","email","name","lang","created_at"}`, как и раньше. Гостю (нет cookie или сессия истекла): `200 {"user": null}` вместо `401`.

## POST /api/feedback
`{"poi_id": "osm:w123", "kind": "closed|wrong_hours|not_as_described|great|other"}` → `{"ok": true, "message": "…"}`.
