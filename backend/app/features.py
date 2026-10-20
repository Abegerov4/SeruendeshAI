"""POI amenities extracted from OSM tags, with RU/KK/EN labels.

Only facts present in the data are stored; a missing feature means "unknown",
never "no". This is what lets the API say "Wi-Fi: no data" instead of guessing.
"""
from __future__ import annotations

FEATURE_LABELS: dict[str, tuple[str, str, str]] = {
    "wifi": ("Wi-Fi", "Wi-Fi", "Wi-Fi"),
    "no_wifi": ("без Wi-Fi", "Wi-Fi жоқ", "no Wi-Fi"),
    "outdoor_seating": ("летняя веранда", "жазғы алаң", "outdoor seating"),
    "wheelchair": ("доступно для колясок", "арбамен кіруге болады", "wheelchair accessible"),
    "wheelchair_limited": ("частично доступно для колясок", "арбамен ішінара қолжетімді", "partly wheelchair accessible"),
    "lit": ("освещение вечером", "кешке жарықтандырылған", "lit at night"),
    "free": ("вход бесплатный", "кіру тегін", "free entry"),
    "paid": ("вход платный", "кіру ақылы", "paid entry"),
    "kids_area": ("детская зона", "балалар аймағы", "kids area"),
    "changing_table": ("пеленальный столик", "бала орау үстелі", "changing table"),
    "takeaway": ("кофе/еда с собой", "алып кетуге болады", "takeaway"),
    "vegetarian": ("есть вегетарианское", "вегетариандық тағам бар", "vegetarian options"),
    "no_smoking": ("без курения", "темекі шегуге болмайды", "no smoking"),
    "air_conditioning": ("кондиционер", "кондиционер", "air conditioning"),
    "open_24_7": ("круглосуточно", "тәулік бойы", "open 24/7"),
    "power_outlets": ("есть розетки", "розеткалар бар", "power outlets"),
    "indoor": ("в помещении", "жабық орында", "indoors"),
    "toilets": ("есть туалет", "дәретхана бар", "toilets"),
}

CUISINE_RU = {
    "coffee_shop": "кофе", "coffee": "кофе", "tea": "чай", "bubble_tea": "бабл-ти", "pizza": "пицца", "burger": "бургеры",
    "sushi": "суши", "japanese": "японская кухня", "kazakh": "казахская кухня", "regional": "местная кухня",
    "uzbek": "узбекская кухня", "georgian": "грузинская кухня", "turkish": "турецкая кухня", "italian": "итальянская кухня",
    "chinese": "китайская кухня", "korean": "корейская кухня", "asian": "азиатская кухня", "american": "американская кухня",
    "european": "европейская кухня", "russian": "русская кухня", "international": "международная кухня",
    "steak_house": "стейки", "dessert": "десерты", "cake": "торты", "ice_cream": "мороженое", "shawarma": "шаурма",
    "kebab": "кебаб", "doner": "донер", "chicken": "курица", "seafood": "морепродукты", "pancake": "блины",
    "breakfast": "завтраки", "bakery": "выпечка", "sandwich": "сэндвичи", "noodle": "лапша", "ramen": "рамен",
    "vegetarian": "вегетарианская", "fish": "рыба", "barbecue": "гриль", "lebanese": "ливанская кухня",
    "indian": "индийская кухня", "french": "французская кухня", "mexican": "мексиканская кухня",
    "middle_eastern": "ближневосточная кухня", "oriental": "восточная кухня", "caucasian": "кавказская кухня",
}


def features_from_osm(t: dict[str, str]) -> dict[str, bool | str]:
    f: dict[str, bool | str] = {}
    ia = t.get("internet_access", "")
    if ia in ("wlan", "yes", "wifi", "terminal;wlan"):
        f["wifi"] = True
    elif ia == "no":
        f["wifi"] = False
    if t.get("outdoor_seating") == "yes":
        f["outdoor_seating"] = True
    w = t.get("wheelchair")
    if w in ("yes", "designated"):
        f["wheelchair"] = "yes"
    elif w == "limited":
        f["wheelchair"] = "limited"
    elif w == "no":
        f["wheelchair"] = "no"
    if t.get("lit") == "yes":
        f["lit"] = True
    elif t.get("lit") == "no":
        f["lit"] = False
    if t.get("fee") == "no":
        f["free"] = True
    elif t.get("fee") == "yes":
        f["free"] = False
    if t.get("kids_area") == "yes" or t.get("playground") == "yes":
        f["kids_area"] = True
    if t.get("changing_table") == "yes":
        f["changing_table"] = True
    if t.get("takeaway") in ("yes", "only"):
        f["takeaway"] = True
    if t.get("diet:vegetarian") in ("yes", "only") or t.get("diet:vegan") in ("yes", "only"):
        f["vegetarian"] = True
    if t.get("smoking") in ("no", "outside"):
        f["no_smoking"] = True
    if t.get("air_conditioning") == "yes":
        f["air_conditioning"] = True
    if t.get("opening_hours", "").strip() == "24/7":
        f["open_24_7"] = True
    if t.get("power_supply") == "yes" or t.get("socket") == "yes" or t.get("charging_station") == "yes":
        f["power_outlets"] = True
    if t.get("indoor") == "yes" or t.get("location") == "indoor":
        f["indoor"] = True
    if t.get("toilets") == "yes":
        f["toilets"] = True
    return f


def feature_labels(features: dict, lang: str) -> list[str]:
    i = {"ru": 0, "kk": 1, "en": 2}.get(lang, 0)
    out = []
    for k, v in features.items():
        if v is True and k in FEATURE_LABELS:
            out.append(FEATURE_LABELS[k][i])
        elif k == "wifi" and v is False:
            out.append(FEATURE_LABELS["no_wifi"][i])
        elif k == "free" and v is False:
            out.append(FEATURE_LABELS["paid"][i])
        elif k == "wheelchair" and v == "yes":
            out.append(FEATURE_LABELS["wheelchair"][i])
        elif k == "wheelchair" and v == "limited":
            out.append(FEATURE_LABELS["wheelchair_limited"][i])
    return out


def cuisine_ru(cuisine: str | None) -> list[str]:
    if not cuisine:
        return []
    return [CUISINE_RU.get(c.strip(), c.strip().replace("_", " ")) for c in cuisine.split(";") if c.strip()][:4]


def cuisine_labels(cuisine: str | None, lang: str) -> list[str]:
    if lang != "en":
        return cuisine_ru(cuisine)
    return [c.strip().replace("_", " ") for c in (cuisine or "").split(";") if c.strip()][:4]


def describe(p: dict, lang: str) -> str | None:
    """Description in the reply language: source texts as they are, fact-based ones rebuilt per language."""
    if p.get("description_source") != "template" or lang == "ru":
        return p.get("description")
    from app.categories import label
    from app.i18n import t
    parts = [label(p["category"], lang)]
    if cz := cuisine_labels(p.get("cuisine"), lang):
        parts.append(t("desc_cuisine", lang, v=", ".join(cz)))
    if fl := feature_labels(p.get("features", {}), lang):
        parts.append(t("desc_features", lang, v=", ".join(fl)))
    if near := p.get("near"):
        parts.append(t("desc_near" if near["m"] < 80 else "desc_near_m", lang, name=near["name"], m=near["m"]))
    if p.get("address"):
        parts.append(t("desc_address", lang, v=p["address"]))
    return ". ".join(parts) + "."
