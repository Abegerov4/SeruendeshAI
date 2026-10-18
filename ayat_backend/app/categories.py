"""Category taxonomy shared by the data pipeline and the API.

Every POI gets exactly one category key. A category carries what ranking, safety
rules and the "what to do" templates need: group, indoor/outdoor, typical visit
time (min, typical), audience flags and RU/KK/EN labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    group: str
    indoor: bool | None  # None = depends / mixed
    visit: tuple[int, int]  # (minimum, typical) minutes on site
    labels: tuple[str, str, str]  # ru, kk, en
    icon: str
    kids: bool = False  # good for children by default
    adult_only: bool = False  # never for children
    night: bool = False  # a typical late-evening activity
    quiet: bool = False


_C = Category
CATEGORIES: dict[str, Category] = {c.key: c for c in [
    _C("museum", "culture", True, (40, 75), ("Музей", "Мұражай", "Museum"), "museum", kids=True),
    _C("gallery", "culture", True, (30, 45), ("Галерея", "Галерея", "Gallery"), "gallery", quiet=True),
    _C("theatre", "culture", True, (90, 120), ("Театр", "Театр", "Theatre"), "theatre"),
    _C("cinema", "entertainment", True, (100, 130), ("Кинотеатр", "Кинотеатр", "Cinema"), "cinema", night=True),
    _C("arts_centre", "culture", True, (30, 60), ("Арт-пространство", "Өнер кеңістігі", "Arts centre"), "palette"),
    _C("library", "quiet", True, (30, 60), ("Библиотека", "Кітапхана", "Library"), "book", quiet=True),
    _C("landmark", "sight", False, (15, 30), ("Достопримечательность", "Көрікті орын", "Landmark"), "landmark"),
    _C("monument", "sight", False, (5, 15), ("Памятник / мемориал", "Ескерткіш / мемориал", "Monument"), "monument"),
    _C("artwork", "sight", False, (5, 10), ("Арт-объект", "Арт-нысан", "Public art"), "sparkles"),
    _C("viewpoint", "sight", None, (10, 20), ("Смотровая площадка", "Көру алаңы", "Viewpoint"), "eye"),
    _C("worship", "sight", True, (20, 30), ("Мечеть / храм", "Мешіт / ғибадатхана", "Mosque / temple"), "worship", quiet=True),
    _C("park", "nature", False, (20, 45), ("Парк", "Саябақ", "Park"), "trees", kids=True),
    _C("garden", "nature", False, (15, 30), ("Сквер / сад", "Гүлзар / бақ", "Garden / square"), "flower", quiet=True),
    _C("playground", "kids", False, (20, 40), ("Детская площадка", "Балалар алаңы", "Playground"), "baby", kids=True),
    _C("kids_indoor", "kids", True, (45, 75), ("Детский игровой центр", "Балалар ойын орталығы", "Indoor play centre"), "baby", kids=True),
    _C("zoo_aquarium", "kids", True, (45, 75), ("Океанариум / зоопарк", "Океанариум / хайуанаттар бағы", "Aquarium / zoo"), "fish", kids=True),
    _C("water_park", "kids", True, (90, 150), ("Аквапарк", "Аквапарк", "Water park"), "waves", kids=True),
    _C("theme_park", "kids", False, (60, 120), ("Парк аттракционов", "Аттракциондар саябағы", "Amusement park"), "ferris", kids=True),
    _C("mall", "shopping", True, (30, 60), ("Торговый центр", "Сауда орталығы", "Mall"), "shopping", kids=True),
    _C("market", "shopping", None, (30, 45), ("Рынок / базар", "Базар", "Market"), "store"),
    _C("souvenir", "shopping", True, (15, 25), ("Сувениры / книги", "Кәдесыйлар / кітаптар", "Souvenirs / books"), "gift"),
    _C("cafe", "food", True, (25, 45), ("Кофейня / кафе", "Кофехана / кафе", "Café"), "coffee"),
    _C("restaurant", "food", True, (45, 75), ("Ресторан", "Мейрамхана", "Restaurant"), "utensils"),
    _C("fast_food", "food", True, (15, 25), ("Фастфуд", "Фастфуд", "Fast food"), "burger"),
    _C("sweets", "food", True, (15, 25), ("Кондитерская / мороженое", "Кондитерлік / балмұздақ", "Bakery / ice cream"), "cake", kids=True),
    _C("bar", "night", True, (45, 75), ("Бар / паб", "Бар / паб", "Bar / pub"), "beer", adult_only=True, night=True),
    _C("nightclub", "night", True, (60, 120), ("Ночной клуб", "Түнгі клуб", "Nightclub"), "music", adult_only=True, night=True),
    _C("karaoke", "night", True, (60, 90), ("Караоке", "Караоке", "Karaoke"), "mic", night=True),
    _C("hookah", "night", True, (60, 90), ("Кальянная", "Кальянхана", "Hookah lounge"), "cloud", adult_only=True, night=True),
    _C("active", "active", True, (45, 90), ("Активный отдых", "Белсенді демалыс", "Activities & sport"), "activity", kids=True),
    _C("spa", "relax", True, (60, 120), ("Баня / спа", "Монша / спа", "Sauna / spa"), "spa"),
    _C("coworking", "work", True, (60, 120), ("Коворкинг", "Коворкинг", "Coworking"), "laptop", quiet=True),
    _C("event_venue", "culture", True, (60, 120), ("Площадка мероприятий", "Іс-шара алаңы", "Event venue"), "ticket"),
]}

GROUP_OF = {k: c.group for k, c in CATEGORIES.items()}


def label(key: str, lang: str) -> str:
    c = CATEGORIES.get(key)
    if not c:
        return key
    return c.labels[{"ru": 0, "kk": 1, "en": 2}.get(lang, 0)]


# --- OSM tags -> category -------------------------------------------------------------

_AMENITY = {
    "cafe": "cafe", "restaurant": "restaurant", "fast_food": "fast_food", "food_court": "fast_food",
    "ice_cream": "sweets", "bar": "bar", "pub": "bar", "biergarten": "bar", "nightclub": "nightclub",
    "karaoke_box": "karaoke", "hookah_lounge": "hookah", "theatre": "theatre", "cinema": "cinema",
    "arts_centre": "arts_centre", "library": "library", "planetarium": "museum",
    "marketplace": "market", "place_of_worship": "worship", "coworking_space": "coworking",
    "internet_cafe": "coworking", "events_venue": "event_venue", "exhibition_centre": "event_venue",
    "concert_hall": "theatre", "music_venue": "event_venue", "community_centre": "event_venue",
    "public_bath": "spa",
}
_TOURISM = {
    "museum": "museum", "gallery": "gallery", "attraction": "landmark", "viewpoint": "viewpoint",
    "artwork": "artwork", "zoo": "zoo_aquarium", "aquarium": "zoo_aquarium", "theme_park": "theme_park",
}
_LEISURE = {
    "park": "park", "garden": "garden", "playground": "playground", "water_park": "water_park",
    "amusement_arcade": "kids_indoor", "indoor_play": "kids_indoor", "trampoline_park": "kids_indoor",
    "ice_rink": "active", "bowling_alley": "active", "escape_game": "active", "swimming_pool": "active",
    "sports_centre": "active", "miniature_golf": "active", "sauna": "spa", "dance": "active",
}
_SHOP = {
    "mall": "mall", "department_store": "mall", "books": "souvenir", "gift": "souvenir",
    "souvenir": "souvenir", "art": "souvenir", "bakery": "sweets", "confectionery": "sweets",
    "chocolate": "sweets", "coffee": "cafe", "tea": "cafe",
}
_HISTORIC_MONUMENT = {"monument", "memorial", "statue", "wayside_cross", "milestone"}
# things we deliberately do not recommend as destinations
SKIP_LEISURE = {"pitch", "track", "fitness_station", "fitness_centre", "stadium", "sports_hall", "dog_park"}
SKIP_AMENITY = {"toilets", "bicycle_rental", "boat_rental", "childcare", "fountain", "studio", "casino",
                "social_centre", "public_bookcase", "conference_centre"}


def category_from_osm(t: dict[str, str]) -> str | None:
    """Map an OSM tag dict to one category key, or None if it is not a destination."""
    a, tr, le, sh, hi = t.get("amenity"), t.get("tourism"), t.get("leisure"), t.get("shop"), t.get("historic")
    if any(k.startswith(p) for k in t for p in ("disused:", "abandoned:", "was:", "demolished:", "razed:")) and not (a or tr or le or sh):
        return None
    if t.get("opening_hours", "").strip().lower() == "closed":
        return None
    if tr == "attraction" and (t.get("indoor") or t.get("level")):
        return None  # exhibits mapped inside a building (e.g. a museum hall), not a destination
    if tr in _TOURISM:
        return _TOURISM[tr]
    if a == "cafe" and t.get("cuisine", "").startswith(("ice_cream", "dessert")):
        return "sweets"
    if a == "bar" and "hookah" in t.get("bar", "") + t.get("cuisine", ""):
        return "hookah"
    if a in _AMENITY:
        return _AMENITY[a]
    if a in SKIP_AMENITY:
        return None
    if le in _LEISURE:
        return _LEISURE[le]
    if le in SKIP_LEISURE:
        return None
    if sh in _SHOP:
        return _SHOP[sh]
    if t.get("man_made") in ("tower", "observatory") and t.get("name"):
        return "landmark"  # e.g. Baiterek: monument AND observation tower -> landmark (longer visit)
    if hi:
        if t.get("building") not in (None, "no") and int(re.sub(r"\D", "", t.get("building:levels", "0")) or 0) >= 3:
            return "landmark"  # e.g. Baiterek: a monument you can go up -> landmark visit times
        return "monument" if hi in _HISTORIC_MONUMENT else "landmark"
    if t.get("man_made") == "obelisk" and t.get("name"):
        return "monument"
    if t.get("office") == "coworking":
        return "coworking"
    if t.get("attraction"):
        return "theme_park" if t["attraction"] in ("amusement_ride", "carousel", "roller_coaster", "big_wheel") else "landmark"
    b = t.get("building")
    if b in ("mosque", "cathedral", "church", "synagogue", "temple"):
        return "worship"
    if b == "museum":
        return "museum"
    if b == "theatre":
        return "theatre"
    return None


# team contract (README §3.1) has a coarser 18-value enum; our 33 keys map onto it
CONTRACT_CATEGORY = {
    "museum": "museum", "gallery": "gallery", "arts_centre": "gallery", "theatre": "theatre", "cinema": "cinema",
    "library": "library", "landmark": "attraction", "monument": "monument", "artwork": "monument",
    "viewpoint": "viewpoint", "worship": "attraction", "park": "park", "garden": "park", "playground": "playground",
    "kids_indoor": "attraction", "zoo_aquarium": "attraction", "water_park": "sport", "theme_park": "attraction",
    "mall": "mall", "market": "other", "souvenir": "other", "cafe": "cafe", "restaurant": "restaurant",
    "fast_food": "restaurant", "sweets": "cafe", "bar": "bar", "nightclub": "nightlife", "karaoke": "nightlife",
    "hookah": "nightlife", "active": "sport", "spa": "other", "coworking": "coworking", "event_venue": "attraction",
}
