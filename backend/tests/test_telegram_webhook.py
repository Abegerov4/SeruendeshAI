"""The Telegram webhook is off without a token and only accepts calls that carry Telegram's secret header."""
import asyncio

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
