"""Measure the primary document retriever, without intent/planning/generation.

The exact runtime text_relevance fusion is used. This measures document retrieval,
not final recommendation utility. The holdout's unjudged results stay unjudged.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

import numpy as np

from ayat_backend.app.store import load_store
from ayat_backend.app.embedder import get_embedder
from ayat_backend.app.retrieval import text_relevance
from ayat_backend.app.geo import hav_m
from ayat_backend.app.categories import CONTRACT_CATEGORY
from rag.evaluate import _case, _id_index, _metrics
from eval.run_eval import file_sha256, source_fingerprint


def wilson(hits, n):
    if not n: return None
    z=1.96; p=hits/n; c=1+z*z/n; center=(p+z*z/(2*n))/c; half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/c
    return [center-half, center+half]


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('golden',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    start=time.perf_counter();store=load_store('e5-small');encoder=get_embedder('e5-small');startup=time.perf_counter()-start
    if store.emb is None or encoder is None: raise RuntimeError('Real matching dense index/model required')
    document=json.loads(a.golden.read_text());rows=document['queries'];index=_id_index(store.pois);report={'runtime_id':'ayat','scope':'primary_document_retrieval_only_no_intent_planner_generation','golden_sha256':file_sha256(a.golden),'snapshot_version':store.manifest['snapshot_version'],'canonical_sha256':store.manifest['canonical_sha256'],'source_sha256':source_fingerprint(Path.cwd()),'model':'e5-small','startup_seconds':startup,'judgments':'Unlisted results are unjudged; hit/recall use frozen positive labels, not precision.','modes':{}}
    for mode in ['bm25','dense','hybrid']:
        durations=[]
        def search(query,lat,lon,radius_m,categories,top_k):
            t0=time.perf_counter();qvec=encoder.query(query) if mode!='bm25' else None
            bm,rrf=text_relevance(store,query,qvec);score=bm if mode=='bm25' else store.emb@qvec if mode=='dense' else rrf
            allowed=np.ones(store.size,dtype=bool)
            if lat is not None: allowed &= hav_m(lat,lon,store.lat,store.lon)<=radius_m
            if categories is not None: allowed &= np.array([p['category'] in categories or CONTRACT_CATEGORY.get(p['category']) in categories for p in store.pois])
            order=[int(i) for i in np.argsort(-score) if allowed[i]][:top_k]
            durations.append((time.perf_counter()-t0)*1000)
            return [store.pois[i] for i in order]
        seen=set();cases=[_case(row,i,store.pois,index,SimpleNamespace(search=search),seen) for i,row in enumerate(rows,1)]
        for row in cases: row.pop('retrieved',None)
        metrics=_metrics(cases);metrics['hit_at_5_wilson95']=wilson(metrics['hit_cases'],metrics['evaluated_cases']);metrics['latency_ms']={'p50':statistics.median(durations),'p95':float(np.percentile(durations,95)),'max':max(durations)}
        report['modes'][mode]={'summary':metrics,'cases':cases}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v['summary'] for k,v in report['modes'].items()},ensure_ascii=False))
    return int(any(v['summary']['error_cases'] for v in report['modes'].values()))
if __name__=='__main__':raise SystemExit(main())
