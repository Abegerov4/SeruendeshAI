"""Home as a start («от дома»), the bot's home memory, address search and themed route ideas."""
from app import db, insights
from app.config import get_settings

HOME = {"lat": 51.1605, "lon": 71.4704, "label": "Кенесары 40"}


def post(client, **body):
    r = client.post("/api/recommend", json={"lang": "ru", "now": "2026-10-20T15:00:00+05:00", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_from_home_uses_the_saved_home_and_is_not_counted(client):
    d = post(client, query="Хочу погулять час недалеко от дома", home=HOME, landmark="baiterek")
    loc = d["used_context"]["location"]
    assert loc["source"] == "home" and loc["label"] == "Дом" and (loc["lat"], loc["lon"]) == (51.16, 71.47)
    with db.SessionLocal() as s:
        assert not any(r.cell_lat == 51.16 and r.cell_lon == 71.47 for r in s.query(db.DemandCount).all())


def test_home_choice_without_words_and_a_named_place_wins(client):
    assert post(client, query="Хочу кофе", home=HOME, use_home=True)["used_context"]["location"]["source"] == "home"
    d = post(client, query="Я возле Хан Шатыра, хочу кофе", home=HOME, use_home=True)
    assert d["used_context"]["location"]["source"] == "text_landmark"


def test_from_home_without_a_saved_home_says_how_to_add_it(client):
    d = post(client, query="Что интересного рядом с домом?", landmark="baiterek")
    assert d["used_context"]["location"]["source"] == "landmark" and any("Дом" in n for n in d["notes"])


def test_bot_home_api_needs_the_bot_key(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_api_key", "k")
    assert client.get("/api/bot/home", headers={"X-Seru-User": "u1"}).status_code == 403
    h = {"X-Seru-Bot-Key": "k", "X-Seru-User": "u1"}
    assert client.get("/api/bot/home", headers=h).json() == {"home": None}
    assert client.put("/api/bot/home", headers=h, json={"lat": 51.16049, "lon": 71.47041, "label": "дом"}).json()["home"]["lat"] == 51.16
    assert client.put("/api/bot/home", headers=h, json={"lat": 43.2, "lon": 76.9, "label": "Алматы"}).status_code == 422
    assert client.get("/api/bot/home", headers=h).json()["home"]["label"] == "дом"
    assert client.delete("/api/bot/home", headers=h).json() == {"home": None}


def test_geocode_finds_a_landmark_without_the_network(client):
    d = client.get("/api/geocode", params={"q": "Хан Шатыр"}).json()
    assert d["results"] and d["results"][0]["source"] == "gazetteer"


def test_route_ideas_are_real_routes(client):
    d = client.post("/api/routes/ideas", json={"landmark": "baiterek", "lang": "ru", "now": "2026-10-20T14:00:00+05:00"}).json()
    ideas = d["ideas"]
    assert len(ideas) >= 3 and all(2 <= len(i["stops"]) <= 3 and i["response"]["route"] for i in ideas)
    assert len({tuple(sorted(i["stops"])) for i in ideas}) == len(ideas)  # no two ideas with the same stops


def test_meta_offers_a_styled_basemap_only_with_a_key(client, monkeypatch):
    assert client.get("/api/meta").json()["map"] is None
    monkeypatch.setattr(get_settings(), "maptiler_key", "abc")
    m = client.get("/api/meta").json()["map"]
    assert "maps/streets-v2/256/{z}/{x}/{y}{r}.png?key=abc" in m["url"] and "dataviz" in m["data_url"] and "MapTiler" in m["attribution"]
