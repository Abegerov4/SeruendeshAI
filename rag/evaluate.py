"""Evaluate QA golden JSON directly against search; no generated answers involved."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag import search, resolve_landmark

def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('golden', type=Path)
    args = parser.parse_args()
    rows = json.loads(args.golden.read_text(encoding='utf-8'))
    hits, total = 0, 0
    for row in rows:
        expected = set(row.get('expect', {}).get('must_include_any', []))
        if not expected:
            continue
        location = row.get('location') or resolve_landmark(row['query']) or {}
        result = search(row['query'], location.get('lat'), location.get('lon'),
                        radius_m=row.get('radius_m', 2500), top_k=5)
        hit = bool(expected.intersection(p['id'] for p in result))
        hits += hit
        total += 1
        print(json.dumps({'id': row['id'], 'hit_at_5': hit, 'retrieved': [p['id'] for p in result]}, ensure_ascii=False))
    print(json.dumps({'cases': total, 'recall_at_5_any_expected': hits/total if total else None}))
    if not total:
        raise SystemExit('No golden cases with expected POI IDs')

if __name__ == '__main__':
    main()
