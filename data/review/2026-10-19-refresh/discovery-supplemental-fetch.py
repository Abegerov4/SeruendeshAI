import urllib.request,urllib.error,hashlib,json,re
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
base=Path(__file__).parent
urls=['https://gasteria-mega-silk-way.kamiqr.com/menu/at-place','https://gasteria-mega-silk-way.kamiqr.com/menu/at-place/list','https://astana.restoran.kz/coffee/102604-gasteria-mega-silk-way','https://yandex.kz/maps/ru/org/mon_plaisir/178386407450/','https://www.bizkontakte.com/KZ/tatti-latte']
out=[]
for u in urls:
 x={'source_url':u,'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:b=r.read();x.update(http_status=r.status,final_url=r.url)
  sha=hashlib.sha256(b).hexdigest();p=base/'discovery-cache'/('supp-'+sha[:16]+'.html');p.write_bytes(b)
  s=BeautifulSoup(b,'html.parser');text=re.sub(r'(?:\.\s*){5,}',' ',s.get_text(' ',strip=True));x.update(response_sha256=sha,archive_path=str(p),text_excerpt=text[-24000:])
  print(u,x['http_status'],text[-7000:],flush=True)
 except Exception as e:x.update(error=str(e));print(u,str(e),flush=True)
 out.append(x)
(base/'discovery-supplemental.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
