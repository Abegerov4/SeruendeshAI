from backend.app.pipeline import recommend
from backend.app.schemas import RecommendRequest
from backend.telegram_bot.bot import build_app
from backend.telegram_bot.format import SCENARIOS, format_response


def _resp(query: str, **kw):
    return recommend(RecommendRequest(query=query, now="2026-10-18T15:00:00+05:00", **kw))


def test_format_has_why_action_badges_and_transparency():
    text = format_response(_resp("с ребёнком площадка или музей", location={"lat": 51.0899, "lon": 71.4110}))
    assert "<b>1." in text and "Почему:" in text and "Что делать:" in text
    assert "openstreetmap.org" in text and "Учёл:" in text
    assert any(b in text for b in ("🟢", "🔴", "⚪"))


def test_format_escapes_html_and_handles_empty():
    text = format_response(_resp("<script>куда сходить?</script>"))
    assert "<script>" not in text and "ℹ️" in text


def test_scenarios_are_short_callbacks():
    assert all(len(f"sc:{k}".encode()) <= 64 for k in SCENARIOS)  # лимит callback_data в Telegram


def test_app_builds_with_handlers():
    app = build_app("123456:TEST-token-not-real")
    assert sum(len(h) for h in app.handlers.values()) >= 6
