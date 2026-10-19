# SeruendeshAI: ИИ-помощник по прогулкам в Астане

> Основной UI-сервер. Запуск из корня: `docker compose up --build`, http://127.0.0.1:8001; либо `sh scripts/run_local_integration.sh` после сборки frontend. Старые показатели ниже относятся к прежнему снимку. Текущие результаты: [устранение аудита](../docs/reports/audit_remediation_2026-10-19.md).

> Хакатон **Build with AI**, задача 1 от **НИЦ Smart City**: RAG-система, которая в реальном времени подсказывает, куда сходить и что сделать рядом, с учётом локации, времени, погоды и предпочтений.

**«Я возле Mega Silk Way, у меня час. Куда?»** Система отвечает 1–3 конкретными местами. Для каждого:
- сколько идти (по реальному графу улиц) и сколько пробыть;
- **почему** это подходит именно сейчас и **что там делать**;
- статус часов работы с уровнем уверенности;
- метка источника: «Данные POI» или «Идея ИИ».

При необходимости строится мини-маршрут на карте. Блок «Что я учёл» показывает все использованные данные.

| | |
|---|---|
| Данные | Полный командный снимок `data/processed/pois.json`; места для прогулок используются в поиске, остальные адреса — как ориентиры. Исходный снимок Ayat в `pois.jsonl` сохранён для совместимости. |
| RAG | Структурные фильтры → BM25 и опциональный согласованный e5 → модель выбирает ID → сервер формирует фактические тексты и расписание |
| Языки | RU / KK / EN |
| Качество | 15 сценариев × 12 автоматических проверок: **170/170**, ответ ~3.5 с ([EVAL_RESULTS](docs/EVAL_RESULTS.md)) |
| Приватность | Локация округляется до ~100 м, не хранится и не передаётся в LLM |

## Документы для жюри
| Требование задачи | Документ |
|---|---|
| 1. Концепция продукта, аудитория, сценарии, бизнес, риски, план | [docs/CONCEPT.md](docs/CONCEPT.md) |
| 2. Демо / прототип | API (этот репозиторий) + фронтенд в [`../frontend/`](../frontend/) |
| 3. Описание RAG-подхода | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 4. Тестовые сценарии и ограничения | [docs/TEST_SCENARIOS.md](docs/TEST_SCENARIOS.md), [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) |
| 5. Презентация | [docs/PRESENTATION.md](docs/PRESENTATION.md) (план слайдов и сценарий демо) |
| 6. Этика и приватность | [docs/ETHICS_PRIVACY.md](docs/ETHICS_PRIVACY.md) |
| Сбор данных (автоматизирован) | [docs/DATA.md](docs/DATA.md) |
| Как выбирали стек (исследование) | [docs/RESEARCH.md](docs/RESEARCH.md) |
| API-контракт для фронтенда | [docs/API.md](docs/API.md), [docs/api/openapi.json](docs/api/openapi.json), [примеры](docs/api/examples/) |

## Быстрый старт

Нужны Python ≥ 3.12 и [uv](https://docs.astral.sh/uv/). Ключ OpenAI необязателен: без него работает шаблонный режим.

```bash
cp ayat_backend/.env.example ayat_backend/.env
uv sync --project backend
LLM_ENABLED=false EMBED_MODEL=off WEATHER_ENABLED=false \
  uv run --project backend uvicorn ayat_backend.app.main:app --port 8000
```

- Swagger: http://localhost:8000/docs
- Проверка: `curl localhost:8000/api/health`
- Команда выше работает локально: BM25, шаблонные ответы и часы работы; запросы к ИИ и погодному сервису отключены, модель эмбеддингов не скачивается.
- Аккаунты и случайные сессии хранятся в SQLite (`ayat_backend/.local/app.db`), если `DATABASE_URL` не задан; Docker использует постоянный volume. Logout отзывает текущую сессию, reset — все сессии. `SECRET_KEY` больше не подписывает cookie; при переходе старые подписанные cookie потребуют повторного входа.

Пример запроса:

```bash
curl -s localhost:8000/api/recommend -H 'content-type: application/json' -d '{
  "query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?",
  "lang": "ru"
}' | python -m json.tool
```

Фронтенд (React + Vite) лежит в `frontend/`, инструкции в [../frontend/README.md](../frontend/README.md). Укажите `VITE_API_URL=http://localhost:8000`.

Docker: `docker compose up --build` из корня; `.env` необязателен. По умолчанию LLM/погода/dense/SMTP отключены. Для платной проверки используйте отдельный явный запуск с лимитом, например `python -m scripts.live_model_probe --key-file /path/to/key --out eval/runs/live`; общий ledger не зависит от каталога вывода.

### Команды

```bash
make -C ayat_backend test        # unit + контрактные тесты, временная SQLite, без провайдеров
make -C ayat_backend eval        # 15 сценариев в шаблонном режиме
make -C ayat_backend eval-llm    # те же сценарии с LLM + LLM-as-judge
make -C ayat_backend data        # полный автоматический сбор данных: fetch → build → graph → embed → events
make -C ayat_backend contract    # выгрузить OpenAPI и примеры ответов для фронтенда
```

## Как это работает (кратко)

```
запрос + фильтры + локация (~100 м)
  ├─ правила (язык, время, дети, кофе, ночь…)      ┐
  ├─ LLM-разбор gpt-6-luna → строгий JSON          ├─ параллельно
  ├─ погода Open-Meteo, праздники РК, темнота      │
  └─ эмбеддинг запроса (e5-large, локально)        ┘
→ точка старта (ориентир в тексте / GPS / список)
→ достижимость: Dijkstra по пешеходному графу OSM (мосты через Есиль!)
→ жёсткие фильтры в коде: часы при прибытии, дети, доступность, темнота, мороз, дедлайн рейса
→ скоринг: категория + BM25/e5 (RRF), близость, нужды, часы, контекст, популярность → MMR
→ мини-маршрут: перебор порядков 2–3 точек с проверкой часов
→ LLM выбирает 1–3 из карточек c1..c10; код формирует «почему» / «что делать», часы и фактическую длительность
→ валидатор: только известные id; числа, часы и «открыто сейчас» вырезаются; иначе шаблон
```

Подробно в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Структура репозитория
```
ayat_backend/
  app/            FastAPI-приложение: схемы (контракт), поиск, ранжирование, маршруты, LLM, валидатор
  pipeline/       автоматический сбор данных (Overpass, Overture, Wikidata, Wikipedia, Ticketon/Sxodim, граф, эмбеддинги)
  tests/          unit + контрактные тесты
data/processed/   закоммиченный снимок данных (POI, газеттир, граф, эмбеддинги, манифест с лицензиями)
eval/             сценарии + харнесс оценки (проверки + LLM-as-judge)
docs/             концепция, архитектура, данные, этика, сценарии, презентация, API
frontend/         интерфейс (React + Vite)
```

## Ограничения
Честно описаны в [docs/TEST_SCENARIOS.md](docs/TEST_SCENARIOS.md#ограничения). Главные:
- часы работы есть у ~20% мест;
- рейтингов в открытых данных нет;
- розетки и «тишина» почти не размечены;
- пешеходный граф покрывает центр, ЭКСПО и НУ;
- время на машине оценивается эвристикой, без пробок в реальном времени.

## Лицензии данных
© OpenStreetMap contributors (ODbL) · Overture Maps Foundation (CDLA-Permissive-2.0 / Apache-2.0 / CC0) · Wikidata (CC0) · Wikipedia (CC BY-SA 4.0, ссылки в карточках) · Open-Meteo (CC BY 4.0) · события: Ticketon, Sxodim (только факты и ссылка).
