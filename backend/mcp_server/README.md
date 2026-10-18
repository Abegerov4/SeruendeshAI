# MCP-сервер `seruendesh-astana`

Городской помощник по Астане в виде MCP-инструментов. Его можно подключить к Claude Desktop, Claude Code, Cursor или своему агенту, и ассистент сам будет искать места рядом, проверять часы работы и строить маршрут.

**Почему MCP, а не только HTTP API.** HTTP API нужен нашему фронтенду. MCP нужен для того, чтобы те же возможности получил любой AI-ассистент без отдельной интеграции. Модель сама решает, какой инструмент и когда вызвать: сначала поискать, потом проверить часы, потом собрать маршрут.

## Tools

Все инструменты только читают данные (`readOnlyHint`): ничего не создают, не отправляют и не удаляют.

| Tool | Что делает | Когда вызывать |
|---|---|---|
| `recommend_places` | Полный ответ помощника: 1–3 места с «почему», временем на визит, «что делать» и мини-маршрутом | Нужен готовый совет «куда сходить» |
| `search_pois` | Поиск мест по смыслу запроса рядом с ориентиром или точкой. Возвращает расстояние, время в пути и статус «открыто сейчас» | Агент подбирает варианты сам или уточняет |
| `check_open_status` | Открыто ли место в заданный момент (UTC+5). Без данных о часах возвращает `unknown` | Перед советом на вечер, ночь или конкретный день |
| `plan_route` | Порядок обхода 2–5 мест (ближайшее следующим), время в пути и на месте, `fits_budget` | Выбрано несколько мест |
| `get_poi` | Карточка места: описание и его источник, адрес, часы, контакты, доступность | Нужны подробности |

Внутри работает тот же пайплайн, что и у HTTP API: guardrails, поиск, decision model, проверка ответа. Поэтому рекомендации через MCP проходят те же защиты.

## Skill

[skill/SKILL.md](skill/SKILL.md) — инструкция для ассистента: когда срабатывать, в каком порядке вызывать tools, что запрещено и в каком формате отвечать. Чтобы подключить skill к Claude Code, скопируй папку в `~/.claude/skills/astana-walk-guide/`.

## Запуск

```bash
# stdio — для Claude Desktop / Claude Code
python -m backend.mcp_server.server

# streamable HTTP на http://localhost:8001/mcp — для удалённых клиентов
python -m backend.mcp_server.server --http --port 8001

# отладка в MCP Inspector
npx @modelcontextprotocol/inspector .venv/bin/python -m backend.mcp_server.server
```

**Подключение к Claude Desktop.** Скопируй [mcp.example.json](mcp.example.json) в `~/Library/Application Support/Claude/claude_desktop_config.json` и подставь свои пути и ключ.

**Подключение к Claude Code** (из корня репозитория):
```bash
claude mcp add seruendesh-astana -- .venv/bin/python -m backend.mcp_server.server
```

## Тесты
`pytest backend/tests/test_mcp.py`: in-memory клиент проверяет список tools и `readOnly`, поиск, часы, маршрут, рекомендации и ошибки.
