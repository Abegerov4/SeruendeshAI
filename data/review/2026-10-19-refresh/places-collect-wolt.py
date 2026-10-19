"""One-off free public merchant-page collection; does not alter canonical data."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
import requests

OUT = Path(__file__).parent
candidates = json.loads((OUT / 'places-wolt-candidates.json').read_text())
selected = [4,5,11,15,18,20,21,22,23,24,26,27,33,36,41,42,43,44,46,47,49,51,58,61,62,64,65,68,69,71,77,84]
chosen = [candidates[i] for i in selected]
for c in candidates:
    if c['venue']['slug'] in {'koktem','qaganat-dostyk-ast','bistro-koktem'}:
        chosen.append(c)
# Prefer the named canonical branch whose coordinates lie in the actual mall.
for c in chosen:
    if c['venue']['slug'] == 'del-papa-mega-silk-way':
        c.update(canonical_id='osm:node/12093489323',canonical_name='Del Papa',canonical_address=None,
                 canonical_lat=51.088547,canonical_lon=71.410156)


def collect(c):
    url = 'https://wolt.com/en/kaz/nur-sultan/restaurant/' + c['venue']['slug']
    r = requests.get(url, timeout=35)
    output = {'source_url':url, 'checked_at':'2026-10-19', 'http_status':r.status_code,
              'response_sha256':hashlib.sha256(r.content).hexdigest(), 'candidate':c}
    if r.status_code != 200:
        return output
    soup = BeautifulSoup(r.text,'html.parser')
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            ld = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(ld,dict) and ld.get('@type') == 'Restaurant':
            output['merchant'] = {k:ld.get(k) for k in ['name','address','geo','telephone','sameAs','servesCuisine']}
    items=[]
    for h in soup.select('h3[data-test-id="horizontal-item-card-header"]'):
        card = h.find_parent(id=re.compile(r'^item-card-content-'))
        price = card.select_one('[data-test-id="horizontal-item-card-price"]') if card else None
        if not price:
            continue
        amount = re.search(r'KZT\s*([\d,]+(?:\.\d+)?)',price.get_text(' ',strip=True))
        if not amount:
            continue
        section = h.find_previous('h2')
        section = section.get_text(' ',strip=True) if section else ''
        items.append({'id':card['id'].removeprefix('item-card-content-'),
                      'name':h.get_text(' ',strip=True), 'amount':float(amount[1].replace(',','')),
                      'section':section})
    # Keep a small factual menu sample, prioritizing explicit meal sections and
    # the user's requested cutlet + potato combination. No menu descriptions.
    seen=set(); dedup=[]
    for item in items:
        if item['id'] not in seen:
            dedup.append(item);seen.add(item['id'])
    def priority(item):
        name=item['name'].lower()
        return (0 if 'котлет' in name and 'пюре' in name else
                1 if re.search(r'горяч|основн|суп|пицц|паст|завтрак|плов|лагман',item['section'],re.I) else 2)
    dedup.sort(key=priority)
    output['menu_items'] = dedup[:5]
    output['published_item_count'] = len(dedup)
    return output


results=[]
with ThreadPoolExecutor(max_workers=5) as pool:
    for future in as_completed([pool.submit(collect,c) for c in chosen]):
        try:
            out=future.result()
        except Exception as exc:
            out={'error':type(exc).__name__+': '+str(exc)[:200]}
        results.append(out)
        print(out.get('candidate',{}).get('venue',{}).get('slug'),out.get('http_status'),out.get('published_item_count'),flush=True)
        (OUT/'places-wolt-collected.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
