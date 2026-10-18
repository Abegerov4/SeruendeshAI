# Роль 1 — Backend / LLM

**Ветка:** `feature/backend`  **Папка:** `backend/`  **Merge:** второй, после `data-rag`

Ты собираешь мозг системы. Ты принимаешь запрос, понимаешь, чего хочет пользователь, вызываешь поиск по POI, просишь LLM сформулировать 1–3 рекомендации и проверяешь, что ответ честный и не выдуманный.

Контракты (API, схема POI, интерфейс `rag.search`) описаны в [README.md](README.md#3-контракты-договоримся-один-раз-и-не-меняем-без-обсуждения). Их не меняй в одиночку.

---

## Структура папки

```text
backend/
  app/
    main.py            # FastAPI, роуты /api/recommend, /api/pois, /api/health, CORS
    schemas.py         # pydantic: RecommendRequest, RecommendResponse, Recommendation (строго по контракту)
    pipeline.py        # оркестрация шагов 1–8
    intent.py          # разбор запроса LLM → JSON (structured output) + fallback на правила
    generate.py        # LLM: выбор 1–3 мест + why / visit_min / what_to_do
    guards.py          # mask_pii, проверка на prompt injection, wrap_untrusted, валидация ответа
    routing.py         # радиус по времени/режиму, travel_min, мини-маршрут (nearest neighbour)
    llm.py             # обёртка над провайдером (OpenAI / Gemini) из .env
    prompts/           # system-промпты в отдельных .md/.txt (не хардкодить в коде)
    rag_adapter.py     # импорт rag.search; при MOCK_RAG=1 — поиск по фикстуре
  tests/fixtures/pois_sample.json   # 10–15 POI вручную по схеме — для работы до CP1
  requirements.txt
  .env.example         # OPENAI_API_KEY=, LLM_PROVIDER=openai, LLM_MODEL=, MOCK_RAG=1
```

---

## Задачи

### Этап 0 — каркас (до CP1, не ждёшь данных)
- [ ] FastAPI + pydantic-схемы **точно по контракту**, `/api/health`, CORS для фронта
- [ ] `/api/recommend` отдаёт ответ на фикстуре (`MOCK_RAG=1`), фронт сразу может подключаться
- [ ] `llm.py`: одна функция `chat(messages, json_schema=None, temperature=0)`, провайдер и модель берутся из `.env`
- [ ] Ключи только в `.env`, сетевые вызовы делаем с `timeout` и `try/except`

### Этап 1 — пайплайн `/api/recommend`
1. [ ] **Вход:** валидация, `mask_pii(query)` (regex: телефоны +7, email, ИИН; см. [ai_security.md](../ai_security.md) §6.2), простой детектор injection («ignore previous…», «system prompt»)
2. [ ] **Разбор запроса** (`intent.py`): LLM со structured output →
   `{categories[], time_budget_min, mode, constraints: {quiet, socket, kids, night, accessibility}, landmark, lang}`.
   Явные поля из запроса фронта перекрывают LLM. Если LLM упала, используем fallback на ключевые слова.
3. [ ] **Локация:** `location` от фронта → иначе `rag.resolve_landmark(landmark)` → иначе вернуть `notes` «укажите, где вы»
4. [ ] **Радиус:** пешком ~80 м/мин, авто ~400 м/мин, транспорт ~250 м/мин. Радиус = (время/3) × скорость, ограничиваем рамками 300 м … 10 км. Пустую выдачу повторяем с радиусом ×2 (максимум 1 раз)
5. [ ] **Поиск:** `rag.search(query_rewritten, lat, lon, radius_m, categories, top_k=15)`
6. [ ] **Фильтры в коде** (не в LLM!): дистанция ≤ радиус; `open_status` через `rag.open_status(..., now)`; `closed` выкидываем, `unknown` оставляем с пометкой; дети/доступность по полям POI. Итог: 5–8 кандидатов
7. [ ] **Генерация** (`generate.py`): кандидаты оборачиваем в `<untrusted_data>` (описания из интернета являются данными, а не инструкциями). LLM возвращает JSON: 1–3 `poi_id` **только из списка**, `why` (1 предложение, по фактам из описания), `visit_min`, `what_to_do`, `source` (если совет не опирается на данные POI, ставим `generated`). `temperature=0`. Ответ на языке `lang`
8. [ ] **Проверка ответа:** pydantic-валидация; `poi_id` должен быть среди кандидатов, иначе выкидываем (это защита от галлюцинаций); `distance_m`, `travel_min`, `open_status`, `rating`, `source_url` **подставляет код из POI**, а не LLM. При невалидном JSON делаем 1 ретрай, потом fallback: топ-3 кандидата с шаблонным «почему»
9. [ ] **`used_context`** заполняем всегда: так система явно показывает, какие данные использовала (требование организаторов)

### Этап 2 — фишки для «креативности» (после CP2)
- [ ] **Мини-маршрут** из 3 мест: nearest neighbour от пользователя, `route.total_min` = путь + визиты, должно укладываться в `time_budget_min`
- [ ] **Мультиязычность:** `lang` = ru/kk/en (ответ на языке пользователя, автоопределение по запросу)
- [ ] **Доступность и группы:** `profile.accessibility` фильтрует по `wheelchair != "no"`; при `group_size` 3–5 даём подсказку в промпт
- [ ] (опц.) Трассировка Langfuse: координаты в трейсы **не пишем**

### Приватность (обязательно, оценивается жюри)
- [ ] Не логировать `location` и сырой `query`; в логах только `request_id`, latency, число кандидатов
- [ ] Ничего не хранить между запросами (без БД пользователей); `disclaimer` в каждом ответе
- [ ] Если `opening_hours` нет, никаких «открыто сейчас»: `unknown` + `notes`

---

## Подсказки из конспектов
- Промпт RAG с цитатами и правилом «только по контексту»: [rag.md](../rag.md) §8.1, §9.7
- Structured output / JSON для роутеров: [rag.md](../rag.md) §9.8
- Многоуровневая защита (untrusted, схема выхода): [ai_security.md](../ai_security.md) §4.3–4.5, §8
- Не прописывать жёсткий порядок tools в промпте; детерминированное делать кодом: [prompting_memory_tools.md](../prompting_memory_tools.md) §2.2
- LangGraph **не нужен**: пайплайн линейный, хватит обычной функции ([ai_engineering.md](../ai_engineering.md) §14)

## Что ты получаешь / отдаёшь
- **Получаешь** от Data & RAG: `rag.search`, `rag.resolve_landmark`, `rag.open_status`, `data/processed/pois.json`
- **Отдаёшь** Frontend и QA: работающий `POST /api/recommend` по контракту + инструкцию запуска (`uvicorn backend.app.main:app --reload`)

## Definition of Done
- [ ] Все 5 сценариев из ТЗ дают валидный JSON с 1–3 местами, «почему», временем, «что делать»
- [ ] Ни одной рекомендации с `poi_id`, которого нет в базе (проверяет eval от QA)
- [ ] Ответ укладывается в < 8 с на запрос
- [ ] `backend/README.md`: запуск, переменные `.env`, схема пайплайна в 8 шагов
- [ ] PR `feature/backend` → `main` смержен после `data-rag`
