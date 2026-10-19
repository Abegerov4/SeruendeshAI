#!/usr/bin/env python3
"""Resumable public-source candidate discovery; never modifies or excludes POIs.

Examples:
  .venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --prepare-only
  .venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --limit 30 --max-requests 90

Sources are ordinary public HTML pages. Captchas/403/429 immediately trip a
persistent provider circuit. Skips and 404s are incomplete, never no-information.
A discovery result needs a separate branch/fact review before publication.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import difflib,hashlib,json,math,re,time
from pathlib import Path
import urllib.parse,urllib.request,urllib.error
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PROVIDERS=('2gis','bing','yandex_maps')
POLICY={'min_distinct_successful_sources_before_no_information':3,
        'minimum_successful_sources_is_not_exhaustiveness':True,
        'no_information_requires_explicit_completed_human_source_review':True,
        'source_error_or_block_means_incomplete':True,
        'closure_requires_explicit_source_statement_and_exact_branch_identity':True,
        'automatic_acceptance':False,'automatic_exclusion':False,
        'exact_branch_max_coordinate_distance_m':200,
        'name_and_address_or_coordinates_required':True}
UA='Mozilla/5.0'

def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(value).hexdigest()
def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def read(path,default):return json.loads(path.read_text()) if path.exists() else default
def norm(value):
    value=str(value).lower().replace('ё','е')
    return re.sub(r'[^a-zа-яәіңғүұқөһ0-9]+',' ',value).strip()
def distance(row):
    lat,lon=row['lat'],row['lon']
    a=math.sin(math.radians(lat-51.092788)/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(51.092788))*math.sin(math.radians(lon-71.421482)/2)**2
    return 2*6371000*math.asin(min(1,math.sqrt(a)))
def source_url(provider,row):
    name=row['name']
    address=row.get('address') or ''
    query=' '.join([name,address,'Астана']).strip()
    if provider=='2gis':return 'https://2gis.kz/astana/search/'+urllib.parse.quote(name),query
    if provider=='bing':return 'https://www.bing.com/search?'+urllib.parse.urlencode({'q':query}),query
    return 'https://yandex.kz/maps/163/astana/?'+urllib.parse.urlencode({'text':query}),query

def assess(response):
    status=response.get('http_status')
    text=response.get('text_excerpt','').lower()
    block=any(s in text for s in ('unusual traffic','verify you are human','complete the following challenge','подтвердите, что вы не робот','подтвердите, что запросы отправляли вы','доступ ограничен','showcaptcha','captcha challenge'))
    if status in (403,429) or block:return 'blocked'
    if status!=200 or response.get('error'):return 'incomplete_source_error'
    # A page without discovered links remains a successful provider search whose
    # meaning must be inspected; this is never evidence of branch closure.
    return 'candidates_found' if response.get('candidates') else 'search_returned_no_candidates'

def candidates(provider,soup,url,row):
    result=[];seen=set()
    if provider=='2gis':
        anchors=[a for a in soup.find_all('a',href=True) if '/firm/' in a['href']]
    elif provider=='bing':
        anchors=soup.select('li.b_algo h2 a')
        if not anchors:anchors=soup.select('#b_results h2 a')
    else:
        anchors=[a for a in soup.find_all('a',href=True) if '/org/' in a['href']]
    for a in anchors:
        target=urllib.parse.urljoin(url,a['href'])
        if urllib.parse.urlsplit(target).scheme not in ('http','https') or target in seen:continue
        seen.add(target);title=a.get_text(' ',strip=True)
        context=a.parent.get_text(' ',strip=True)[:1600] if a.parent else title
        score=round(difflib.SequenceMatcher(None,norm(row['name']),norm(title)).ratio(),3)
        result.append({'source_url':target,'source_title':title,'excerpt':context,
            'name_similarity_for_triage_only':score,'identity_status':'unreviewed',
            'accepted':False,'canonical_address':row.get('address'),
            'review_required':['exact branch name','exact address or independent coordinates <=200m','current status/date','field-specific source excerpt']})
    return result[:20]

def fetch(provider,row,cache,*,timeout):
    url,query=source_url(provider,row)
    result={'provider':provider,'source_url':url,'query':query,'checked_at':now(),'canonical_id':row['id'],'actual_request':True}
    try:
        request=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ru,en;q=0.7'})
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read(3_000_001);result.update(http_status=response.status,final_url=response.url)
        if len(raw)>3_000_000:result['error']='response_size_limit_exceeded'
        sha=digest(raw);archive=cache/(sha+'.html');archive.write_bytes(raw)
        soup=BeautifulSoup(raw,'html.parser')
        for tag in soup(['script','style']):tag.decompose()
        text=re.sub(r'(?:\.\s*){5,}',' ',soup.get_text(' ',strip=True))
        result.update(response_sha256=sha,archive_path=str(archive.relative_to(ROOT)),
            text_excerpt=text[:18000],candidates=candidates(provider,soup,url,row))
    except urllib.error.HTTPError as exc:
        result.update(http_status=exc.code,error=str(exc),candidates=[])
    except Exception as exc:result.update(error=type(exc).__name__+': '+str(exc),candidates=[])
    result['outcome']=assess(result)
    return result

def summary(rows,events):
    by_id={}
    for event in events:by_id.setdefault(event['canonical_id'],{})[event['provider']]=event
    counts=Counter();items=[]
    for row in rows:
        evidence=by_id.get(row['id'],{})
        succeeded=[p for p,e in evidence.items() if e['outcome'] in ('candidates_found','search_returned_no_candidates')]
        actual=[p for p,e in evidence.items() if e.get('actual_request')]
        pending=[p for p in PROVIDERS if p not in succeeded]
        review=row.get('source_review') or {}
        no_information=(len(succeeded)>=3 and review.get('completed') is True
            and review.get('outcome')=='no_information' and bool(review.get('reviewed_by'))
            and bool(review.get('reviewed_at')) and bool(review.get('evidence_urls')))
        state='reviewed_no_information' if no_information else 'candidate_review_required' if len(succeeded)>=3 else 'incomplete_source_checks'
        counts[state]+=1
        items.append({'canonical_id':row['id'],'name':row['name'],'address':row.get('address'),
            'outcome':state,'actual_distinct_providers_attempted':len(actual),
            'successful_distinct_providers':len(succeeded),'pending_or_failed_providers':pending,
            'candidate_count':sum(len(e.get('candidates',[])) for e in evidence.values()),
            'no_information_confirmed':no_information,'closed_confirmed':False})
    return {'generated_at':now(),'policy':POLICY,'rows':len(rows),'counts':dict(counts),
            'actual_requests':sum(bool(e.get('actual_request')) for e in events),
            'event_outcomes':dict(Counter(e['outcome'] for e in events)),
            'coverage_note':'Candidate discovery is not fact verification or an exhaustive no-information review.',
            'records':items}

def prepare(canonical,excluded_paths,out):
    raw=canonical.read_bytes();exclude=set()
    for path in excluded_paths:
        exclude.update(r['canonical_id'] for r in read(path,{}).get('records',[]))
    selected=[r for r in json.loads(raw) if r.get('category') in ('cafe','restaurant')
              and not r.get('website') and r['id'] not in exclude]
    selected.sort(key=distance)
    rows=[{'id':r['id'],'name':r['name'],'address':r.get('address'),'lat':r['lat'],'lon':r['lon'],
           'category':r['category'],'distance_expo_m':round(distance(r)),
           'row_sha256':digest(json.dumps(r,sort_keys=True,ensure_ascii=False).encode())} for r in selected]
    previous=read(out/'discovery-queue.json',{})
    old={r['id']:r for r in previous.get('records',[])}
    for row in rows:
        if old.get(row['id'],{}).get('row_sha256')==row['row_sha256'] and old[row['id']].get('source_review'):
            row['source_review']=old[row['id']]['source_review']
    payload={'schema_version':1,'prepared_at':now(),'canonical_path':str(canonical),
        'canonical_sha256':digest(raw),'policy':POLICY,'excluded_accepted_records':len(exclude),
        'records':rows}
    dump(out/'discovery-queue.json',payload)
    return payload

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical',type=Path,default=ROOT/'data/processed/pois.json')
    parser.add_argument('--exclude',type=Path,action='append')
    parser.add_argument('--output-dir',type=Path,default=HERE)
    parser.add_argument('--limit',type=int,default=30,help='Rows considered this invocation, nearest EXPO first')
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--max-requests',type=int,default=90)
    parser.add_argument('--timeout',type=float,default=20)
    parser.add_argument('--delay',type=float,default=1.0,help='Minimum seconds between requests; no parallel host traffic')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--retry-incomplete',action='store_true',help='Retry ordinary source errors; persistent provider blocks are still respected')
    parser.add_argument('--providers',nargs='+',choices=PROVIDERS,default=list(PROVIDERS))
    args=parser.parse_args()
    if args.limit<0 or args.offset<0 or args.max_requests<0 or args.delay<0.5:parser.error('Invalid bounds; minimum delay is0.5sec')
    out=args.output_dir.resolve();out.mkdir(exist_ok=True,parents=True)
    cache=out/'discovery-queue-cache';cache.mkdir(exist_ok=True)
    excluded=args.exclude or [ROOT/'data/sources/place_details_2026-10-19.json',ROOT/'data/sources/place_details_discovery_2026-10-19.json']
    queue=prepare(args.canonical,excluded,out);rows=queue['records']
    ledger=out/'discovery-queue-events.jsonl'
    events=[json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    # A changed canonical row invalidates old discovery attempts for that row.
    current={r['id']:r['row_sha256'] for r in rows}
    relevant=[e for e in events if e.get('row_sha256')==current.get(e['canonical_id'])]
    if args.prepare_only:
        dump(out/'discovery-queue-summary.json',summary(rows,relevant));print('prepared',len(rows));return
    host_state=read(out/'discovery-queue-host-state.json',{})
    latest={(e['canonical_id'],e['provider']):e for e in relevant}
    done={key for key,e in latest.items() if not args.retry_incomplete or e['outcome'] not in ('incomplete_source_error','skipped_provider_block')}
    actual=0
    for row in rows[args.offset:args.offset+args.limit]:
        for provider in args.providers:
            if (row['id'],provider) in done:continue
            block=host_state.get(provider)
            if block:
                event={'canonical_id':row['id'],'provider':provider,'checked_at':now(),'actual_request':False,
                    'outcome':'skipped_provider_block','blocked_since':block['blocked_at'],
                    'reason':'Provider access block remains unresolved; no retry or alternate route attempted.',
                    'candidates':[],'row_sha256':row['row_sha256']}
            else:
                if actual>=args.max_requests:break
                event=fetch(provider,row,cache,timeout=args.timeout);event['row_sha256']=row['row_sha256'];actual+=1
                if event['outcome']=='blocked':
                    host_state[provider]={'blocked_at':event['checked_at'],'source_url':event['source_url'],
                        'http_status':event.get('http_status'),'outcome':'blocked'}
                    dump(out/'discovery-queue-host-state.json',host_state)
                time.sleep(args.delay)
            with ledger.open('a') as handle:handle.write(json.dumps(event,ensure_ascii=False)+'\n')
            events.append(event);relevant.append(event);done.add((row['id'],provider))
            print(row['id'],provider,event['outcome'],len(event.get('candidates',[])),flush=True)
        if actual>=args.max_requests:break
    report=summary(rows,relevant);dump(out/'discovery-queue-summary.json',report)
    print('rows',len(rows),'requests_this_run',actual,'counts',report['counts'],flush=True)
if __name__=='__main__':main()
