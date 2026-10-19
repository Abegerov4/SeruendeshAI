"""Reviewed exact-branch facts only; candidates with disputes remain outside sidecar."""
from pathlib import Path
from datetime import date
from copy import deepcopy
import json,hashlib,ast,re,math
from bs4 import BeautifulSoup
HERE=Path(__file__).parent;ROOT=HERE.parents[2]
raw=(ROOT/'data/processed/pois.json').read_bytes();sha=hashlib.sha256(raw).hexdigest()
rows={r['id']:r for r in json.loads(raw)};batch=json.loads((HERE/'discovery-batch.json').read_text())
cards={x['source_url']:x for x in json.loads((HERE/'discovery-cards.json').read_text())}
records=[]
def bound_state(card,firm):
 soup=BeautifulSoup(Path(card['archive_path']).read_text(),'html.parser')
 text=next(x.get_text() for x in soup.find_all('script') if 'initialState = JSON.parse' in x.get_text())
 match=re.search(r"initialState\s*=\s*JSON.parse\(('(?:\\.|[^'\\])*')\)",text)
 state=json.loads(ast.literal_eval(match[1]));found=[]
 def walk(o):
  if isinstance(o,dict):
   if str(o.get('id'))==firm and 'point' in o and 'address_name' in o:found.append(o)
   for v in o.values():walk(v)
  elif isinstance(o,list):
   for v in o:walk(v)
 walk(state)
 if len(found)!=1:raise ValueError('Ambiguous firm state')
 return found[0]
def make(index,firm,name,facts):
 row=rows[batch[index]['id']];url='https://2gis.kz/astana/firm/'+firm;card=cards[url];info=cards[url+'/tab/info'];state=bound_state(card,firm)
 ident={'canonical_name':row['name'],'canonical_address':row.get('address'),'canonical_lat':row['lat'],'canonical_lon':row['lon'],'source_name':name,'source_address':state['address_name'],'source_lat':state['point']['lat'],'source_lon':state['point']['lon'],'source_url':url,'branch_confirmed':True,'match_basis':'name_coordinates'}
 rec={'canonical_id':row['id'],'identity':ident,'facts':[],'menu_items':[],'prices':[]}
 def add(field,value,excerpt,source=info):
  rec['facts'].append({'field':field,'value':value,'status':'accepted','conflict_status':'none','branch_scope':'exact','branch_confirmation':{k:ident[k] for k in ['source_name','source_address']},'source':{'url':source['source_url'],'excerpt':excerpt,'checked_at':'2026-10-19','channel':'onsite','archive_path':source['archive_path'],'response_sha256':source['response_sha256'],'extraction':'reviewed public 2GIS exact branch Contacts/Info'},'valid_from':None,'valid_to':None})
 add('address',state['address_name'],state['address_name'],card)
 for field,value,excerpt in facts:add(field,value,excerpt)
 records.append(rec);return rec,add
r,add=make(3,'70000001032715428','Dami',[
 ('format','Халяльное кафе','Халяльное кафе'),('halal',True,'Халяльная кухня'),('wifi',True,'Wi-Fi для клиентов'),('terrace',True,'Летняя веранда'),('kids_area',True,'Детский уголок'),('reservations',True,'Заказ столиков'),('takeaway',True,'Заказ навынос'),('delivery',True,'Услуги Доставка'),('seating_capacity_max',80,'До 80 мест'),('wheelchair_accessible',True,'Доступный вход для людей с инвалидностью')])
add('phone','+77779444747','+7‒777‒944‒47‒47',cards['https://2gis.kz/astana/firm/70000001032715428'])
add('menu_url','https://2gis.kz/astana/firm/70000001032715428/tab/prices','Меню',cards['https://2gis.kz/astana/firm/70000001032715428'])
r,add=make(8,'70000001030630928','Тәп-Тәтті',[
 ('format','Кондитерская','Кондитерская'),('takeaway',True,'отдел самовывоза'),('delivery',True,'Услуги Доставка'),('wheelchair_accessible',True,'Доступный вход для людей с инвалидностью')])
# Full weekly hours are public response data for the matched firm, not an inference
# from "opens at" or the ordering hours of a delivery platform.
c=cards['https://2gis.kz/astana/firm/70000001030630928'];s=bound_state(c,'70000001030630928')
assert set(s['schedule'])=={'Mon','Tue','Wed','Thu','Fri','Sat','Sun'}
assert all(v['working_hours']==[{'from':'08:00','to':'22:00'}] for v in s['schedule'].values())
add('opening_hours','Mo-Su 08:00-22:00','Matched firm public schedule: Mon–Sun 08:00–22:00',c)
for index,firm,kids in [(12,'70000001091370531',False),(18,'70000001048362608',True)]:
 facts=[('format','Служба доставки / пиццерия','Служба доставки; В справочнике Пиццерии'),('cuisines',['Итальянская'],'Итальянская кухня'),('wifi',True,'Wi-Fi для клиентов'),('takeaway',True,'Заказ навынос'),('delivery',True,'Услуги Доставка')]
 if kids:facts += [('kids_area',True,'Детский уголок'),('wheelchair_accessible',True,'Доступный вход для людей с инвалидностью')]
 make(index,firm,'dodo pizza',facts)
payload={'schema_version':1,'canonical_sha256':sha,'as_of':'2026-10-19','records':records}
path=ROOT/'data/sources/place_details_discovery_2026-10-19.json';path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
# Price values and conflicting historical schedules are retained in source archives
# and report candidates, not silently represented as current exact venue claims.
print('records',len(records),'facts',sum(len(r['facts']) for r in records),'prices',sum(len(r['prices']) for r in records))
