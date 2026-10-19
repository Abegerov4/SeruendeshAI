"""City Insights publishes only k-anonymous counters and never stores the query or the person."""
from sqlalchemy import inspect

from app import db, insights


def post(client, **body):
    r = client.post("/api/recommend", json={"lang": "ru", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_cells_are_published_only_from_k_requests(client):
    for _ in range(insights.K):
        post(client, query="Хочу кофе рядом", location={"lat": 51.1601, "lon": 71.4702})
    for _ in range(2):
        post(client, query="Где музей?", location={"lat": 51.0902, "lon": 71.4180})
    d = client.get("/api/insights?days=7").json()
    cells = {(c["lat"], c["lon"]): c for c in d["cells"]}
    assert (51.16, 71.47) in cells and cells[(51.16, 71.47)]["requests"] >= insights.K
    assert (51.09, 71.42) not in cells and d["suppressed_requests"] >= 2
    assert any(i["key"] == "cafe" for i in d["intents"])


def test_no_text_or_precise_location_is_stored(client):
    post(client, query="секретная фраза у моего дома", location={"lat": 51.12345, "lon": 71.43219})
    columns = {c["name"] for c in inspect(db._engine).get_columns("demand_counts")}
    assert columns == {"key", "day", "cell_lat", "cell_lon", "slot", "intent", "unmet", "hits"}
    with db.SessionLocal() as s:
        for row in s.query(db.DemandCount).all():
            assert "секрет" not in row.key and round(row.cell_lat, 2) == row.cell_lat
