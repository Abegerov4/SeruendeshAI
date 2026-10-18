import math
import re
from datetime import datetime, timezone, timedelta
from rag.geo import haversine_m

CATEGORIES = {'pub': 'bar', 'nightclub': 'nightlife', 'arts_centre': 'gallery',
              'coworking_space': 'coworking', 'artwork': 'monument', 'garden': 'park',
              'sports_centre': 'sport', 'memorial': 'monument', 'zoo': 'attraction'}
ALLOWED = set('cafe restaurant bar nightlife museum gallery theatre cinema park viewpoint monument attraction playground mall library coworking sport other'.split())

def name_key(value):
    return re.sub(r'[^\w]', '', value.casefold().replace('ё', 'е'))

def normalize(elements):
    result, groups = [], {}
    for element in sorted(elements, key=lambda e: (e['type'], e['id'])):
        t = element.get('tags', {})
        name = t.get('name') or t.get('name:ru') or t.get('name:kk') or t.get('name:en')
        pos = element.get('center', element)
        if not name or 'lat' not in pos or 'lon' not in pos:
            continue
        lat, lon = float(pos['lat']), float(pos['lon'])
        if not (math.isfinite(lat) and math.isfinite(lon) and 51.05 <= lat <= 51.25 and 71.25 <= lon <= 71.60):
            continue
        category = 'other'
        for key in ('amenity', 'tourism', 'leisure', 'historic', 'shop'):
            value = CATEGORIES.get(t.get(key), t.get(key))
            if value in ALLOWED:
                category = value
                break
        key = name_key(name)
        if any(haversine_m(lat, lon, p['lat'], p['lon']) < 50 for p in groups.get(key, [])):
            continue
        source_id = f'{element["type"]}/{element["id"]}'
        desc = t.get('description:ru') or t.get('description') or t.get('description:kk')
        poi = dict(id='osm:' + source_id, name=name, name_en=t.get('name:en'), name_kk=t.get('name:kk'),
                   lat=lat, lon=lon, category=category,
                   tags=[f'{k}={v}' for k, v in sorted(t.items()) if k in ('amenity', 'tourism', 'leisure', 'historic', 'cuisine', 'club', 'internet_access', 'outdoor_seating', 'wikidata', 'wikipedia')],
                   description=desc, description_source='osm' if desc else None,
                   address=', '.join(t[k] for k in ('addr:street', 'addr:housenumber', 'addr:unit') if t.get(k)) or None,
                   opening_hours=t.get('opening_hours'), phone=t.get('phone') or t.get('contact:phone'),
                   website=t.get('website') or t.get('contact:website'), rating=None, rating_count=None,
                   wheelchair=t.get('wheelchair') if t.get('wheelchair') in ('yes', 'no', 'limited') else None,
                   kid_friendly=True if category == 'playground' or t.get('tourism') == 'zoo' or t.get('kids') == 'yes' else None,
                   source='osm', source_url='https://www.openstreetmap.org/' + source_id,
                   updated_at=datetime.now(timezone(timedelta(hours=5))).date().isoformat())
        result.append((poi, t))
        groups.setdefault(key, []).append(poi)
    return result
