import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.card_photos import apply_card_photos


def test_overlay_preserves_fallback_and_attribution(tmp_path, monkeypatch):
    path = tmp_path / "photos.json"
    path.write_text(json.dumps({"p1": {"key": "cards/photo.jpg", "author": "Alice",
                                       "license": "CC BY 4.0", "page": "https://source.test"}}))
    monkeypatch.setenv("CARD_PHOTOS_FILE", str(path))
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://photos.test/place-photos/")
    pois = [{"id": "p1", "photo": {"url": "old"}}, {"id": "p2", "photo": {"url": "fallback"}}]
    apply_card_photos(pois)
    assert pois[0]["photo"]["url"] == "https://photos.test/place-photos/cards/photo.jpg"
    assert pois[0]["photo"]["author"] == "Alice"
    assert pois[0]["photo"]["page"] == "https://source.test"
    assert "key" not in pois[0]["photo"]
    assert pois[1]["photo"]["url"] == "fallback"


def test_disabled_overlay(monkeypatch):
    monkeypatch.delenv("CARD_PHOTOS_FILE", raising=False)
    pois = [{"id": "p1"}]
    apply_card_photos(pois)
    assert pois == [{"id": "p1"}]


@pytest.fixture
def manager():
    file = Path(__file__).resolve().parents[1] / "manage.py"
    spec = importlib.util.spec_from_file_location("photo_manager", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_image_validation_and_metadata_stripping(manager, tmp_path):
    from PIL import Image
    file = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[270] = "private metadata"
    Image.new("RGB", (2400, 1200)).save(file, exif=exif)
    payload, width, height = manager.prepare_image(file)
    assert (width, height) == (1920, 960)
    assert not Image.open(manager.BytesIO(payload)).getexif()
    file.write_bytes(b"not an image")
    with pytest.raises(Exception):
        manager.prepare_image(file)
    file.write_bytes(b"x" * (manager.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="12 MiB"):
        manager.prepare_image(file)


def test_upload_failure_preserves_manifest(manager, tmp_path, monkeypatch):
    manifest = tmp_path / "photos.json"
    manifest.write_text('{"existing": {"key": "cards/old.jpg"}}')
    original = manifest.read_bytes()
    monkeypatch.setattr(manager, "prepare_image", lambda path: (b"image", 10, 20))
    monkeypatch.setattr(manager, "locked_manifest", lambda path: nullcontext())
    s3 = Mock()
    s3.put_object.side_effect = RuntimeError("unavailable")
    args = SimpleNamespace(file="photo.jpg", poi_id="new", author="Alice", license="CC0", source="Team", page=None)
    with pytest.raises(RuntimeError):
        manager.publish(s3, "photos", args, manifest)
    assert manifest.read_bytes() == original
    s3.put_object.side_effect = None
    key = manager.publish(s3, "photos", args, manifest)
    entries = json.loads(manifest.read_text())
    assert entries["existing"]["key"] == "cards/old.jpg"
    assert entries["new"]["key"] == key
    assert s3.put_object.call_args.kwargs["ContentType"] == "image/jpeg"


def test_init_only_creates_missing_bucket_and_scopes_policy(manager):
    pytest.importorskip("botocore", reason="Install infra/photos/requirements.txt for S3 tooling tests")
    from botocore.exceptions import ClientError
    s3 = Mock()
    s3.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
    manager.initialize(s3, "photos")
    s3.create_bucket.assert_called_once_with(Bucket="photos")
    policy = json.loads(s3.put_bucket_policy.call_args.kwargs["Policy"])
    assert policy["Statement"][0]["Action"] == ["s3:GetObject"]
    assert policy["Statement"][0]["Resource"] == ["arn:aws:s3:::photos/cards/*"]
    s3.reset_mock()
    s3.head_bucket.side_effect = None
    manager.initialize(s3, "photos")
    s3.create_bucket.assert_not_called()
    s3.head_bucket.side_effect = ClientError({"Error": {"Code": "403"}}, "HeadBucket")
    with pytest.raises(ClientError):
        manager.initialize(s3, "photos")
