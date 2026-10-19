"""Bounded, free public 2GIS discovery for thirty address-bearing food branches."""
import json,math,hashlib,time,urllib.request,urllib.parse,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from bs4 import BeautifulSoup
HERE=Path(__file__).parent
CACHE=HERE/'discovery-cache';CACHE.mkdir(exist_ok=True)
rows=json.load(open('data/processed/pois.json'))
enriched={x['canonical_id'] for x in json.load(open('data/sources/place_details_2026-10-19.json'))['records']}
def distance(r):
 return 6371000*2*math.asin(min(1,math.sqrt(math.sin(math.radians(r['lat']-51.092788)/2)**2+math.cos(math.radians(r['lat']))*math.cos(math.radians(51.092788))*math.sin(math.radians(r['lon']-71.421482)/2)**2)))
eligible=sorted((r for r in rows if r['category'] in ['cafe','restaurant'] and not r.get('website') and r['id'] not in enriched),key=distance)
indices=[0,1,2,3,4,5,6,7,8,9,10,11,12,15,16,17,18,19,20,21,22,23,24,25,28,29,30,31,32,34]
batch=[{**eligible[i],'distance_expo_m':round(distance(eligible[i]))} for i in indices]
(HERE/'discovery-batch.json').write_text(json.dumps(batch,ensure_ascii=False,indent=2)+'\n')
queries=['TOTEM','Casablanca Мангилик Ел 53','walk cafe','Dami Туркестан 34','People Туркестан','Мята Platinum Мангилик Ел','Joule 27','Coffee Shot Мангилик Ел 51','Тап Татти Мангилик Ел','Синьора Толстушка Бокейхан','Blonde Brune','German Doner Мангилик Ел','Додо Мангилик Ел 58','Whoopie Cakes','Croissant Factory','Узбекский двор Мангилик Ел','Coffee black52','Maguro Мангилик Ел','Додо Мангилик Ел 47','Baker Street','Мята Коркем','Gezellig','Caramelo Туркестан','Magandamdi','Azim Кабанбай','Qimchi','Mon Plaisir','Italissima','Tatti Latte','Gasteria']
def fetch(arg):
 idx,row,q=arg;u='https://2gis.kz/astana/search/'+urllib.parse.quote(q)
 meta={'canonical_id':row['id'],'canonical_name':row['name'],'canonical_address':row.get('address'),'query':q,'source_url':u,'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:raw=r.read();meta.update(http_status=r.status,final_url=r.url)
  digest=hashlib.sha256(raw).hexdigest();stem=f'{idx:02d}-{digest[:16]}'
  (CACHE/(stem+'.html')).write_bytes(raw)
  soup=BeautifulSoup(raw,'html.parser');text=soup.get_text(' ',strip=True);(CACHE/(stem+'.txt')).write_text(text)
  meta.update(response_sha256=digest,archive_path=str(CACHE/(stem+'.html')),text_path=str(CACHE/(stem+'.txt')),text_excerpt=text[-14000:],firm_links=[{'name':a.get_text(' ',strip=True),'url':'https://2gis.kz'+a['href'] if a['href'].startswith('/') else a['href']} for a in soup.find_all('a',href=True) if '/firm/' in a['href']])
 except urllib.error.HTTPError as e:meta.update(http_status=e.code,error=str(e),outcome='source_unavailable')
 except Exception as e:meta.update(error=type(e).__name__+': '+str(e),outcome='source_unavailable')
 print(idx,row['name'],meta.get('http_status'),len(meta.get('firm_links',[])),flush=True)
 return meta
with ThreadPoolExecutor(max_workers=4) as pool:out=list(pool.map(fetch,[(i,r,queries[i]) for i,r in enumerate(batch)]))
(HERE/'discovery-2gis-searches.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
