"""python data/run_pipeline.py [--refresh] [--skip-wiki]"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.collect.osm_overpass import collect
from data.collect.normalize import normalize
from data.collect.enrich_wiki import description as wiki_description
from data.collect.enrich_llm import description as generated_description

def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--skip-wiki', action='store_true')
    args = parser.parse_args()
    rows = normalize(collect(args.refresh))
    print(f'Normalized {len(rows)} POIs', flush=True)
    pois = []
    for poi, tags in rows:
        if not poi['description'] and not args.skip_wiki:
            poi['description'] = wiki_description(tags)
            if poi['description']:
                poi['description_source'] = 'wikipedia'
        if not poi['description']:
            poi['description'] = generated_description(poi)
            poi['description_source'] = 'llm_generated'
        pois.append(poi)
    if not pois:
        raise RuntimeError('Empty source: refusing to replace dataset')
    output = ROOT / 'data/processed/pois.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(pois, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(output)
    counts = Counter(p['category'] for p in pois)
    lines = ['# Dataset statistics', '', f'POIs: {len(pois)}; updated: {pois[0]["updated_at"]}', '', '| Category | Count |', '|---|---:|']
    lines += [f'| {k} | {v} |' for k, v in sorted(counts.items())]
    lines += ['', '| Field | Coverage |', '|---|---:|']
    for field in ('description', 'opening_hours', 'wheelchair', 'rating'):
        lines.append(f'| {field} | {100 * sum(p[field] is not None for p in pois) / len(pois):.1f}% |')
    lines += ['', 'Description sources: ' + str(dict(Counter(p['description_source'] for p in pois))), '',
              'Generated descriptions are category-only LLM-authored templates, not verified editorial descriptions.',
              'No ratings or quietness are inferred. Unknown child suitability is null.',
              '© OpenStreetMap contributors — https://www.openstreetmap.org/copyright (ODbL).',
              'Wikipedia extracts, when present: CC BY-SA; linked article identifiers remain in tags.',
              'QA golden Recall@5: not measured until the independent QA set is available.']
    (ROOT / 'data/stats.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Saved {len(pois)} POIs to {output}', flush=True)

if __name__ == '__main__':
    main()
