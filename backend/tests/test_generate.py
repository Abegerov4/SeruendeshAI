

def test_sentences_about_the_data_are_dropped_from_explanations():
    from app.generate import drop_meta_sentences
    assert drop_meta_sentences("Отличный вид на город. В карточке нет данных о часах.") == "Отличный вид на город."
    assert drop_meta_sentences("Это единственный кандидат рядом.") == ""
