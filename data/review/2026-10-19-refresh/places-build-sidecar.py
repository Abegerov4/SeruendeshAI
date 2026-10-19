"""Materialize reviewed public facts, keeping canonical rows immutable."""
from copy import deepcopy
from html import unescape
import json
from pathlib import Path
import re

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
ROWS = {row['id']: row for row in json.loads((ROOT/'data/processed/pois.json').read_text())}
SHA = '803dcffdb4473abddfc97be9cab5a41bc663ee74afc67c560f1723b42f8c1e63'
DAY = '2026-10-19'


def evidence(identity, url, excerpt, **source):
    return {'status':'accepted', 'conflict_status':'none', 'branch_scope':'exact',
            'branch_confirmation':{key:identity[key] for key in ('source_name','source_address')},
            'source':{'url':url,'excerpt':excerpt,'checked_at':DAY, **source},
            'valid_from':None,'valid_to':None}


records = {}
rejected = []
for collected in json.loads((HERE/'places-wolt-collected.json').read_text()):
    candidate = collected['candidate']
    slug = candidate['venue']['slug']
    merchant = collected.get('merchant')
    if not merchant or collected['http_status'] != 200:
        rejected.append({'slug':slug,'reason':'no parsed merchant identity'})
        continue
    if slug == 'hanibrunch-turkestan':
        rejected.append({'slug':slug,'canonical_id':candidate['canonical_id'],
                         'reason':'source Turkestan28 vs canonical Turkestan18,178m apart; another or moved branch unresolved'})
        continue
    if slug == 'del-papa-mega-silk-way':
        # Candidate OSM point lies 189m from source coordinates, at the other end
        # of a large shopping mall. Use the address-bearing canonical duplicate
        # only as a held candidate until an exact mall branch is unambiguous.
        rejected.append({'slug':slug,'canonical_id':candidate['canonical_id'],
                         'reason':'mall identity plausible but canonical duplicates disagree60vs62; withheld for review'})
        continue
    row = ROWS[candidate['canonical_id']]
    source_address = unescape(merchant['address']['streetAddress']).strip().replace('\u200b','')
    identity = {'canonical_name':row['name'],'canonical_address':row.get('address'),
                'canonical_lat':row['lat'],'canonical_lon':row['lon'],
                'source_name':unescape(merchant['name']), 'source_address':source_address,
                'source_lat':merchant['geo']['latitude'],'source_lon':merchant['geo']['longitude'],
                'source_url':collected['source_url'],'branch_confirmed':True,'match_basis':'name_coordinates'}
    url = collected['source_url']
    rec = {'canonical_id':row['id'], 'identity':identity, 'facts':[], 'menu_items':[], 'prices':[]}
    for field,value in [('address',source_address),('phone',merchant.get('telephone')),
                        ('cuisine',merchant.get('servesCuisine')),('menu_url',url)]:
        if not value:
            continue
        excerpt = (identity['source_name']+'; '+source_address if field == 'menu_url' else str(value))
        rec['facts'].append({'field':field,'value':value,
                             **evidence(identity,url,excerpt,channel='delivery',
                                        response_sha256=collected['response_sha256'],
                                        extraction='public merchant page JSON-LD')})
    # Wolt openingHours describe ordering/delivery. They are deliberately absent
    # from onsite opening_hours, and menu items remain delivery channel only.
    for item in collected.get('menu_items',[]):
        section = item['section']
        role = ('meal' if re.search(r'^(?:горячие блюда|основн|супы|азиатские супы|суп |суп$|супы пюре|пицц|паст|завтраки|сытные завтраки|сеты завтраков|горячее)',section,re.I)
                else 'drink' if re.search(r'кофе|напитки|чай|лимонад|смузи|слэши',section,re.I)
                else 'dessert' if re.search(r'десерт|торт|выпечка',section,re.I) else 'unknown')
        if re.search(r'конструктор|сборный|добавки|соус',item['name'],re.I):
            role='unknown'
        components = []
        if 'котлет' in item['name'].lower() and 'пюре' in item['name'].lower():
            components = (['куриными котлетами','Пюре'] if slug == 'espresso-bar-expo'
                          else ['Куриная котлета','пюре','шпинатом','картофельным пюре'])
        excerpt = f"{section}: {item['name']}; {item['amount']:g} KZT"
        if item.get('component_excerpt'):
            excerpt += '; '+item['component_excerpt']
        rec['menu_items'].append({'id':item['id'],'name':item['name'], 'components':components,'aliases':[],
            'role':role, 'price':{'amount':item['amount'],'currency':'KZT','unit':'item',
                                 'channel':'delivery','kind':'item'} if not re.search(r'сборный|конструктор',item['name'],re.I) else None,
            **evidence(identity,url,excerpt,channel='delivery',menu_section=section,
                       response_sha256=collected['response_sha256'],extraction='visible public menu card')})
    records[row['id']] = rec

# Independently reviewed exact 2GIS branch cards (Contacts establishes address;
# Info establishes attributes). Names/addresses are preserved verbatim below.
GIS = [
    ('koktem','70000001032494391','Көкtem','Улица Динмухамед Конаев,12/1',5000,
     [('format','Кафе','Кафе'),('terrace',True,'Летняя веранда'),('kids_area',True,'Детский уголок; Детская комната')]),
    ('daredzhani-mega-silk-way','70000001087635586','Дареджани','Кабанбай батыр проспект,62; ТРЦ MEGA Silk Way',10000,
     [('format','Ресторан','Ресторан'),('cuisines',['Грузинская','Кавказская'],'Грузинская кухня; Кавказская кухня'),
      ('wifi',True,'Wi-Fi для клиентов'),('seating_capacity_max',70,'До 70 мест'),('terrace',True,'Летняя веранда')]),
    ('tanuki-nur-sultan','70000001060637337','Tanuki','Проспект Мангилик Ел,55а',7000,
     [('format','Японский ресторан','Японский ресторан'),('cuisines',['Японская'],'Японская кухня'),
      ('wifi',True,'Wi-Fi для клиентов'),('kids_area',True,'Детский уголок; Детская комната'),('terrace',True,'Летняя веранда')]),
    ('espresso-bar-expo','70000001029139626','Espresso Bar','Кабанбай батыр проспект,58Б корпус2',3000,
     [('format','Кофейня','Кофейня'),('wifi',True,'Бесплатный Wi-Fi'),('laptop_allowed',True,'Можно с ноутбуком'),
      ('seating_capacity_max',50,'До 50 мест')]),
    ('discovery-coffee-mangilik-el','70000001059485628','Discovery Coffee','Проспект Мангилик Ел,54',2000,
     [('format','Кофейня','Сеть кофеен'),('wifi',True,'Бесплатный Wi-Fi'),('seating_capacity_max',20,'До 20 мест')]),
    ('rumi-megasilkway','70000001027297427','Rumi','Кабанбай батыр проспект,62; ТРЦ MEGA Silk Way',7000,
     [('format','Центр плова','Центр плова'),('cuisines',['Узбекская'],'Узбекская кухня'),
      ('wifi',True,'Wi-Fi для клиентов'),('seating_capacity_max',110,'До 110 мест')]),
    ('qaganat-dostyk-ast','70000001034709690','Qaganat','Улица Достык,5',None,
     [('format','Столовая','Столовая'),('opening_hours','24/7','Круглосуточно')]),
]
evidence_rows=[]
by_slug={r['identity']['source_url'].rsplit('/',1)[-1]:r for r in records.values()}
for slug,firm,name,address,average,facts in GIS:
    rec=by_slug[slug];ident=rec['identity'];card='https://2gis.kz/astana/firm/'+firm;info=card+'/tab/info'
    evidence_rows.append({'source_url':card,'info_url':info,'checked_at':DAY,'branch_name':name,
                          'branch_address':address,'canonical_id':rec['canonical_id'],
                          'average_check_kzt':average,'facts':[{'field':f,'value':v,'excerpt':e} for f,v,e in facts]})
    for field,value,excerpt in facts:
        # A field has one reviewed value; don't leave competing cuisine tags.
        rec['facts']=[f for f in rec['facts'] if f['field']!=field]
        source=card if field in {'format','opening_hours'} else info
        rec['facts'].append({'field':field,'value':value,
            **evidence(ident,source,excerpt,branch_name=name,branch_address=address,identity_url=card,
                       extraction='reviewed public 2GIS branch Contacts/Info',channel='dine_in')})
    if average is not None:
        rec['prices'].append({'amount':average,'currency':'KZT','unit':'person','channel':'dine_in',
            'kind':'average_check',**evidence(ident,info,f'Чек {average} тнг.',
                branch_name=name,branch_address=address,identity_url=card,channel='dine_in')})

# Expo steak-house identity also comes from its branch route link coordinates.
row=ROWS['overture:c0ebebea-c333-467e-9649-e3fb823b1491']
identity={'canonical_name':row['name'],'canonical_address':row.get('address'),'canonical_lat':row['lat'],
          'canonical_lon':row['lon'],'source_name':'Line Brew','source_address':'Проспект Мангилик Ел,55/1',
          'source_lat':51.088901,'source_lon':71.414775,'source_url':'https://2gis.kz/astana/firm/70000001030035728',
          'branch_confirmed':True,'match_basis':'name_coordinates'}
card=identity['source_url'];info=card+'/tab/info'
rec={'canonical_id':row['id'],'identity':identity,'facts':[],'menu_items':[],'prices':[]}
for field,value,excerpt in [('format','Стейк-хаус','Стейк-хаус'),('cuisines',['Европейская'],'Европейская кухня'),
                            ('wifi',True,'Wi-Fi для клиентов'),('seating_capacity_max',118,'До 118 мест'),
                            ('terrace',True,'Летняя веранда')]:
    rec['facts'].append({'field':field,'value':value,**evidence(identity,info,excerpt,identity_url=card,channel='dine_in')})
rec['prices'].append({'amount':18000,'currency':'KZT','unit':'person','channel':'dine_in','kind':'average_check',
                     **evidence(identity,info,'Чек 18000 тнг.',identity_url=card,channel='dine_in')})
records[row['id']]=rec
evidence_rows.append({'source_url':card,'info_url':info,'canonical_id':row['id'],'checked_at':DAY,
                      'branch_name':'Line Brew','branch_address':identity['source_address'],
                      'route_link':'https://2gis.kz/astana/directions/points/|71.414775,51.088901;70000001030035728',
                      'average_check_kzt':18000,'facts':rec['facts']})

# Additional exact branch cards collected after the first publishable sample.
for entry in json.loads((HERE/'places-additional-2gis.json').read_text()):
    card='https://2gis.kz/astana/firm/'+entry['firm'];info=card+'/tab/info'
    rec=by_slug.get(entry.get('slug'))
    if rec is None:
        row=ROWS[entry['canonical_id']]
        ident={'canonical_name':row['name'],'canonical_address':row.get('address'),
               'source_name':entry['name'],'source_address':entry['address'],'source_url':card,
               'branch_confirmed':True,'match_basis':'name_address'}
        if entry.get('source_lat') is not None:
            ident.update(match_basis='name_coordinates',canonical_lat=row['lat'],canonical_lon=row['lon'],
                         source_lat=entry['source_lat'],source_lon=entry['source_lon'])
        rec={'canonical_id':row['id'],'identity':ident,'facts':[],'menu_items':[],'prices':[]}
        records[row['id']]=rec
    ident=rec['identity']
    for field,value,excerpt in entry['facts']:
        rec['facts']=[f for f in rec['facts'] if f['field']!=field]
        rec['facts'].append({'field':field,'value':value,
          **evidence(ident,info,excerpt,identity_url=card,branch_name=entry['name'],
                     branch_address=entry['address'],channel='dine_in')})
    rec['prices'].append({'amount':entry['average'],'currency':'KZT','unit':'person',
      'kind':'average_check','channel':'dine_in','comparison_group':entry['group'],
      **evidence(ident,info,f"Чек {entry['average']} тнг.",identity_url=card,
                 branch_name=entry['name'],branch_address=entry['address'],channel='dine_in')})
    evidence_rows.append({'source_url':card,'info_url':info,'canonical_id':rec['canonical_id'],
      'checked_at':DAY,'branch_name':entry['name'],'branch_address':entry['address'],
      'average_check_kzt':entry['average'],'comparison_group':entry['group'],
      'facts':[{'field':f,'value':v,'excerpt':e} for f,v,e in entry['facts']]})
# Explicit source categories, not a cost threshold or a venue-name inference.
for rec in records.values():
    for price in rec['prices']:
        if 'comparison_group' not in price:
            price['comparison_group']=('cafe' if rec['canonical_id'] in {
              'overture:22ad98d6-faf7-4c60-b761-82371ea7424d','overture:b0d26f91-135b-4ee0-bb0e-1de57b965856',
              'osm:node/12990081501'} else 'restaurant')

# Independently reviewed raw-source audit facts. Original canonical IDs survive.
audit_path=HERE/'places-audit-approved.json'
if audit_path.exists():
    audit=json.loads(audit_path.read_text())
    if audit['canonical_sha256']!=SHA:
        raise ValueError('Reviewed audit is bound to another canonical master')
    for rec in audit['records']:
        if rec['canonical_id'] in records:
            raise ValueError('Audit merge requires an explicit same-branch conflict review')
        records[rec['canonical_id']]=rec

payload={'schema_version':1,'canonical_sha256':SHA,'as_of':DAY,'records':list(records.values())}
(ROOT/'data/sources/place_details_2026-10-19.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
(HERE/'places-2gis-evidence.json').write_text(json.dumps(evidence_rows,ensure_ascii=False,indent=2)+'\n')
(HERE/'places-held-candidates.json').write_text(json.dumps(rejected+[{
    'canonical_id':'overture:1ebeb4db-5e4d-47d1-9784-6a65efa51f7b','name':'Buffet canteen',
    'canonical_address':'Сауран көшесі34','reason':'No exact branch in public2GIS Буфет search or explicit websearch; format correction unconfirmed, no change',
    'source_urls':['https://2gis.kz/astana/search/Буфет'],'checked_at':DAY}],ensure_ascii=False,indent=2)+'\n')
print('records',len(records),'menus',sum(len(r['menu_items']) for r in records.values()),
      'facts',sum(len(r['facts']) for r in records.values()),'prices',sum(len(r['prices']) for r in records.values()))
