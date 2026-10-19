import json,hashlib,urllib.request,urllib.error,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from bs4 import BeautifulSoup
HERE=Path(__file__).parent;CACHE=HERE/'discovery-cache'
urls=[]
for firm in ['70000001032715428','70000001030630928','70000001091370531','70000001048362608','70000001047928378','70000001066937642','70000001066021424']:
 for suffix in ['', '/tab/info']:urls.append('https://2gis.kz/astana/firm/'+firm+suffix)
urls += ['https://2gis.kz/astana/firm/70000001062012206/tab/branches','https://yandex.kz/maps/ru/org/joule_27/127662901008/','https://astana.restoran.kz/cafe/89180-dami','https://astana.spravker.ru/restoranyi/german-doner.htm']
def fetch(u):
 out={'source_url':u,'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:raw=r.read();out.update(http_status=r.status,final_url=r.url)
  digest=hashlib.sha256(raw).hexdigest();stem='card-'+digest[:16];(CACHE/(stem+'.html')).write_bytes(raw)
  s=BeautifulSoup(raw,'html.parser');text=s.get_text(' ',strip=True);(CACHE/(stem+'.txt')).write_text(text)
  out.update(response_sha256=digest,archive_path=str(CACHE/(stem+'.html')),text_path=str(CACHE/(stem+'.txt')),text_excerpt=re.sub(r'(?:\.\s*){5,}',' ',text)[-18000:],links=[{'text':a.get_text(' ',strip=True),'url':a['href']} for a in s.find_all('a',href=True) if any(k in a['href'] for k in ['/firm/','directions','tel:','menu','instagram','taplink'])])
 except urllib.error.HTTPError as e:out.update(http_status=e.code,error=str(e))
 except Exception as e:out.update(error=type(e).__name__+': '+str(e))
 print(u,out.get('http_status'),flush=True);return out
with ThreadPoolExecutor(max_workers=4) as p:out=list(p.map(fetch,urls))
(HERE/'discovery-cards.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
