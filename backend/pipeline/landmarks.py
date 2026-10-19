"""Hand-curated aliases for well-known Astana landmarks (RU/KK/EN spellings).

Coordinates are resolved from the collected data at build time; `fallback` is used only
for a couple of anchors whose position is certain, in case OSM naming changes.
"""

LANDMARKS: list[dict] = [
    {"key": "baiterek", "label": "Байтерек", "aliases": ["байтерек", "бәйтерек", "baiterek", "bayterek"], "fallback": (51.12828, 71.43050)},
    {"key": "khan_shatyr", "label": "Хан Шатыр", "aliases": ["хан шатыр", "khan shatyr", "хан-шатыр"], "fallback": (51.13250, 71.40370)},
    {"key": "mega_silk_way", "label": "Mega Silk Way", "aliases": ["mega silk way", "мега силк вэй", "мега силк уэй", "мега силк", "mega silkway"]},
    {"key": "expo", "label": "EXPO", "aliases": ["экспо", "expo", "экспо-2017", "expo 2017"], "prefer": "-", "prefer_cats": ("event_venue", "landmark", "museum")},
    {"key": "nur_alem", "label": "Нур Алем (сфера EXPO)", "aliases": ["нур алем", "нұр әлем", "nur alem", "сфера экспо", "музей будущей энергии"], "prefer": "-", "prefer_cats": ("museum", "landmark"), "fallback": (51.08930, 71.41590)},
    {"key": "airport", "label": "Аэропорт Астаны (NQZ)", "aliases": ["аэропорт", "әуежай", "airport", "nqz", "аэропорту"], "fallback": (51.02220, 71.46690), "kind": "airport"},
    {"key": "nurly_zhol", "label": "Вокзал Нурлы Жол", "aliases": ["нурлы жол", "нұрлы жол", "nurly zhol"], "prefer": "station"},
    {"key": "astana_1", "label": "Вокзал Астана-1", "aliases": ["астана-1", "астана 1", "старый вокзал", "astana-1", "вокзал астана", "astana train station", "астана (станция)"], "prefer": "station"},
    {"key": "pyramid", "label": "Дворец мира и согласия", "aliases": ["дворец мира и согласия", "пирамида", "бейбітшілік және келісім сарайы", "palace of peace"]},
    {"key": "hazret_sultan", "label": "Мечеть Хазрет Султан", "aliases": ["хазрет султан", "әзірет сұлтан", "hazrat sultan", "hazret sultan"]},
    {"key": "astana_opera", "label": "Астана Опера", "aliases": ["астана опера", "astana opera", "театр оперы и балета"]},
    {"key": "ak_orda", "label": "Акорда", "aliases": ["акорда", "ак орда", "ақорда", "akorda"], "prefer": "government", "prefer_cats": ("landmark",)},
    {"key": "central_park", "label": "Центральный парк", "aliases": ["центральный парк", "орталық саябақ", "central park"]},
    {"key": "presidential_park", "label": "Президентский парк", "aliases": ["президентский парк", "президенттік саябақ", "presidential park"]},
    {"key": "botanical_garden", "label": "Ботанический сад", "aliases": ["ботанический сад", "ботаникалық бақ", "botanical garden", "ботсад", "бот сад", "ботанический", "ботаникалық", "ботанического сада", "ботаническом саду", "ботаническому саду", "ботсаду", "ботсада"]},
    {"key": "national_museum", "label": "Национальный музей РК", "aliases": ["национальный музей", "ұлттық музей", "national museum"]},
    {"key": "keruen", "label": "ТРЦ Керуен", "aliases": ["керуен", "keruen"]},
    {"key": "abu_dhabi_plaza", "label": "Abu Dhabi Plaza", "aliases": ["абу даби плаза", "abu dhabi plaza", "абу-даби"]},
    {"key": "aitu", "label": "Astana IT University (AITU)", "aliases": ["aitu", "айту", "astana it university", "астана ит университет", "ит университет", "it university", "astana it"], "prefer": "university", "fallback": (51.09086, 71.41842)},
    {"key": "nazarbayev_university", "label": "Назарбаев Университет", "aliases": ["назарбаев университет", "nazarbayev university", "назарбаев университеті"], "prefer": "university"},
    {"key": "barys_arena", "label": "Барыс Арена", "aliases": ["барыс арена", "barys arena"], "prefer": "stadium", "prefer_cats": ("active",)},
    {"key": "astana_arena", "label": "Астана Арена", "aliases": ["астана арена", "astana arena"], "prefer": "stadium"},
    {"key": "nurzhol", "label": "Бульвар Нуржол", "aliases": ["нуржол", "нұржол", "nurzhol", "нұржол желек жолы"], "prefer": "boulevard", "prefer_cats": ("garden", "park"),
     "fallback": (51.12828, 71.43050)},  # Baiterek stands in the middle of the boulevard
    {"key": "triathlon_park", "label": "Триатлон парк", "aliases": ["триатлон парк", "triathlon park"]},
    {"key": "kazakh_eli", "label": "Монумент «Қазақ Елі»", "aliases": ["қазақ елі", "казак ели", "площадь независимости", "kazakh eli"]},
    {"key": "shabyt", "label": "Дворец творчества «Шабыт»", "aliases": ["шабыт", "shabyt"], "prefer": "-", "prefer_cats": ("arts_centre", "event_venue", "theatre", "landmark")},
    {"key": "duman", "label": "Ailand (бывш. Думан)", "aliases": ["думан", "duman", "ailand", "айленд", "айлэнд"], "prefer": "-", "prefer_cats": ("zoo_aquarium", "kids_indoor", "theme_park", "mall")},
    {"key": "aruzhan", "label": "ТРЦ Аружан", "aliases": ["аружан", "aruzhan"]},
]
