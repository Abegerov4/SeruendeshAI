# Живая оценка продакшена — 19.10.2026

`backend/eval/run_eval.py --base-url https://seruendesh.site`: 15 сценариев, реальная модель (gpt-6-luna), реальные данные, HTTP через Railway.

- Первый прогон: 170/170 проверок, медиана 3,8 с, максимум 4,7 с.
- Повторный прогон (этот отчёт): 170/170, `failed=0`. Задержка меньше, потому что совпадающие запросы отдаются из кэша ответов.

`python -m eval.check_readiness --root . --evidence eval/runs/2026-10-19-production/live.json` — всё готово, кроме ссылки на YouTube в `docs/submission.json`.
