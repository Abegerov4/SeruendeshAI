"""pipeline.corrections: concert halls are not karaoke, betting shops are not places to recommend."""
import json

from app.paths import PROCESSED_DIR
from app.store import apply_corrections, load_store
from pipeline import corrections


def test_decide_from_2gis_rubrics_then_names():
    karaoke = {"id": "ov:x", "name": "Extaz", "category": "karaoke"}
    assert corrections.decide(karaoke, {"name": "Extaz, караоке-бар", "category_names": ["Караоке-залы", "Бары"]}) is None
    hall = {"id": "ov:y", "name": "Kazakhstan Central Concert Hall", "category": "karaoke"}
    assert corrections.decide(hall, None)["category"] == "event_venue"
    assert corrections.decide({"id": "ov:z", "name": "Музыкальная Академия", "category": "karaoke"}, None)["exclude"]
    assert corrections.decide({"id": "osm:1", "name": "Спорт-бар \"Финал\", БК FairPlay.", "category": "bar"}, None)["exclude"]
    assert corrections.decide({"id": "ov:w", "name": "Revival", "category": "karaoke"}, None) is None  # no evidence: kept
    assert corrections.decide({"id": "osm:2", "name": "Пинта", "category": "bar"}, None) is None


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


def test_twogis_features_fill_unknowns_only():
    from app.store import apply_twogis

    pois = [{"id": "a", "name": "Кафе", "category": "cafe", "features": {"outdoor_seating": False}},
            {"id": "b", "name": "Бар", "category": "bar", "features": {"wheelchair": "yes"}, "cuisine": "georgian"}]
    layer = {"a": {"features": {"outdoor_seating": True, "laptop_friendly": True, "ramp": True}, "cuisine": ["Итальянская кухня"]},
             "b": {"features": {"ramp": True, "halal": True}, "cuisine": ["Японская кухня"]}}
    apply_twogis(pois, layer)
    a, b = pois
    assert a["features"]["outdoor_seating"] is False  # the map said no: 2GIS does not overrule it
    assert a["features"]["laptop_friendly"] is True and a["features"]["wheelchair"] == "limited"  # a ramp is partial
    assert a["cuisine"] == "italian"
    assert b["features"]["wheelchair"] == "yes" and b["features"]["halal"] is True and b["cuisine"] == "georgian"


def test_bookmaker_sports_bars_are_excluded_by_website():
    bar = {"id": "osm:3", "name": "Лигалайф", "category": "bar", "website": "https://www.fairplay.kz/"}
    assert corrections.decide(bar, None)["exclude"]
    cafe = {"id": "osm:4", "name": "Panda Lamian", "category": "cafe", "website": "https://www.fairplay.kz/"}
    assert corrections.decide(cafe, None) is None  # a café keeps its card; only the wrong link goes (link check)
