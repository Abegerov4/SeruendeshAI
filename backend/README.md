# Backend: Seruendesh AI

FastAPI-сервис, который по запросу пользователя («я возле Mega Silk Way, хочу погулять час») возвращает 1–3 места рядом. Для каждого места есть «почему», время на посещение, «что делать там», статус часов работы и метка источника. Контракт API описан в [team/README.md §3.3](../team/README.md).

## Запуск

```bash
# из корня репозитория
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example .env        # вписать OPENAI_API_KEY
uvicorn backend.app.main:app --reload --port 8000
```

- Swagger: http://localhost:8000/docs
- Проверка: `curl localhost:8000/api/health`
- Тесты (без LLM, на фикстуре): `pytest backend/tests -q`

Пока пакета `rag/` нет в репозитории (ветка `feature/data-rag`), бэкенд сам переключается на mock-поиск по [фикстуре](tests/fixtures/pois_sample.json). Принудительно включить mock можно через `MOCK_RAG=1`.

## Пример

```bash
curl -s localhost:8000/api/recommend -H 'Content-Type: application/json' -d '{
  "query": "Еду с ребёнком, где рядом площадка или интерактивный музей?",
  "location": {"lat": 51.090, "lon": 71.411}
}'
```

## Пайплайн `/api/recommend`

| # | Шаг | Где | Кто решает |
|---|---|---|---|
| 1 | Маскирование PII (телефон, email, ИИН, карта), детектор prompt injection | `guards.py` | код |
| 2 | Разбор запроса → категории, время, режим, ориентир, ограничения | `intent.py` | правила + **fast model** |
| 3 | Локация: GPS (округлён до ~100 м, только Астана) → ориентир → просим указать | `pipeline.py` | код |
| 4 | Радиус = треть бюджета времени × скорость (пешком 80 м/мин, авто 400, транспорт 250) | `routing.py` | код |
| 5 | Поиск `rag.search` по категориям (если мало, добираем без них), при пустой выдаче радиус ×2 | `rag_adapter.py` | RAG |
| 6 | Фильтры: закрытые убираем, дети / доступность, бонус открытым | `pipeline.py` | код |
| 7 | Выбор 1–3 мест + «почему / что делать / сколько времени»; кандидаты обёрнуты в `<untrusted_data>` | `generate.py` | **decision model** |
| 8 | Проверка: `poi_id` только из кандидатов; расстояние, время в пути, часы, рейтинг и ссылку подставляет код; мини-маршрут | `pipeline.py`, `routing.py` | код |

**Модели** настраиваются в `.env`:
- `LLM_FAST_MODEL=gpt-5.4-mini` разбирает запрос, `temperature=0`, ответ ~0.7 с.
- `LLM_DECISION_MODEL=gpt-6.1-sol` выбирает места и объясняет выбор. Это свежая reasoning-модель, работает с `reasoning_effort=low`.

Цепочка отказоустойчивости: decision → fast → шаблонный ответ. Сервис отвечает даже без ключа и без сети.

## Фото-режим `POST /api/recommend/photo`

Пользователь присылает фото того, что видит, и система по нему определяет место:
1. Pillow пережимает фото до ≤ 1024 px и удаляет EXIF, включая GPS.
2. Fast model с vision выбирает место **только из закрытого списка** известных ориентиров и POI, иначе возвращает `null`.
3. При уверенности `high` или `medium` место становится локацией для обычного пайплайна, при `low` система просит написать ориентир.
4. Текст на фото считается данными: инъекция «IGNORE ALL INSTRUCTIONS» на картинке проверена и не срабатывает.
5. Фото не попадает в Langfuse, вместо него в трейс пишется `[image omitted]`.

```bash
curl -s localhost:8000/api/recommend/photo -F image=@khan_shatyr.jpg -F query="куда дальше на часик?"
```

## MCP-сервер

Те же возможности доступны как MCP-tools для Claude Desktop, Claude Code и Cursor: `recommend_places`, `search_pois`, `check_open_status`, `plan_route`, `get_poi`. К серверу прилагается Skill с инструкцией для ассистента. Подробности в [mcp_server/README.md](mcp_server/README.md).

## Наблюдаемость, стоимость, кэш
- **Langfuse** (если в `.env` есть `LANGFUSE_*`): трейс `recommend` → `parse-intent` (generation) → `poi-search` (retriever) → `decide-recommendations` (generation). В трейсах видны токены, стоимость и latency. Координат там нет.
- **Стоимость** около **$0.005 за запрос** (sol ≈ $0.0044, mini ≈ $0.0007). Каждый запрос пишет в лог токены и `cost_usd`.
- **Кэш:** TTL 15 мин, ключ — sha256 от замаскированного запроса, округлённой локации и часа. Повторный запрос отвечает примерно за 0 с вместо 5–13 с.
- **A/B выбора decision model** и эволюция промпта v1 → v2 описаны в [experiments/README.md](experiments/README.md).

## Приватность и честность
- Координаты округляются до 3 знаков; в логах есть только `request_id`, число кандидатов и latency, без координат и текста запроса.
- Ничего не хранится между запросами.
- Если часов работы нет, ставим `open_status: "unknown"`, а не «открыто».
- `source: "generated"` ставится, когда совет не опирается на данные POI.
- Ссылки и markdown-картинки из текста LLM вырезаются.
