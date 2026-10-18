import re

ALIASES = {
    'cafe': 'кафе кофе кофейня coffee café кофехана кофе ішу',
    'restaurant': 'ресторан еда поесть тамақ мейрамхана restaurant food',
    'park': 'парк сад прогулка погулять саябақ серуен бақ park walk garden',
    'playground': 'дети ребёнок площадка балалар ойын playground kids',
    'museum': 'музей мұражай museum', 'mall': 'магазины торговый сауда shopping mall',
    'viewpoint': 'смотровая көрініс viewpoint', 'monument': 'памятник ескерткіш monument',
    'library': 'библиотека кітапхана library', 'sport': 'спорт sport',
    'cinema': 'кино кинотеатр cinema', 'theatre': 'театр theatre',
    'gallery': 'галерея gallery', 'nightlife': 'ночной клуб nightlife',
}

def tokens(text):
    aliases = {'байтерек': 'bayterek', 'бәйтерек': 'bayterek', 'baiterek': 'bayterek',
               'хан': 'khan', 'шатыр': 'shatyr', 'мега': 'mega', 'силк': 'silk', 'уэй': 'way'}
    return [aliases.get(t, t) for t in re.findall(r'[^\W_]+', text.casefold().replace('ё', 'е'), re.UNICODE)]

def document(poi):
    return (f'{poi["name"]} ({poi.get("name_en") or ""}) {poi.get("name_kk") or ""}. '
            f'Категория: {poi["category"]} {ALIASES.get(poi["category"], "")}. '
            f'Теги: {", ".join(poi["tags"])}. {poi.get("description") or ""}. '
            f'Адрес: {poi.get("address") or ""}')
