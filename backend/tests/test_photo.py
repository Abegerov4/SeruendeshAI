"""Photo mode: input validation, privacy (EXIF), no-LLM 503 and the recognised / unrecognised flows (LLM faked)."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main, photo
from app.main import app
from app.schemas import PhotoRecommendResponse

URL = "/api/recommend/photo"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def jpeg(w=1600, h=1200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 140, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_invalid_type_is_rejected(client):
    r = client.post(URL, files={"image": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415 and r.json() == {"error": "unsupported_media_type"}
    assert client.post(URL, data={"query": "кофе"}).status_code in (415, 422)  # no file at all
    assert client.post(URL, json={"query": "кофе"}).status_code == 415  # not multipart


def test_too_large_is_rejected(client):
    big = b"\xff\xd8" + b"0" * (photo.MAX_BYTES + 10)
    r = client.post(URL, files={"image": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413 and r.json() == {"error": "photo_too_large"}


def test_no_llm_returns_503(client):
    r = client.post(URL, files={"image": ("p.jpg", jpeg(), "image/jpeg")}, data={"query": "кофе рядом", "lang": "ru"})
    assert r.status_code == 503 and r.json() == {"error": "photo_unavailable"}


def test_bad_lang_and_broken_image(client, monkeypatch):
    assert client.post(URL, files={"image": ("p.jpg", jpeg(), "image/jpeg")}, data={"lang": "de"}).status_code == 422
    monkeypatch.setattr(main, "llm_client", lambda: object())
    r = client.post(URL, files={"image": ("p.jpg", b"\xff\xd8garbage", "image/jpeg")})
    assert r.status_code == 422 and r.json() == {"error": "invalid_image"}


def fake_guess(place_id, confidence, seen=None):
    async def guess(jpeg_bytes, places, lang):
        if seen is not None:
            seen.update(size=Image.open(io.BytesIO(jpeg_bytes)).size, places=places)
        return photo.PhotoGuessLLM(place_id=place_id, confidence=confidence, description="Высокая башня"), "fake", None
    return guess


def test_recognised_photo_runs_the_normal_flow(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "llm_client", lambda: object())
    monkeypatch.setattr(photo, "guess_place", fake_guess("baiterek", "high", seen))
    r = client.post(URL, files={"image": ("p.jpg", jpeg(), "image/jpeg")},
                    data={"query": "Хочу кофе", "lang": "ru"})
    assert r.status_code == 200, r.text
    d = PhotoRecommendResponse.model_validate(r.json()).model_dump()
    assert d["photo_guess"] == {"recognized": True, "place_id": "baiterek", "kind": "landmark", "name": "Байтерек",
                                "confidence": "high", "description": "Высокая башня", "probability": None}
    assert d["recommendations"] and d["used_context"]["location_label"].startswith("Байтерек")
    assert "Байтерек" in d["notes"][0] and any("EXIF" in n for n in d["notes"])
    assert max(seen["size"]) == 1024  # the LLM only ever sees the downscaled, re-encoded copy
    # 29 curated landmarks (27 built + «Мега Центр», «Азия Парк» from app.aliases) and at most 40 places nearby
    assert 29 <= len(seen["places"]) <= 29 + 40 and "baiterek" in seen["places"]
    assert any(p["kind"] == "poi" for p in seen["places"].values())


def test_unrecognised_photo_asks_for_a_landmark(client, monkeypatch):
    monkeypatch.setattr(main, "llm_client", lambda: object())
    monkeypatch.setattr(photo, "guess_place", fake_guess("baiterek", "low"))
    r = client.post(URL, files={"image": ("p.png", jpeg(), "image/jpeg")}, data={"lang": "en"})
    assert r.status_code == 200
    d = r.json()
    assert d["recommendations"] == [] and d["photo_guess"]["recognized"] is False
    assert "landmark" in d["summary"] and d["lang"] == "en"
    # a fallback landmark from the form is used when the photo is not recognised
    monkeypatch.setattr(photo, "guess_place", fake_guess(None, "low"))
    r = client.post(URL, files={"image": ("p.jpg", jpeg(), "image/jpeg")}, data={"landmark": "khan_shatyr", "query": "кофе"})
    d = r.json()
    assert r.status_code == 200 and d["recommendations"] and d["photo_guess"]["place_id"] is None
