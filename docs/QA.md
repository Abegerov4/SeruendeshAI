# Astana Walk AI — Smart City

## Локальная интеграция big-data — 19 октября

Основной сервер текущего UI — `ayat_backend/`; `backend/ + rag/` сохранён отдельным сервисом для фото/MCP/Telegram. Каноническая база — 14 006 POI; общий безопасный набор рекомендаций — 2 750 мест. Исходные 14 607 source ID сохранены. Локальный профиль работает без платных провайдеров и SMTP.

Единый запуск с UI, аккаунтами и постоянной SQLite: `docker compose up --build`, адрес http://127.0.0.1:8001. Дополнительный сервер: `docker compose --profile secondary up --build`, порт 8002.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-integration.txt
cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..
sh scripts/run_local_integration.sh
# Открыть http://127.0.0.1:8001
```

Аудит и исправления: [реестр 44 проблем](docs/backend_model_data_audit_2026-10-19.md), [результаты устранения и оставшиеся ограничения](docs/audit_remediation_2026-10-19.md). Снимки данных публикуются атомарно; часы/удобства с конфликтами остаются неизвестными. Модель выбирает места, а фактические объяснения и времена формирует сервер. Запас до вылета: 2 часа для внутреннего, 3 для международного и неизвестного типа, дополнительно дорога и 15 минут неопределённости.

`/api/health` различает `runtime_id`, `readiness_profile`, `snapshot_version` и состояние LLM `off/configured/degraded/ok`. `configured` означает наличие настроек; `ok` требует свежих успешных ответов обеих ролей. `READINESS_PROFILE=llm` требует проверки модели. Платный прогрев при старте выключен (`LLM_WARMUP_ENABLED=false`). SMTP выключен до отдельной настройки.

## История QA исходного снимка

Ниже сохранены прежние материалы QA от 18 октября. Их числители относятся к предыдущему снимку; актуальные проверки указаны выше.

ИИ-помощник по прогулкам в Астане для Build with AI: пользователь сообщает локацию, интересы и время, система должна предложить 1–3 места с объяснением, временем посещения, конкретным действием и источником.

**QA проверен совместно с backend (`bdeefdc3`) и локальным экспортом 14 009 POI Астаны.** Ветка `qa` содержит только тесты и материалы QA; код backend и собранные данные в этот коммит не входят. Проверенный локальный API использует keyword/template fallback. Общий прогон в совмещённой рабочей копии: **549 passed, 42 failed, 40 skipped**. Это не готовность продукта: [результаты](eval/results.md), [найденные расхождения](docs/qa_findings.md).

QA использует существующие сценарии и валидаторы. Проверки работают с временными копиями POI; исходные файлы `data/` не изменяются.

## Быстрый запуск QA

Прогон проверен на Python 3.12; ключи моделей для локальных тестов не нужны.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-qa.txt
# Проверки QA без исходников backend: интеграции явно пропускаются
python -m pytest tests -q

# В рабочей копии, где уже подключены Backend и Data
python -m pip install -r backend/requirements.txt -r data/requirements.txt
python -m pytest tests backend/tests data/tests --pois data/processed/pois.json --live-backend -q
python -m eval.check_readiness --root . --output eval/readiness.md
```

`python -m pytest tests` запускает QA и, при наличии исходников backend, новый локальный API-набор. Без этих исходников локальные API-проверки явно пропускаются; `--live-backend` делает их отсутствие ошибкой. `python -m pytest` также собирает присутствующие тесты Backend и Data, но без флагов пропускает проверки реального экспорта и opt-in интеграции. При использовании QA-флагов явно указывайте путь `tests`, где объявлены эти параметры.

Общий прогон сейчас возвращает код 1 из-за обнаруженных расхождений. Readiness также должен оставаться **NOT READY**: настоящая цепочка RAG/модель/UI и материалы сдачи ещё не подтверждены.

## Что проверяется

| Уровень | Содержание | Что требуется |
|---|---|---|
| Offline QA | Контракты, намеренно испорченные ответы, ID, координаты, время, статусы, метрики, ошибки запуска | Только QA-зависимости |
| Локальный backend | 64 существующих golden-сценария, privacy, poisoned POI, выход модели, языковой fallback | Настоящий FastAPI; временные POI; внешние провайдеры отключены |
| Dataset | Схема, границы города, источники, атрибуция, часы, quarantine, загрузка и карта через API | Собранные 14 009 POI; релевантность пока не размечена |
| API | Настоящие HTTP-ответы, валидация ввода, рекомендации, карта, публичные проверки безопасности | Запущенный backend и реальные данные |
| RAG | Расстояние, часы, полночь, часовой пояс, радиус, категории, ориентир | Реальные модули `rag.*` и данные |
| UI | Настоящий интерфейс, ошибки, пустая выдача, текст ИИ, GPS и мобильный экран | Frontend, Playwright и [hooks](docs/frontend_test_contract.md) |
| Real E2E | UI → backend → реальные данные/RAG/модель → карточки | Все части и проверенная конфигурация без моков |
| Human / instrumented | Смысл ответов, языки, логи, исходящие вызовы, privacy, непрямой injection | Проверка по [матрице](docs/qa_strategy.md) |

В `tests/fixtures/` лежат явно вымышленные POI с `test:*` ID. Использовать их как реальную базу города, доказательство качества RAG или рекомендации жюри нельзя.

## Дополнительные интеграции

Команды ниже запускаются из корня репозитория после настройки соответствующих частей по их будущим инструкциям. QA не запускает сервисы и не создаёт платные вызовы незаметно.

```bash
# Реальный датасет
python -m pytest tests --pois data/processed/pois.json -m dataset

# Запущенный backend
python -m pytest tests --live-api --base-url http://127.0.0.1:8000 --pois data/processed/pois.json -m live_api

# Настоящий RAG
python -m pytest tests --live-rag --pois data/processed/pois.json -m live_rag

# Реальная функция маскирования PII; без HTTP и запросов к модели
python -m pytest tests --live-backend -m live_backend

# Все 64 сценария через настоящий API; модель может расходовать ваш API-бюджет
python -m eval.run_eval --base-url http://127.0.0.1:8000 --pois data/processed/pois.json --repeat 3 --output-dir eval/runs/local

# Готовность с измеренным отчётом (слайды/видео также должны существовать)
python -m eval.check_readiness --root . --evidence eval/runs/local/report.json --output eval/readiness.md
```

При явном включении отсутствующего backend/RAG/датасета проверка завершается ошибкой. Обычный offline-запуск пропускает эти проверки с причиной `NOT TESTED`.

Для UI отдельно установите браузер: `python -m pip install playwright`, затем `python -m playwright install chromium`. Команда `python -m pytest tests --live-ui --ui-url http://127.0.0.1:5173 -m live_ui` проверяет UI с контролируемыми ответами API; настоящая цепочка дополнительно требует `--live-api --pois data/processed/pois.json`.

## Измерения и LLM-судья

`run_eval` сохраняет `report.json` и `results.md`: pass/fail/unexecuted, долю ответов, неизвестные ID с числителем и знаменателем, p50/p95 всех попыток, хеши и контекст прогона. Отсутствие наблюдений обозначается `null`, а не хорошей метрикой. Истинность свободного текста и безопасность всех возможных атак не доказываются проверкой ID.

API возвращает максимум три места, поэтому метрики итогового ответа — **Hit@3/Recall@3** только на размеченных данных. **Recall@5 поиска** измеряется отдельно по первым пяти результатам `rag.search`; пока реальные эталонные POI не размечены, эта метрика NOT EVALUATED. Одна удачная рекомендация из нескольких релевантных — это Hit, а не полный Recall.

LLM-судья запускается отдельно через `python -m eval.judge --help`. Без `--execute` запрос к модели не отправляется. Для исполнения обязательны явные адрес API, модель и имя переменной с ключом. Оценки 1–5 дополняют проверки и требуют ручной калибровки.

## Материалы команды

- [Зоны ответственности и API](team/README.md), [задачи QA](team/04_qa_docs.md).
- [Стратегия и очередь интеграции](docs/qa_strategy.md), [сценарии и ограничения](docs/test_scenarios.md).
- [Концепция](docs/product_concept.md), [RAG](docs/rag_approach.md), [этика и приватность](docs/ethics_privacy.md).
- [План презентации](docs/presentation/pitch_outline.md), [сценарий демо](docs/demo_script.md).

PDF-презентация готова: `docs/presentation/SeruendeshAI-presentation.pdf`. Демо-видео записано (`submission/SeruendeshAI-demo.mp4`, 2:55), его осталось загрузить на YouTube. После их подготовки создайте `docs/submission.json` с `slides_path` (путь к PDF) и `demo_url` (ссылка YouTube). Проверка ссылки offline не подтверждает доступность или содержание видео — это нужно проверить отдельно.

Исходный план команды в `team/` сохранён. Обнаруженные противоречия и выбранные критерии описаны в стратегии QA. Никакие Git-коммиты, push или merge без разрешения пользователя не выполняются.
