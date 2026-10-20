"""How people in Astana actually name the landmarks: «я у меги», «возле шатра», «у шара на экспо».

The curated landmarks (pipeline.landmarks) carry the official spellings; these are the colloquial ones, with the
case forms of short names spelled out (a short key only takes a short ending, so «мега» never matches «мегафон»).
`apply` adds them to the gazetteer at load time, so a new nickname does not need a data rebuild. A landmark that
is not in the built gazetteer yet («старая Мега») is placed on the catalogue place with that exact name.
"""
from __future__ import annotations

from app.textnorm import fold

COLLOQUIAL: dict[str, list[str]] = {
    "mega_silk_way": ["мега", "меги", "меге", "мегу", "мегой", "мега силк вей", "мега силквей", "мега силкуэй",
                      "мегасилк", "мега силк уей", "силк вей", "silk way", "mega", "мега на левом берегу", "новая мега"],
    "mega_center": ["мега центр", "мега центр астана", "мега центра", "мега центре", "старая мега", "старой меге",
                    "старой меги", "mega center", "mega astana"],
    "khan_shatyr": ["ханшатыр", "хан шатыре", "хан шатыра", "шатыр", "шатыра", "шатыре", "шатер", "шатёр", "шатра",
                    "шатре", "шатром", "khanshatyr", "хан-шатыре"],
    "baiterek": ["байтерик", "байтереке", "байтерека", "байтереком", "baytereк"],
    "expo": ["экспо 2017", "expo2017", "территория экспо", "на экспо", "у экспо"],
    "nur_alem": ["шара", "шаре", "шаром", "шар экспо", "шара экспо", "нуралем", "нур-алем", "сфера", "сферы",
                 "сфере", "нур алеме"],
    "nurly_zhol": ["вокзал", "вокзала", "вокзале", "новый вокзал", "нового вокзала", "нурлыжол", "жд вокзал"],
    "astana_1": ["старого вокзала", "старом вокзале"],
    "airport": ["аэропорт нурсултан", "аэропорта", "аэропорте"],
    "hazret_sultan": ["хазрет", "мечеть хазрет", "мечети хазрет султан", "хазрет-султан"],
    "astana_opera": ["опера", "оперы", "опере", "оперу", "оперный", "оперный театр", "оперного театра", "оперном театре"],
    "central_park": ["центральном парке", "центрального парка", "центральному парку", "центральным парком", "центр парк"],
    "presidential_park": ["президентском парке", "президентского парка", "президентскому парку"],
    "national_museum": ["нацмузей", "нац музей", "национальном музее", "национального музея", "национальному музею"],
    "keruen": ["керуен сити", "керуене", "керуена", "keruen city"],
    "abu_dhabi_plaza": ["абу даби", "абудаби", "абу-даби плаза", "абу даби плазе", "абу даби плазы", "abu dhabi"],
    "nurzhol": ["водно-зеленый бульвар", "водно-зелёный бульвар", "водно зеленый бульвар", "водно-зеленом бульваре",
                "нуржол бульвар", "бульвар нуржол"],
    "kazakh_eli": ["казак ели", "стела", "стелы", "стеле", "монумент казак ели"],
    "duman": ["океанариум", "океанариума", "океанариуме", "думане", "думана"],
    "barys_arena": ["барыс", "барыс арене", "барыс арены"],
    "astana_arena": ["астана арене", "астана арены"],
    "nazarbayev_university": ["университет назарбаева", "назарбаев университете", "ну назарбаев"],
    "pyramid": ["пирамиде", "пирамиды", "пирамиду"],
    "asia_park": ["азия парк", "азия парке", "азия парка", "asia park"],
}

# landmarks the build does not know yet: name, the catalogue name to stand on, the preferred category
NEW_LANDMARKS: dict[str, tuple[str, list[str], str]] = {
    "mega_center": ("ТРЦ «Мега Центр Астана»", ["мега центр астана", "трц \"мега центр астана\"", "mega astana"], "mall"),
    "asia_park": ("ТРЦ «Азия Парк»", ["asia park", "азия парк"], "mall"),
}


def apply(gazetteer: list[dict]) -> int:
    """Add the colloquial keys to the curated entries (and place the new landmarks); returns keys added."""
    added = 0
    by_key = {g.get("landmark_key"): g for g in gazetteer if g.get("kind") == "landmark"}
    for key, (label, names, category) in NEW_LANDMARKS.items():
        if key in by_key:
            continue
        wanted = {fold(n) for n in names}
        spot = next((g for g in gazetteer if g.get("kind") == "poi" and g.get("category") == category
                     and wanted & set(g.get("keys") or [])), None)
        if spot:
            entry = {"name": label, "lat": spot["lat"], "lon": spot["lon"], "kind": "landmark", "landmark_key": key,
                     "keys": sorted(wanted)}
            gazetteer.append(entry)
            by_key[key] = entry
    for key, names in COLLOQUIAL.items():
        g = by_key.get(key)
        if not g:
            continue
        keys = set(g.get("keys") or [])
        new = {fold(n) for n in names} - keys
        g["keys"] = sorted(keys | new)
        added += len(new)
    return added
