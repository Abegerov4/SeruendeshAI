"""Extract attributable internet facts without guessing venue amenities."""
from __future__ import annotations

from urllib.parse import urlsplit


def extract_source_amenities(raw: dict) -> tuple[list[dict], list[str]]:
    """Return source facts before merging records and only supported search tags.

    Unknown nonempty strings remain uninterpreted facts. An access fee does not
    establish access, and a generic ``yes`` does not establish Wi-Fi.
    """
    source_id, source_url = raw.get("id"), raw.get("source_url")
    if not isinstance(source_id, str) or not source_id.strip():
        return [], []
    if not isinstance(source_url, str) or any(c.isspace() for c in source_url):
        return [], []
    try:
        parsed = urlsplit(source_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return [], []
    except ValueError:
        return [], []
    raw_tags = raw.get("raw_tags")
    if not isinstance(raw_tags, dict):
        return [], []
    provenance = {
        "source_id": source_id,
        "source_url": source_url,
        "collected_at": raw.get("collected_at"),
        "source_updated_at": raw.get("source_updated_at"),
    }
    facts = []
    for field in ("internet_access", "internet_access:fee"):
        value = raw_tags.get(field)
        if isinstance(value, str) and value.strip():
            facts.append({"field": field, "value": value, **provenance})
    access = raw_tags.get("internet_access")
    if access == "wlan":
        return facts, ["Wi-Fi", "internet_access=wlan", "интернет"]
    if access == "yes":
        return facts, ["internet_access=yes", "интернет"]
    return facts, []
