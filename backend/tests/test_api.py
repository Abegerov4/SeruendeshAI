"""Contract tests against the real data snapshot, in template mode (no API key needed)."""
import re
from app.schemas import RecommendResponse

W = {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 4}


def post(c, **body):
    body.setdefault("now", "2026-10-18T15:00:00+05:00")
    body.setdefault("weather", W)
    r = c.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    RecommendResponse.model_validate(r.json())
    return r.json()


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["pois"] > 1000 and h["llm"] in ("ok", "off")
    m = client.get("/api/meta").json()
    keys = {x["key"] for x in m["landmarks"]}
    assert {"baiterek", "khan_shatyr", "mega_silk_way", "airport"} <= keys


def test_recommend_contract(client):
    d = post(client, query="Я возле Байтерека, хочу погулять час")
    poi = [i for i in d["recommendations"] if i["source"] == "poi_data"]
    assert 1 <= len(poi) <= 3
    for i in poi:
        assert i["distance_m"] >= 0 and i["travel_min"] <= d["used_context"]["time_budget_min"]
        assert i["open_status"] in ("open", "unknown") and i["open_confidence"] in ("high", "low", "none")
        assert len(i["visit_min"]) == 2 and i["visit_min"][0] <= i["visit_min"][1]
        assert i["source_label"] and i["poi_id"]
    u = d["used_context"]
    assert {"location_source", "location_label", "radius_m", "time_budget_min", "mode", "filters", "now"} <= set(u)
    assert d["ai_generated"] is True and d["disclaimer"]


def test_location_is_rounded_and_not_echoed_precisely(client):
    d = post(client, query="кофе рядом", location={"lat": 51.1283456, "lon": 71.4304567})
    loc = d["used_context"]["location"]
    assert d["used_context"]["location_source"] == "gps_rounded" and loc["lat"] == 51.128 and loc["lon"] == 71.43
    assert "51.1283456" not in str(d)


def test_kids_never_get_bars(client):
    d = post(client, query="с ребёнком куда сходить вечером", location={"lat": 51.128, "lon": 71.43},
             now="2026-10-18T19:00:00+05:00")
    assert not any(i["category_detail"] in ("bar", "nightclub", "hookah") for i in d["recommendations"])


def test_kids_get_public_places_not_courtyard_playgrounds(client):
    # Khan Shatyr has residential-complex courtyard playgrounds within 50 m; a family is sent to public places
    d = post(client, query="Я с ребёнком, где рядом площадка или интерактивный музей?", landmark="khan_shatyr",
             now="2026-10-20T15:00:00+05:00")
    names = [i["name"] for i in d["recommendations"] if i["source"] == "poi_data"]
    assert names and not any(" в ЖК «" in n for n in names), names


FAR_GPS = {"lat": 51.16, "lon": 71.47}  # right bank, ~6 km from Khan Shatyr


def test_named_place_with_gps_is_the_destination_not_a_new_start(client):
    # «мечеть Хазрет Султан» / «хочу в Хан Шатыр» from across the river: the route starts from the user
    for q, name in (("мечеть Хазрет Султан", "хазрет султан"), ("хочу в Хан Шатыр", "хан шатыр"),
                    ("отведи меня к Пирамиде", "дворец мира")):
        d = post(client, query=q, location=FAR_GPS, now="2026-10-20T15:00:00+05:00")
        assert d["used_context"]["location_source"] == "gps_rounded", q
        first = d["recommendations"][0]
        assert name in first["name"].lower(), (q, first["name"])


def test_kind_of_place_inside_a_named_one_keeps_it_as_the_area(client):
    d = post(client, query="кофейня в Mega Silk Way", location=FAR_GPS, now="2026-10-20T15:00:00+05:00")
    assert d["used_context"]["location_label"] == "Mega Silk Way"


def test_inflected_word_is_not_a_short_map_name(client):
    # «в Центральном парке» must not turn into the café «Централ» as the start
    d = post(client, query="погулять в Центральном парке", location=FAR_GPS, now="2026-10-20T15:00:00+05:00")
    assert d["used_context"]["location_source"] == "gps_rounded"


def test_extreme_cold_switches_to_taxi_and_indoor(client):
    d = post(client, query="погулять час", landmark="baiterek",
             weather={"temperature_c": -25, "feels_like_c": -33, "wind_ms": 10})
    assert d["used_context"]["mode"] == "car"
    assert not any("outdoor" in i["badges"] for i in d["recommendations"] if i["source"] == "poi_data")


def test_bad_input_422(client):
    assert client.post("/api/recommend", json={"time_budget_min": 5}).status_code == 422


def test_team_contract_request_and_no_location(client):
    d = post(client, query="Где выпить кофе?", mode="walk",
             profile={"with_kids": False, "tourist": False, "accessibility": False, "group_size": 1})
    assert d["recommendations"] == [] and d["used_context"]["location_source"] == "none"
    assert any("локацию" in n for n in d["notes"])


def test_pois_endpoint(client):
    r = client.get("/api/pois", params={"lat": 51.128, "lon": 71.43, "radius_m": 500}).json()
    assert r and all({"id", "name", "category", "lat", "lon"} <= set(x) for x in r)


def test_events_attach_to_venues(client):
    d = post(client, query="Хочу вечером на спектакль или концерт", location={"lat": 51.164, "lon": 71.418},
             now="2026-10-20T18:20:00+05:00", time_budget_min=180)
    evs = [r["event"] for r in d["recommendations"] if r["event"]]
    if evs:  # depends on the collected snapshot; when present it must be well-formed
        assert all(e["title"] and e["starts_at"] and e["source"] in ("ticketon", "sxodim") for e in evs)


def test_refinements_change_results(client):
    base = dict(query="Хочу погулять и выпить кофе", landmark="khan_shatyr")
    plain = post(client, **base)
    no_coffee = post(client, **base, refine=["no_coffee"])
    indoor = post(client, **base, refine=["indoor"])
    closer = post(client, **base, refine=["closer"])
    assert not any(r["category_detail"] in ("cafe", "sweets") for r in no_coffee["recommendations"])
    assert not any("outdoor" in r["badges"] for r in indoor["recommendations"] if r["source"] == "poi_data")
    assert closer["used_context"]["radius_m"] < plain["used_context"]["radius_m"]


def test_frontend_is_served_when_built(client):
    r = client.get("/")
    assert r.status_code in (200, 404)
    assert client.get("/api/unknown").status_code == 404


def test_accounts_flow(client):
    import uuid
    email = f"t{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"name": "Аят", "email": email, "password": "short"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"name": "Аят", "email": email, "password": "correct horse 1"})
    assert r.status_code == 201 and r.json()["email"] == email
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["name"] == "Аят" and me.json()["email"] == email  # flat UserOut, as before
    assert {"id", "email", "name", "lang", "created_at"} == set(me.json())
    assert client.post("/api/auth/register", json={"name": "X Y", "email": email, "password": "another pass"}).status_code == 409
    assert client.put("/api/me/saved/osm:n1", json={"data": {"name": "Кафе", "lat": 51.1, "secret": "x"}}).status_code == 200
    saved = client.get("/api/me/saved").json()
    assert saved[0]["poi_id"] == "osm:n1" and "secret" not in saved[0]["data"]
    client.post("/api/auth/logout")
    guest = client.get("/api/auth/me")
    assert guest.status_code == 200 and guest.json() == {"user": None}  # guests: no 401
    assert client.get("/api/me/saved").status_code == 401  # private endpoints still require a session
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email.upper(), "password": "correct horse 1"}).status_code == 200
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/auth/me").json() == {"user": None}
    assert client.post("/api/auth/login", json={"email": email, "password": "correct horse 1"}).status_code == 401


def test_auth_me_guest_and_bad_cookie(client):
    client.cookies.set("seru_session", "garbage")
    r = client.get("/api/auth/me")
    client.cookies.clear()
    assert r.status_code == 200 and r.json() == {"user": None}


def test_meta_features(client):
    f = client.get("/api/meta").json()["features"]
    assert set(f) == {"password_reset_email", "photo", "mcp"} and isinstance(f["password_reset_email"], bool)
    assert f["photo"] is False and f["mcp"] is True  # tests run without an LLM


def test_off_topic_queries_get_a_friendly_note(client):
    from .test_units import OFF_TOPIC_QUERIES
    for q in OFF_TOPIC_QUERIES[:3]:
        d = post(client, query=q, landmark="baiterek")
        assert d["off_topic"] is True and d["recommendations"] == [] and d["route"] is None, q
        assert "Астан" in d["summary"] and d["summary"] in d["notes"]
    d = post(client, query="write me some code in python", lang="en")
    assert d["off_topic"] is True and "Astana" in d["notes"][-1]
    d = post(client, query="код жазып бер", lang="kk")
    assert d["off_topic"] is True and "Астанадағы" in d["summary"]


def test_normal_queries_are_never_off_topic(client):
    from .test_units import NORMAL_QUERIES
    for q in NORMAL_QUERIES:
        d = post(client, query=q, landmark="baiterek", time_budget_min=120)
        assert d["off_topic"] is False and "Серу" not in d["summary"], q
        assert d["recommendations"], q


def test_llm_usage_block_is_additive(client):
    d = post(client, query="кофе рядом", landmark="baiterek")
    assert d["llm"]["mode"] == "template" and d["llm"]["usage"] == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    assert d["off_topic"] is False


def test_strict_schema_and_query_truncation(client):
    bad = {"query": "кофе", "location": {"lat": "51.128", "lon": 71.43}}  # numbers as strings are not coerced
    assert client.post("/api/recommend", json=bad).status_code == 422
    d = post(client, query="кофе " * 400, landmark="baiterek")
    assert d["recommendations"]


def test_pii_is_masked_and_noted(client):
    d = post(client, query="кофе рядом, мой номер +7 701 123 45 67", landmark="baiterek")
    assert any("личн" in n.lower() for n in d["notes"])


def test_destination_is_recommended_and_ideas_are_separate(client):
    d = post(client, query="я у Байтерека, хочу дойти до Хан Шатыра", time_budget_min=90)
    assert d["used_context"]["location_label"].startswith("Байтерек")
    assert any("Хан Шатыр" in r["name"] or "Khan Shatyr" in r["name"] for r in d["recommendations"])
    assert all(r["source"] == "poi_data" for r in d["recommendations"])
    assert all(i["source"] == "generated" for i in d.get("ideas", []))


def test_hotel_is_a_valid_origin(client):
    d = post(client, query="я в отеле Hilton Astana, где выпить кофе в 15 минутах пешком?")
    assert d["used_context"]["location_source"] == "landmark" and d["recommendations"]


def test_requested_destination_closed_is_explained(client):
    d = post(client, query="я у Байтерека, хочу дойти до Хан Шатыра", time_budget_min=90, now="2026-10-19T01:00:00+05:00")
    if not any("Шатыр" in r["name"] for r in d["recommendations"]):
        assert "Хан Шатыр" in d["summary"] and any("Хан Шатыр" in n for n in d["notes"])


def test_route_to_a_place_from_rounded_gps_and_from_a_landmark(client):
    d = post(client, query="кофе рядом", landmark="baiterek")
    pid = d["recommendations"][0]["poi_id"]
    r = client.post("/api/route", json={"poi_id": pid, "location": {"lat": 51.12834, "lon": 71.43051}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["origin"] == {"lat": 51.128, "lon": 71.431} and j["origin_source"] == "gps_rounded"
    assert j["distance_m"] > 0 and j["travel_min"] >= 1 and len(j["polyline"]) >= 2 and "2gis" in j["links"]
    assert client.post("/api/route", json={"poi_id": pid, "landmark": "baiterek"}).json()["origin_source"] == "landmark"
    # GPS outside Astana and no landmark: no silent guess
    assert client.post("/api/route", json={"poi_id": pid, "location": {"lat": 43.24, "lon": 76.95}}).status_code == 422
    assert client.post("/api/route", json={"poi_id": "nope:1", "landmark": "baiterek"}).status_code == 404


def test_route_to_botanical_garden_is_a_navigation_answer(client):
    d = post(client, query="маршрут до ботсада", location={"lat": 51.128, "lon": 71.43})
    names = [r["name"] for r in d["recommendations"]]
    assert len(names) == 1 and ("бақ" in names[0].lower() or "ботан" in names[0].lower()), names
    assert d["navigate_to"] == d["recommendations"][0]["poi_id"]
    assert d["used_context"]["location_source"] == "gps_rounded"  # the garden is the destination, not the start


def test_negated_place_types_are_avoided_not_required(client):
    d = post(client, query="Хочу чего-то необычного, не торговый центр", location={"lat": 51.1325, "lon": 71.4037},
             now="2026-10-20T15:00:00+05:00")
    assert d["recommendations"] and all(r["category"] != "mall" for r in d["recommendations"])
    d = post(client, query="Только не кофейня! Хочу активно провести 2 часа рядом", location={"lat": 51.1325, "lon": 71.4037},
             now="2026-10-20T15:00:00+05:00")
    assert d["recommendations"] and all(r["category"] != "cafe" for r in d["recommendations"])


def test_view_wish_leads_with_an_observation_deck(client):
    d = post(client, query="Хочу посмотреть город с высоты, где лучшая смотровая площадка?",
             location={"lat": 51.1325, "lon": 71.4037}, now="2026-10-20T15:00:00+05:00")
    first = d["recommendations"][0]["name"].lower()
    assert "байтерек" in first or "бәйтерек" in first or "nur alem" in first, first
    assert all(r["category"] != "playground" for r in d["recommendations"])  # «площадка» is not a playground here


def test_climbing_a_named_landmark_makes_it_the_destination(client):
    d = post(client, query="Хочу подняться на Байтерек, что ещё рядом?", location={"lat": 51.1325, "lon": 71.4037},
             now="2026-10-20T15:00:00+05:00")
    assert any("терек" in r["name"].lower() for r in d["recommendations"])


def test_polluted_air_shortens_outdoor_time_and_says_why(client):
    d = post(client, query="Хочу погулять час", landmark="baiterek",
             weather={"temperature_c": 5.0, "feels_like_c": 3.0, "wind_ms": 2.0, "precipitation": False, "us_aqi": 172.0})
    assert d["used_context"]["weather"]["us_aqi"] == 172 and d["used_context"]["weather"]["max_outdoor_min"] <= 20
    assert any("AQI 172" in n for n in d["notes"])


def test_route_from_a_named_start_to_a_named_destination(client):
    d = post(client, query="так окей закинь мне маршрут с AITU до ботсада", landmark="baiterek")
    names = [r["name"] for r in d["recommendations"]]
    assert len(names) == 1 and "ботан" in names[0].lower(), names
    assert d["used_context"]["location"]["label"].startswith("Astana IT University")  # the start from the text, not the UI landmark
    assert d["navigate_to"] == d["recommendations"][0]["poi_id"]
    assert "AITU" in d["summary"] and "Ботанический сад" in d["summary"]


def test_start_and_place_names_follow_the_users_language(client):
    for lang, start in (("en", "Baiterek"), ("kk", "Бәйтерек"), ("ru", "Байтерек")):
        d = post(client, query="погулять час", landmark="baiterek", lang=lang, now="2026-10-20T15:00:00+05:00")
        assert d["used_context"]["location_label"] == start
    d = post(client, query="walk for an hour", landmark="baiterek", lang="en", now="2026-10-20T15:00:00+05:00")
    names = [i["name"] for i in d["recommendations"] if i["source"] == "poi_data"]
    # translated places come in English; auto-labelled squares keep their labels (a Kazakh street in brackets)
    assert any(not re.search(r"[а-яёәғқңөұүһі]", n, re.I) for n in names), names
