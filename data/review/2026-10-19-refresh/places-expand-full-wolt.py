"""Extract full factual delivery menus from bounded, hash-checked public pages."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

HERE=Path(__file__).parent
ROOT=HERE.parents[2]
MAIN=ROOT/'data/sources/place_details_2026-10-19.json'
OUT=ROOT/'data/sources/place_menus_full_2026-10-19.json'
main=json.loads(MAIN.read_text())
bound={r['canonical_id']:r for r in main['records'] if r['menu_items'] and 'wolt.com' in r['identity']['source_url']}
fetches=json.loads((HERE/'places-wolt-full-fetches.json').read_text())
if {f['canonical_id']for f in fetches}!=set(bound):raise ValueError('Incomplete fetch checkpoint')


def normalized(value):
    return re.sub(r'\s+',' ',unescape(str(value))).replace('\u200b','').strip().casefold()


def role(section,name):
    text=section.casefold()
    if re.search(r'конструктор|сборный|добавки|соус',name,re.I) or re.search(r'перекусы',text):return 'unknown'
    if re.search(r'напит|кофе|чай|чаи|лимонад|смузи|шейки|сок[и ]|вода|газиров|пиво|вино|сидр|соджу|токсода|коктейл|bubble|coffee|drink|tea',text):return 'drink'
    if re.search(r'гарнир|соусы|экстра|добавки|приборы',text):return 'side' if 'гарнир' in text else 'unknown'
    if re.search(r'десерт|торт|макарон$|макарон\s|тарталет|dessert',text):return 'dessert'
    if re.search(r'^(?:горячие блюда|горячее|основн|суп|азиатские супы|пицц|паст|завтраки|сытные завтраки|сеты завтраков|стейки|бургеры|говяжьи бургеры|куриные бургеры|донер|лагман|плов)',text):return 'meal'
    return 'unknown'


def sections(categories):
    result={}
    for category in categories:
        for ident in category.get('item_ids',[]):result.setdefault(ident,[]).append(category['name'].strip())
        result.update(sections([c for c in category.get('subcategories',[])if isinstance(c,dict)]))
    return result


def price_reason(item,options):
    if re.search(r'конструктор|сборный',item['name'],re.I):return 'configurable constructor base; completed order price unknown'
    if item.get('sell_by_weight_config') or item.get('variant'):
        return 'variable quantity, unit or variant requires separate price review'
    if item.get('deposit') is not None:return 'deposit may change completed order price'
    for ref in item.get('options',[]):
        minimum=ref.get('multi_choice_config',{}).get('total_range',{}).get('min')
        if minimum is None:return 'option selection minimum not explicit'
        if minimum>0:
            definition=options.get(ref.get('option_id'))
            if not definition:return 'required option definition absent; completed order price unknown'
            selectable=[v for v in definition.get('values',[]) if v.get('multi_choice_config',{}).get('total_range',{}).get('max',1)>0]
            if not selectable or any(type(v.get('price'))is not int or v['price']!=0 for v in selectable):
                return 'required configurable selection includes paid or unresolved choices'
    return None


records=[];reviews=[];held=[]
for fetched in sorted(fetches,key=lambda f:f['canonical_id']):
    ident=fetched['canonical_id'];prior=bound[ident];identity=deepcopy(prior['identity']);url=identity['source_url']
    decision={'canonical_id':ident,'source_url':url,'status':fetched['status'],'raw_cache':fetched.get('raw_cache'),'raw_sha256':fetched.get('raw_sha256')}
    if fetched['status']!='successful_fetch' or fetched.get('http_status')!=200:
        held.append({**decision,'reason':'Blocked/failed public fetch; no replacement menu'});continue
    raw=(ROOT/fetched['raw_cache']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=fetched['raw_sha256']:raise ValueError('Raw source hash mismatch: '+ident)
    checked=datetime.fromisoformat(fetched['fetched_at']).astimezone(ZoneInfo('Asia/Almaty')).date().isoformat()
    if checked!='2026-10-19':raise ValueError('Unexpected local acquisition date')
    soup=BeautifulSoup(raw,'html.parser')
    merchant=next((json.loads(s.get_text())for s in soup.select('script[type="application/ld+json"]')if json.loads(s.get_text()).get('@type')=='Restaurant'),None)
    if not merchant or any(normalized(value)!=normalized(expected)for value,expected in [
        (merchant['name'],identity['source_name']),
        (merchant['address']['streetAddress'],identity['source_address'])]) or merchant['geo']['latitude']!=identity['source_lat'] or merchant['geo']['longitude']!=identity['source_lon']:
        held.append({**decision,'reason':'Fresh merchant name/address/coordinate identity differs from accepted binding'});continue
    states=[json.loads(s.get_text())for s in soup.select('script.query-state[type="application/json"]')]
    queries=[q for state in states for q in state.get('queries',[]) if q.get('queryKey',[])[:3]==['venue-assortment','category-listing',url.rsplit('/',1)[-1]]]
    if len(queries)!=1:held.append({**decision,'reason':'No unique full public assortment state'});continue
    data=queries[0]['state']['data']
    if data.get('loading_strategy')!='full':held.append({**decision,'reason':'Provider assortment is partial, not full'});continue
    indexed={i['id']:i for i in data['items']};category_map=sections(data['categories']);option_map={o['id']:o for o in data.get('options',[])}
    # Visible card prices independently establish KZT units and the minor-unit
    # conversion. Synthetic Most ordered duplicates do not set menu sections.
    visible={};unparsed=[]
    for h in soup.select('h3[data-test-id="horizontal-item-card-header"]'):
        card=h.find_parent(id=re.compile(r'^item-card-content-'))
        if card is None:continue
        item_id=card['id'].removeprefix('item-card-content-');p=card.select_one('[data-test-id="horizontal-item-card-discounted-price"]') or card.select_one('[data-test-id="horizontal-item-card-price"]')
        text=p.get_text(' ',strip=True)if p else ''
        match=re.fullmatch(r'KZT\s*([\d,]+(?:\.\d+)?)',text)
        visible.setdefault(item_id,[]).append({'name':h.get_text(' ',strip=True),'amount':float(match[1].replace(',',''))if match else None,'price_text':text})
    old_by_id={i['id']:i for i in prior['menu_items']};menus=[];item_holds=[]
    for item in data['items']:
        item_id=item['id'];name=item['name'].strip();section=' / '.join(category_map.get(item_id,[]))
        if item.get('disabled_info') is not None:
            item_holds.append({'id':item_id,'name':name,'reason':'Provider marks item disabled'});continue
        # Do not suggest products explicitly unavailable for home delivery.
        if 'homedelivery' not in item.get('allowed_delivery_methods',[]):
            item_holds.append({'id':item_id,'name':name,'reason':'Provider does not allow home delivery for this item'});continue
        if item_id not in visible or any(normalized(v['name'])!=normalized(name)for v in visible[item_id]):
            item_holds.append({'id':item_id,'name':name,'reason':'No matching visible published menu card'});continue
        reason=price_reason(item,option_map)
        observed={v['amount']for v in visible[item_id]}
        amount=item.get('price')/100 if type(item.get('price'))is int else None
        if amount is None or amount<0 or observed!={amount}:
            reason='Visible KZT amount and structured minor-unit price do not agree'
        price=None if reason else {'amount':amount,'currency':'KZT','unit':item.get('unit_info') or 'item','channel':'delivery','kind':'item'}
        price_text=' / '.join(dict.fromkeys(v['price_text']for v in visible[item_id]))
        excerpt=f'{section}: {name}; displayed '+(price_text or 'price unknown')
        if item.get('unit_info'):excerpt+='; portion '+item['unit_info']
        components=[]
        # Previously manually verified literal components survive only if still
        # present in this new source. All other items keep empty component lists.
        for component in old_by_id.get(item_id,{}).get('components',[]):
            if component.casefold()in(name+' '+item.get('description','')).casefold():
                components.append(component)
                if component.casefold()not in excerpt.casefold():excerpt+='; '+component
        source={'url':url,'excerpt':excerpt,'checked_at':checked,'fetched_at':fetched['fetched_at'],
                'channel':'delivery','menu_section':section,'raw_cache':fetched['raw_cache'],
                'response_sha256':fetched['raw_sha256'],'extraction':'full public assortment state with visible KZT menu-card crosscheck'}
        if item.get('unit_info'):source['portion']=item['unit_info']
        if reason:source['price_status']='unknown_completed_price';source['price_note']=reason
        if item.get('original_price') is not None:source['discount_status']='current displayed price; original price not imported'
        menus.append({'id':item_id,'name':name,'components':components,'aliases':[],'role':role(section,name),'price':price,
            'status':'accepted','conflict_status':'none','branch_scope':'exact',
            'branch_confirmation':{k:identity[k]for k in ['source_name','source_address']},
            'source':source,'valid_from':None,'valid_to':None})
    if menus:records.append({'canonical_id':ident,'identity':identity,'facts':[],'menu_items':menus,'prices':[]})
    decision.update(assortment_loading_strategy=data['loading_strategy'],structured_items=len(data['items']),
                    visible_unique_cards=len(visible),accepted_menu_items=len(menus),
                    unknown_full_prices=sum(m['price']is None for m in menus),held_items=item_holds)
    reviews.append(decision)

payload={'schema_version':1,'canonical_sha256':main['canonical_sha256'],'as_of':'2026-10-19','records':records}
OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
summary={'schema_version':1,'as_of':'2026-10-19','canonical_sha256':main['canonical_sha256'],
         'bound_branches_requested':len(bound),'branches_complete':len(records),
         'accepted_menu_items':sum(len(r['menu_items'])for r in records),
         'unknown_full_prices':sum(i['price']is None for r in records for i in r['menu_items']),
         'roles':dict(Counter(i['role']for r in records for i in r['menu_items'])),
         'failed_or_unbound_branches':held,'branch_reviews':reviews,
         'source_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
         'main_source_sha256_unchanged':hashlib.sha256(MAIN.read_bytes()).hexdigest(),
         'limits':['Only provider full public assortment with visible menu cards; no onsite price inference.',
                   'Configured constructors or required paid choices retain price=null.',
                   'No generated aliases or components; uncertain section roles stay unknown.',
                   'Provider-disabled/non-delivery/unrendered items are reported rather than recommended.',
                   'Fresh retrieval proves public listing, not real-time kitchen stock or merchant last-update date.']}
(HERE/'places-wolt-full-menu-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print({k:v for k,v in summary.items()if k not in {'branch_reviews','limits'}})
