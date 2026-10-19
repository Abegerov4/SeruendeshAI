"""Optional operator-managed card photo overlay, separate from source snapshots."""
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit


def apply_card_photos(pois: list[dict]) -> None:
    filename = os.getenv("CARD_PHOTOS_FILE")
    if not filename:
        return
    path = Path(filename)
    if not path.exists():
        return
    base = os.environ.get("S3_PUBLIC_BASE_URL", "").rstrip("/")
    if urlsplit(base).scheme not in {"http", "https"} or not urlsplit(base).netloc:
        raise ValueError("S3_PUBLIC_BASE_URL must be an absolute public HTTP(S) bucket URL")
    photos = json.loads(path.read_text(encoding="utf-8"))
    for poi in pois:
        if entry := photos.get(poi["id"]):
            photo = dict(entry)
            key = photo.pop("key")
            if not key.startswith("cards/") or ".." in key.split("/"):
                raise ValueError("Card photo key must be inside cards/")
            photo["url"] = f"{base}/{quote(key, safe='/')}"
            poi["photo"] = photo
