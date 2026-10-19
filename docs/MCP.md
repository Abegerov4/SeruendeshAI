# MCP-коннектор Seruendesh

Тот же сервис рекомендаций, что и `POST /api/recommend`, доступен как набор инструментов [Model Context Protocol](https://modelcontextprotocol.io).
Его можно подключить к Claude Desktop, Claude Code, MCP Inspector или любому MCP-клиенту.

- **URL:** `https://seruendesh.site/connector/mcp` (локально `http://localhost:8000/connector/mcp`)
- **Транспорт:** Streamable HTTP, без сессий (stateless), ответы JSON. Отдельный процесс не нужен: коннектор работает внутри того же FastAPI-приложения (`backend/app/mcp_connector.py`, официальный Python SDK `mcp`).
- **Авторизация:** не нужна, инструменты только читают открытые данные.

## Подключение

**Claude Desktop / claude.ai.** Откройте «Настройки → Коннекторы → Добавить свой коннектор» (Add custom connector) и вставьте URL `https://seruendesh.site/connector/mcp`.

Если в вашей версии нет пункта для удалённых коннекторов, подключите сервер через мост `mcp-remote` в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "seruendesh": {"command": "npx", "args": ["-y", "mcp-remote", "https://seruendesh.site/connector/mcp"]}
  }
}
```

**Claude Code:**

```bash
claude mcp add --transport http seruendesh https://seruendesh.site/connector/mcp
```

**MCP Inspector:** `npx @modelcontextprotocol/inspector`, затем Transport = Streamable HTTP и URL коннектора.

**Python (SDK `mcp` ≥ 2):**

```python
from mcp import Client

async with Client("https://seruendesh.site/connector/mcp") as c:
    r = await c.call_tool("recommend_places", {"query": "кофе и прогулка на час", "landmark": "baiterek"})
    print(r.structured_content["places"])
```

## Инструменты

| Инструмент | Параметры | Что возвращает |
|---|---|---|
| `recommend_places` | `query` (RU/KK/EN), `landmark?` (ключ из `list_landmarks` или название), `lat?`/`lon?` (округляются до 3 знаков, ~100 м), `time_budget_min?` (10–480, по умолчанию 60), `lang` = `ru`/`kk`/`en` | `summary`, `origin`, `places[]` (`poi_id`, `name`, `category`, `why`, `what_to_do`, `travel_min`, `travel_mode`, `opening` (подпись часов), `open_status`, `source_url`, `lat`/`lon` с 3 знаками), `route` (текст мини-маршрута или `null`), `notes`, `disclaimer`, `off_topic` |
| `check_open_status` | `poi_id`, `at?` (ISO 8601, время Астаны, например `2026-10-20T19:30`), `lang` | `status` (`open`, `closing_soon`, `closed`, `always`, `unknown`), `confidence`, `label`, `raw` (строка OSM), `next_change`, `holiday` |
| `get_poi` | `poi_id`, `lang` | публичные поля места: название, категория, адрес, координаты, часы из OSM, сайт, ссылка на источник, подтверждённые удобства, доступность для колясок, краткое описание |
| `list_landmarks` | нет | `landmarks[]`: `key`, `name`, `lat`, `lon` (ориентиры для `landmark`) |

Пример вызова `recommend_places`:

```json
{"query": "Я с ребёнком, хотим в тепло на пару часов", "landmark": "khan_shatyr", "lang": "ru"}
```

## Безопасность и ограничения

- Работают те же защиты, что и в HTTP API: телефоны, email и ИИН в тексте маскируются до вызова LLM, фразы вида «игнорируй инструкции» вырезаются. Координаты округляются до ~100 м и в языковую модель не передаются.
- Тексты из открытых данных (описания мест) очищаются от ссылок и инструкций, прежде чем уйти в чужую модель.
- Лимит: 30 вызовов инструментов в минуту на клиента (по IP), настраивается через `MCP_RATE_LIMIT_PER_MIN`. При превышении инструмент возвращает ошибку `rate_limited`.
- Часы работы считает код по данным OSM. Если часов в данных нет, статус будет `unknown`, а не «открыто».
- Ответы сформированы ИИ на основе открытых данных. Перед визитом проверяйте часы работы.
