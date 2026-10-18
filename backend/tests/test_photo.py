import base64
import io

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import vision
from backend.app.main import app

client = TestClient(app)


def _jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (2000, 1500), (90, 140, 200))
    exif = Image.Exif()
    exif[0x8825] = {2: (51.0, 7.0, 42.0)}  # GPSInfo — должен исчезнуть
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_prepare_image_strips_exif_and_downscales():
    url = vision.prepare_image(_jpeg_with_exif(), "image/jpeg")
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(img.size) <= vision.MAX_SIDE
    assert not img.getexif()


def test_photo_rejects_non_image():
    r = client.post("/api/recommend/photo", files={"image": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_photo_without_llm_asks_for_landmark():
    r = client.post("/api/recommend/photo", files={"image": ("p.jpg", _jpeg_with_exif(), "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["recommendations"] == [] and "фото" in r.json()["notes"][0]


def test_photo_recognized_landmark_drives_recommendations(monkeypatch):
    monkeypatch.setattr(vision, "identify_landmark",
                        lambda *_: vision.PhotoGuess(landmark="Байтерек", confidence="high", seen="башня"))
    r = client.post("/api/recommend/photo", files={"image": ("p.jpg", _jpeg_with_exif(), "image/jpeg")},
                    data={"query": "куда пойти на час", "now": "2026-10-18T15:00:00+05:00"})
    data = r.json()
    assert data["used_context"]["location_label"].endswith("(по фото)")
    assert data["recommendations"] and all(x["poi_id"] != "fixture:bayterek" for x in data["recommendations"])
    assert data["notes"][0].startswith("По фото")


def test_low_confidence_is_not_trusted():
    assert vision.resolve(vision.PhotoGuess(landmark="Байтерек", confidence="low")) is None
