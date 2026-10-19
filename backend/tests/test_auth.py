"""Account ownership is enforced against the real temporary SQLite database."""
from urllib.parse import quote

from fastapi.testclient import TestClient


def register(client, email, name):
    response = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "local test password 123",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_encoded_canonical_poi_id_can_be_saved_and_deleted(client):
    register(client, "canonical-id@example.com", "Canonical ID")
    poi_id = "osm:node/123"
    endpoint = f"/api/me/saved/{quote(poi_id, safe='')}"

    response = client.put(endpoint, json={"data": {"name": "Canonical café"}})
    assert response.status_code == 200, response.text
    assert response.json()["poi_id"] == poi_id
    saved = client.get("/api/me/saved").json()
    assert [(row["poi_id"], row["data"]) for row in saved] == [
        ("osm:node/123", {"name": "Canonical café"}),
    ]
    assert client.delete(endpoint).status_code == 204
    assert client.get("/api/me/saved").json() == []
    assert client.delete("/api/me").status_code == 204


def test_saved_places_are_private_and_removable(client):
    from app.main import app

    owner = register(client, "owner@example.com", "Owner")
    saved = client.put("/api/me/saved/osm:n1", json={"data": {"name": "Кафе", "secret": "discard"}})
    assert saved.status_code == 200
    assert saved.json()["data"] == {"name": "Кафе"}

    other = TestClient(app)
    try:
        assert other.get("/api/me/saved").status_code == 401
        stranger = register(other, "stranger@example.com", "Stranger")
        assert stranger["id"] != owner["id"]
        assert other.get("/api/me/saved").json() == []
        assert other.delete("/api/me/saved/osm:n1").status_code == 204
        assert [row["poi_id"] for row in client.get("/api/me/saved").json()] == ["osm:n1"]
        assert other.put("/api/me/saved/osm:n1", json={"data": {"name": "Other café"}}).status_code == 200
        assert client.get("/api/me/saved").json()[0]["data"]["name"] == "Кафе"
        assert other.delete("/api/me").status_code == 204
        assert other.get("/api/auth/me").json() == {"user": None}  # guests: 200 {user: null}
        assert client.get("/api/auth/me").json()["id"] == owner["id"]
        assert client.delete("/api/me/saved/osm:n1").status_code == 204
        assert client.get("/api/me/saved").json() == []
        assert client.delete("/api/me").status_code == 204
    finally:
        other.close()


def test_deletion_removes_persisted_saved_places_and_login(client):
    from sqlalchemy import select

    from app.db import SavedPlace, User
    from app import db

    user = register(client, "delete@example.com", "Delete Me")
    assert client.put("/api/me/saved/osm:n2", json={"data": {"name": "Museum"}}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json() == {"user": None}  # guests: 200 {user: null}
    assert client.post("/api/auth/login", json={"email": "DELETE@example.com", "password": "local test password 123"}).status_code == 200
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/me/saved").status_code == 401
    assert client.post("/api/auth/login", json={"email": "delete@example.com", "password": "local test password 123"}).status_code == 401
    with db.SessionLocal() as session:
        assert session.get(User, user["id"]) is None
        assert list(session.scalars(select(SavedPlace).where(SavedPlace.user_id == user["id"]))) == []


def test_password_reset_is_unavailable_without_smtp(client):
    response = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert response.status_code == 503
    assert response.json()["detail"] == "email_unavailable"
