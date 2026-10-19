# Telegram-бот Серу

Тонкий клиент публичного API: геолокация, текст или фото → 1–3 места рядом. Ответы те же, что на сайте и в MCP-коннекторе. Своих данных, модели и базы у бота нет. Перенесён из бэкенда Abegerov4 (`backend/telegram_bot`) на общий API.

```bash
pip install -r bot/requirements.txt
TELEGRAM_BOT_TOKEN=... SERU_API=https://seruendesh.site python -m bot.telegram_bot
```

Приватность:
- геолокация округляется до ~100 м и живёт в памяти процесса 30 минут, `/forget` стирает её сразу;
- фото уходит в `/api/recommend/photo`: там удаляются EXIF и GPS, картинка не сохраняется;
- в логах нет chat id, координат и текста.
