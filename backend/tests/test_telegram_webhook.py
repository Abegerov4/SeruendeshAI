"""The Telegram webhook is off without a token, only accepts calls that carry Telegram's secret header,
and is restored when a polling copy of the bot with the same token removed it."""
import asyncio
from types import SimpleNamespace

from app import telegram


def test_webhook_is_absent_when_the_bot_is_not_configured(client):
    assert client.post("/telegram/webhook", json={"update_id": 1}).status_code == 404


def test_webhook_rejects_calls_without_the_secret(client, monkeypatch):
    seen = []

    class FakeQueue:
        async def put(self, update):
            seen.append(update)

    class FakeApp:
        update_queue = FakeQueue()
        bot = None

    monkeypatch.setitem(telegram._STATE, "app", FakeApp())
    monkeypatch.setitem(telegram._STATE, "secret", "s3cret")
    assert client.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
    assert client.post("/telegram/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
    ok = client.post("/telegram/webhook", json={"update_id": 7}, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert ok.status_code == 200 and seen and seen[0].update_id == 7


def test_start_is_a_no_op_without_a_token():
    asyncio.run(telegram.start(8000))
    assert telegram._STATE["app"] is None


class FakeBot:
    def __init__(self, url: str):
        self.url, self.calls = url, []

    async def get_webhook_info(self):
        return SimpleNamespace(url=self.url)

    async def set_webhook(self, url, secret_token, allowed_updates):
        self.calls.append((url, secret_token, tuple(allowed_updates)))
        self.url = url


def _one_round(bot: FakeBot, url: str, monkeypatch) -> None:
    monkeypatch.setattr(telegram, "WATCH_S", 0)

    async def go():
        task = asyncio.create_task(telegram._watch(SimpleNamespace(bot=bot), url, "s3cret"))
        await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(go())


def test_removed_webhook_is_restored(monkeypatch):
    bot = FakeBot(url="")  # what Telegram reports after `make bot` ran in polling mode
    _one_round(bot, "https://seruendesh.site/telegram/webhook", monkeypatch)
    assert bot.calls[0] == ("https://seruendesh.site/telegram/webhook", "s3cret", ("message", "callback_query"))
    assert len(bot.calls) == 1  # restored once, then left alone


def test_registered_webhook_is_left_alone(monkeypatch):
    url = "https://seruendesh.site/telegram/webhook"
    bot = FakeBot(url=url)
    _one_round(bot, url, monkeypatch)
    assert bot.calls == []
