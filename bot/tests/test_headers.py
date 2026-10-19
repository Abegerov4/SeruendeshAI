from bot.telegram_bot import api_headers


def test_per_user_headers_hide_the_telegram_id():
    h = api_headers(123456789, "key")
    assert h["X-Seru-Bot-Key"] == "key" and len(h["X-Seru-User"]) == 32 and "123456789" not in h["X-Seru-User"]
    assert api_headers(123456789, "key") == h and api_headers(987, "key")["X-Seru-User"] != h["X-Seru-User"]


def test_no_key_no_headers():
    assert api_headers(123, "") == {} and api_headers(None, "key") == {}
