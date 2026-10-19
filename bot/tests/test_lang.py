from bot.telegram_bot import detect_lang


def test_message_language_beats_ui_language():
    assert detect_lang("хочу кофе возле ханшатыра", "en") == "ru"
    assert detect_lang("Бәйтерек маңында кофе қайда ішуге болады?", "ru") == "kk"
    assert detect_lang("coffee near Baiterek", "en") == "en"


def test_fallback_to_ui_language_or_russian():
    assert detect_lang("coffee near Baiterek", "kk") == "kk"
    assert detect_lang("coffee near Baiterek", "de") == "ru"
    assert detect_lang("", "en") == "ru"
