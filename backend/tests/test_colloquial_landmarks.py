"""People write «я у меги», not «Mega Silk Way»: colloquial names find the right landmark."""
import pytest


@pytest.mark.parametrize("query, start", [
    ("я у меги, хочу кофе", "Mega Silk Way"),
    ("я в меге, куда сходить", "Mega Silk Way"),
    ("мегада тұрмын, кофе ішкім келеді", "Mega Silk Way"),
    ("я возле старой меги", "ТРЦ «Мега Центр Астана»"),
    ("возле шатра хочу погулять", "Хан Шатыр"),
    ("я у шара на экспо", "Нур Алем (сфера EXPO)"),
    ("я на вокзале, есть 2 часа", "Вокзал Нурлы Жол"),
    ("возле абу даби кафе", "Abu Dhabi Plaza"),
    ("у океанариума с ребёнком", "Ailand (бывш. Думан)"),
    ("я в центральном парке", "Центральный парк"),
])
def test_colloquial_name_is_the_start(client, query, start):
    r = client.post("/api/recommend", json={"query": query, "lang": "ru", "now": "2026-10-20T15:00:00"}).json()
    assert r["used_context"]["location"]["source"] == "text_landmark"
    assert r["used_context"]["location"]["label"] == start


def test_a_word_that_only_starts_like_a_nickname_is_not_one(client):
    r = client.post("/api/recommend", json={"query": "хочу купить мегафон рядом с байтереком", "lang": "ru",
                                            "now": "2026-10-20T15:00:00"}).json()
    assert r["used_context"]["location"]["label"] == "Байтерек"
