"""pipeline.corrections: concert halls are not karaoke, betting shops are not places to recommend."""
import json

from app.paths import PROCESSED_DIR
from app.store import apply_corrections, load_store
from pipeline import corrections


def test_decide_by_name():
    assert corrections.decide({"id": "ov:x", "name": "Караоке ROYAL", "category": "karaoke"}) is None
    hall = {"id": "ov:y", "name": "Kazakhstan Central Concert Hall", "category": "karaoke"}
    assert corrections.decide(hall)["category"] == "event_venue"
    assert corrections.decide({"id": "ov:z", "name": "Музыкальная Академия", "category": "karaoke"})["exclude"]
    assert corrections.decide({"id": "osm:1", "name": "Спорт-бар \"Финал\", БК FairPlay.", "category": "bar"})["exclude"]
    assert corrections.decide({"id": "ov:w", "name": "Revival", "category": "karaoke"}) is None  # no evidence: kept
    assert corrections.decide({"id": "osm:2", "name": "Пинта", "category": "bar"}) is None


def test_apply_flags_exclusions_and_fixes_categories_in_place():
    pois = [{"id": "a", "name": "Органный зал", "category": "karaoke"}, {"id": "b", "name": "БК", "category": "bar"},
            {"id": "c", "name": "Kinopark", "category": "cinema", "names": {"ru": "Сарыарка", "en": "Kinopark"}}]
    apply_corrections(pois, {"a": {"category": "event_venue"}, "b": {"exclude": "betting"},
                             "c": {"names": {"ru": "Kinopark 8 IMAX Сарыарка"}}})
    assert len(pois) == 3  # rows stay (embeddings are aligned by row); the loader drops the flagged one
    assert pois[0]["category"] == "event_venue" and pois[1]["excluded"] == "betting"
    assert pois[2]["names"] == {"ru": "Kinopark 8 IMAX Сарыарка", "en": "Kinopark"}


def test_served_catalogue_has_no_betting_shops_or_concert_halls_as_karaoke():
    if not (PROCESSED_DIR / "place_corrections.json").exists():
        return
    st = load_store("off")
    names = {p["id"]: p for p in st.pois}
    assert not any(corrections.BETTING.search(p["name"]) for p in st.pois)
    fixes = json.loads((PROCESSED_DIR / "place_corrections.json").read_text())
    for pid, fix in fixes.items():
        if fix.get("exclude"):
            assert pid not in names
        elif fix.get("category"):
            assert names[pid]["category"] == fix["category"]



def test_bookmaker_sports_bars_are_excluded_by_website():
    bar = {"id": "osm:3", "name": "Лигалайф", "category": "bar", "website": "https://www.fairplay.kz/"}
    assert corrections.decide(bar)["exclude"]
    cafe = {"id": "osm:4", "name": "Panda Lamian", "category": "cafe", "website": "https://www.fairplay.kz/"}
    assert corrections.decide(cafe) is None  # a café keeps its card; only the wrong link goes (link check)
