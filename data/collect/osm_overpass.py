import urllib.parse
from .http import get_json

BBOX = (51.05, 71.25, 51.25, 71.60)
FILTERS = {
    'amenity': 'cafe|restaurant|bar|pub|cinema|theatre|library|arts_centre|coworking_space|nightclub',
    'tourism': 'museum|gallery|attraction|viewpoint|artwork|zoo',
    'leisure': 'park|playground|garden|sports_centre',
    'historic': 'monument|memorial', 'shop': 'mall',
}

def collect(refresh=False):
    bbox = ','.join(map(str, BBOX))
    selectors = [f'nwr["{k}"~"^({v})$"]({bbox});' for k, v in FILTERS.items()]
    selectors.append(f'nwr["club"]({bbox});')
    query = '[out:json][timeout:120];(' + ''.join(selectors) + ');out center tags;'
    body = urllib.parse.urlencode({'data': query}).encode()
    errors = []
    for endpoint in ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']:
        try:
            return get_json(endpoint, body, refresh)['elements']
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
    raise RuntimeError('Overpass failed: ' + '; '.join(errors))
