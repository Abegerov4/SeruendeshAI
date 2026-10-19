"""Primary branch-specific onsite menu; preserve publisher timestamp and price units."""
from pathlib import Path
import json,hashlib,re
HERE=Path(__file__).parent;ROOT=HERE.parents[2]
raw=(ROOT/'data/processed/pois.json').read_bytes();rows={r['id']:r for r in json.loads(raw)}
row=rows['osm:node/13173517356'];menu=json.loads((HERE/'discovery-gasteria-public-menu.json').read_text())
source={s['source_url']:s for s in json.loads((HERE/'discovery-supplemental.json').read_text())}
rooturl='https://gasteria-mega-silk-way.kamiqr.com/menu/at-place';url=rooturl+'/list';root=source[rooturl];listing=source[url]
assert root['http_status']==200 and listing['http_status']==200
assert menu['orgAttrs']['name']=='Gasteria Mega Silk Way' and menu['orgAttrs']['address']['RU']=='Астана, пр. Кабанбай батыра 62'
assert menu['link']=='at-place' and menu['i18N']['currency']=='KZT'
ident={'canonical_name':row['name'],'canonical_address':row.get('address'),'source_name':menu['orgAttrs']['name'],'source_address':menu['orgAttrs']['address']['RU'],'source_url':rooturl,'branch_confirmed':True,'match_basis':'name_address'}
def evidence(excerpt,proof=listing):
 return {'status':'accepted','conflict_status':'none','branch_scope':'exact','branch_confirmation':{k:ident[k] for k in ['source_name','source_address']},'source':{'url':proof['source_url'],'excerpt':excerpt[:990],'checked_at':'2026-10-19','channel':'dine_in','source_updated_at':menu['timestamp'],'menu_version':menu['version'],'archive_path':proof['archive_path'],'response_sha256':proof['response_sha256'],'extraction':'public merchant onsite menu HTML window.__data__; names, descriptions, prices and visibility flags are publisher data'},'valid_from':None,'valid_to':None}
rec={'canonical_id':row['id'],'identity':ident,'facts':[{'field':'address','value':ident['source_address'],**evidence(ident['source_address'],root)},{'field':'menu_url','value':url,**evidence('Gasteria Mega Silk Way; адрес заведения: Астана, пр. Кабанбай батыра 62; menu/at-place',root)}],'menu_items':[],'prices':[]}
# Verify the publisher's own loaded frontend divides primary prices by100. This
# is price-unit normalization, not an estimated meal or average-check price.
asset=HERE/'discovery-cache/asset-723438aaacbded6f.js';js=asset.read_text();assert re.search(r'primary.{0,35}price\)/100',js)
asset_sha=hashlib.sha256(asset.read_bytes()).hexdigest()
meal_categories={'Большие завтраки','Авторские завтраки','Каши','Салаты','Супы','Основное','Паста','Пицца'}
dessert_categories={'Десерты','Торты','Выпечка'}
held=[]
for section in menu['tree']['sections']:
 if menu['sections'][section['sectionId']]['name'].get('RU')!='Основное меню':continue
 for catref in section['categories']:
  cat=menu['categories'][catref['categoryId']];category=cat['name'].get('RU','').strip()
  if cat['isHidden']:continue
  for ref in catref.get('items') or []:
   item=menu['items'][ref['itemId']]
   if item['isHidden'] or item['isOff']:continue
   name=item['name'].get('RU','').strip();price=item['prices']
   if not name:continue
   amount=price.get('primary',{}).get('price')
   if price.get('modSelects') or price.get('others') or not isinstance(amount,(int,float)) or amount<=0:
    held.append({'id':item['_id'],'name':name,'reason':'Required/alternative price structure or absent positive base price; no exact item price asserted'});continue
   en=item['name'].get('EN','').strip();desc=item.get('specs',{}).get('shortDesc',{}).get('RU','').strip()
   excerpt=f'{category}: {name}; {amount/100:g} KZT за позицию; publisher primary.price={amount}, display divisor100'
   if en:excerpt+='; EN: '+en
   if desc:excerpt+='; '+desc
   proof=evidence(excerpt)
   proof['source'].update(menu_category=category,source_item_id=item['_id'],price_unit_proof={'source_url':'https://gasteria-mega-silk-way.kamiqr.com/assets/index-zmK8bJ7M.js','archive_path':str(asset),'response_sha256':asset_sha,'rule':'Publisher rendering item.prices.primary.price /100 in menu currency'})
   rec['menu_items'].append({'id':item['_id'],'name':name,'components':[],'aliases':[en] if en else [],'role':'meal' if category in meal_categories else 'dessert' if category in dessert_categories else 'unknown','price':{'amount':amount/100,'currency':'KZT','unit':'item','channel':'dine_in','kind':'item'},**proof})
# Directory facts are separate exact-branch observations; no hours or phone are
# asserted because available sources disagree or lack a complete current week.
directory=source['https://astana.restoran.kz/coffee/102604-gasteria-mega-silk-way']
assert directory['http_status']==200 and 'Кофейня Gasteria в' in directory['text_excerpt'] and '62' in directory['text_excerpt']
for field,value,excerpt in [('format','Кофейня','Кофейня Gasteria в ТРЦ MEGA Silk Way в Астане'),('cuisines',['Европейская'],'Кухня европейская'),('wifi',True,'Wi-Fi'),('seating_capacity',56,'Количество мест 56 мест')]:
 proof=evidence(excerpt,directory);proof['source'].pop('source_updated_at');proof['source'].pop('menu_version');proof['source']['extraction']='reviewed exact branch directory card, name + MEGA Silk Way + Cabанбай62'
 rec['facts'].append({'field':field,'value':value,**proof})
payload={'schema_version':1,'canonical_sha256':hashlib.sha256(raw).hexdigest(),'as_of':'2026-10-19','records':[rec]}
(HERE/'discovery-gasteria.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
(HERE/'discovery-gasteria-report.json').write_text(json.dumps({'canonical_id':row['id'],'source_branch':ident,'checked_at':'2026-10-19','source_updated_at':menu['timestamp'],'menu_version':menu['version'],'published_items_in_payload':len(menu['items']),'accepted_current_visible_main_menu_items':len(rec['menu_items']),'accepted_fields':len(rec['facts']),'held_items':held,'price_channel':'dine_in','note':'This is the currently served public onsite menu; source update date is retained and no claim of an October menu update is made. No ingredients, dietary labels or serving weights inferred. No combined cutlet/puree meal invented.'},ensure_ascii=False,indent=2)+'\n')
print('accepted_visible_main_menu_items',len(rec['menu_items']),'fields',len(rec['facts']),'held',len(held))
