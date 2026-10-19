import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
LANDMARKS = [
    (('mega silk way', 'мега силк', 'мега silk'), 51.0895, 71.4075, 'Mega Silk Way'),
    (('байтерек', 'бәйтерек', 'bayterek'), 51.12825, 71.43049, 'Байтерек'),
    (('хан шатыр', 'khan shatyr'), 51.1325, 71.4039, 'Хан Шатыр'),
    (('экспо', 'expo', 'нұр әлем', 'нур алем'), 51.0892, 71.4144, 'ЭКСПО'),
    (('аэропорт', 'airport', 'әуежай'), 51.0222, 71.4669, 'Аэропорт Астаны'),
    (('нурлы жол', 'нұрлы жол', 'nurly zhol'), 51.1096, 71.5590, 'Вокзал Нурлы Жол'),
    (('астана 1', 'астана-1', 'astana 1'), 51.1960, 71.4094, 'Вокзал Астана-1'),
]

def haversine_m(lat1, lon1, lat2, lon2) -> int:
    values = [float(v) for v in (lat1, lon1, lat2, lon2)]
    if not all(math.isfinite(v) for v in values) or any(abs(values[i]) > (90 if i % 2 == 0 else 180) for i in range(4)):
        raise ValueError('Invalid coordinates')
    a, b, c, d = map(math.radians, values)
    h = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return round(6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h)))))

def resolve_landmark(text: str) -> dict | None:
    text = re.sub(r'\s+', ' ', text.casefold()).strip()
    if not text:
        return None
    from .retriever import catalog
    best, best_score = None, 0
    # Origin lookup retains every canonical record but shares search's version.
    for poi in catalog()["pois"]:
        for name in (poi['name'], poi.get('name_en'), poi.get('name_kk')):
            if not name:
                continue
            name = name.casefold()
            score = 1 if name == text else SequenceMatcher(None, name, text).ratio()
            if len(name) >= 5 and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text):
                score = max(score, .95)
            if score > best_score:
                best, best_score = poi, score
    if best_score >= .86:
        return {'lat': best['lat'], 'lon': best['lon'], 'label': best['name']}
    for aliases, lat, lon, label in LANDMARKS:
        if any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text) for alias in aliases):
            return {'lat': lat, 'lon': lon, 'label': label}
    from data.collect.http import get_json
    params = urlencode({'q': text + ', Astana, Kazakhstan', 'format': 'json', 'limit': 1,
                        'viewbox': '71.2,51.3,71.65,50.95', 'bounded': 1})
    try:
        rows = get_json('https://nominatim.openstreetmap.org/search?' + params)
        if rows:
            return {'lat': float(rows[0]['lat']), 'lon': float(rows[0]['lon']), 'label': rows[0]['display_name']}
    except (OSError, ValueError, KeyError):
        pass
    return None
