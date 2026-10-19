"""Live S3 smoke check. Run only against a disposable test stack/bucket.

Run `seed`, restart storage, then run `verify` with the same manifest volume.
The check writes a card reference and public/private probe objects.
"""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

sys.path.insert(0, "/tools")
sys.path.insert(0, "/app")
import manage
from card_photos import apply_card_photos


def denied(url, method="GET", data=None):
    try:
        with urlopen(Request(url, data=data, method=method), timeout=15) as response:
            raise AssertionError(f"Anonymous {method} unexpectedly succeeded: {response.status}")
    except HTTPError as exc:
        assert exc.code == 403, f"Expected 403, got {exc.code} for {method}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["seed", "verify"])
    args = parser.parse_args()
    s3 = manage.client()
    manage.wait_ready(s3)
    bucket = os.environ["S3_BUCKET"]
    manifest = Path(os.environ["CARD_PHOTOS_FILE"])
    base = os.environ["S3_ENDPOINT_URL"].rstrip("/") + "/" + bucket
    if args.phase == "seed":
        # Repeated initialization must preserve existing data and permissions.
        manage.initialize(s3, bucket)
        image = Path("/tmp/photo-smoke.jpg")
        exif = Image.Exif()
        exif[270] = "private test metadata"
        Image.new("RGB", (2400, 1200), (50, 120, 180)).save(image, exif=exif)
        upload = SimpleNamespace(file=str(image), poi_id="smoke-test", author="Test",
                                 license="CC0", source="Integration test", page=None)
        first = manage.publish(s3, bucket, upload, manifest)
        assert manage.publish(s3, bucket, upload, manifest) == first
        s3.put_object(Bucket=bucket, Key="private/probe.txt", Body=b"private")
        manage.initialize(s3, bucket)

    os.environ["S3_PUBLIC_BASE_URL"] = base
    pois = [{"id": "smoke-test"}, {"id": "unchanged", "photo": {"url": "original"}}]
    apply_card_photos(pois)
    assert pois[1]["photo"]["url"] == "original"
    photo = pois[0]["photo"]
    assert photo["author"] == "Test" and photo["license"] == "CC0"
    with urlopen(photo["url"], timeout=15) as response:
        assert response.headers["Content-Type"] == "image/jpeg"
        assert "immutable" in response.headers["Cache-Control"]
        decoded = Image.open(BytesIO(response.read()))
        assert decoded.size == (1920, 960)
        assert not decoded.getexif()
    denied(base + "?list-type=2")
    denied(base + "/private/probe.txt")
    denied(base + "/cards/anonymous.jpg", "PUT", b"unauthorized")
    denied(photo["url"], "DELETE")
    entries = json.loads(manifest.read_text())
    assert s3.get_object(Bucket=bucket, Key=entries["smoke-test"]["key"])["ContentLength"] > 0
    print(f"PASS {args.phase}: upload, card overlay, public JPEG, metadata, access policy and persistence")


if __name__ == "__main__":
    main()
