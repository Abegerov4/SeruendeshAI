import re
from urllib.parse import urlencode
from .http import get_json

def description(tags):
    """Read OSM-linked articles only; no ambiguous name search."""
    ref = tags.get('wikipedia', '')
    try:
        if not ref and re.fullmatch(r'Q\d+', tags.get('wikidata', '')):
            qid = tags['wikidata']
            entity = get_json(f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json')['entities'][qid]
            for lang in ('ru', 'kk', 'en'):
                link = entity.get('sitelinks', {}).get(lang + 'wiki')
                if link:
                    ref = lang + ':' + link['title']
                    break
        if ':' not in ref:
            return None
        lang, title = ref.split(':', 1)
        if not re.fullmatch('[a-z-]{2,15}', lang):
            return None
        params = urlencode({'action': 'query', 'format': 'json', 'prop': 'extracts',
                            'exintro': 1, 'explaintext': 1, 'exsentences': 2,
                            'redirects': 1, 'titles': title})
        pages = get_json(f'https://{lang}.wikipedia.org/w/api.php?{params}')['query']['pages']
        return next((p['extract'].strip() for p in pages.values() if p.get('extract')), None)
    except (OSError, ValueError, KeyError):
        return None
