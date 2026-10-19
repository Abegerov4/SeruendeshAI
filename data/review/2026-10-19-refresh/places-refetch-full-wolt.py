"""Bounded free public refetch of already bound Wolt branches; preserve raw bytes."""
import asyncio
import json
from pathlib import Path

from data.catalog_audit import PublicFetcher

HERE=Path(__file__).parent
ROOT=HERE.parents[2]
CACHE=HERE/'places-wolt-full-cache'
SOURCE=ROOT/'data/sources/place_details_2026-10-19.json'

async def main():
    payload=json.loads(SOURCE.read_text())
    records=[r for r in payload['records'] if r['menu_items'] and 'wolt.com' in r['identity']['source_url']]
    results=[]
    async with PublicFetcher(CACHE,concurrency=4,timeout=35,delay=.8,max_bytes=12_000_000) as fetcher:
        async def one(record):
            fetched=await fetcher.fetch(record['identity']['source_url'])
            output={k:v for k,v in fetched.items()if k!='extracted'}
            output['canonical_id']=record['canonical_id']
            if output.get('raw_cache'):
                output['raw_cache']=str(Path(output['raw_cache']).relative_to(ROOT))
            results.append(output)
            (HERE/'places-wolt-full-fetches.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
            print(record['identity']['source_url'].rsplit('/',1)[-1],fetched.get('status'),fetched.get('http_status'),flush=True)
        await asyncio.gather(*(one(record)for record in records))
    print('completed',len(results),flush=True)

if __name__=='__main__':asyncio.run(main())
