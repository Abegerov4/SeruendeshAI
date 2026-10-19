"""Uncapped named physical Astana facilities from the full GeoNames KZ dump.

GeoNames gazetteer data is CC BY 4.0. The primary license and 19-field schema
are documented at https://download.geonames.org/export/dump/readme.txt.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen
import zipfile

SOURCE_URL = 'https://download.geonames.org/export/dump/KZ.zip'
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'
SCHEMA_URL = 'https://download.geonames.org/export/dump/readme.txt'
DEFAULT_BBOX = (50.8, 71.0, 51.4, 71.9)
FIELDS = ('geonameid', 'name', 'asciiname', 'alternatenames', 'latitude', 'longitude',
          'feature_class', 'feature_code', 'country_code', 'cc2', 'admin1_code',
          'admin2_code', 'admin3_code', 'admin4_code', 'population', 'elevation',
          'dem', 'timezone', 'modification_date')
NATURE_CODES = {'L.PRK', 'L.RESF', 'L.RESN', 'L.RESW'}
CATEGORIES = {'S.MUS': 'museum', 'S.LIBR': 'library', 'S.THTR': 'theatre',
              'S.OBPT': 'viewpoint', 'S.MNMT': 'monument',
              'S.HSTS': 'attraction', 'S.RUIN': 'attraction', 'S.ZOO': 'attraction',
              **{feature: 'park' for feature in NATURE_CODES}}


def _bbox(value):
    value = tuple(value or DEFAULT_BBOX)
    if len(value) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value):
        raise ValueError('bbox must have four finite numbers in south,west,north,east order')
    south, west, north, east = value
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError('bbox coordinates are invalid')
    return value


def parse_dump(lines, bbox=None):
    """Parse all 19-field UTF-8 records; retain facilities, parks and reserves."""
    south, west, north, east = _bbox(bbox)
    pois, rejected = {}, Counter()
    raw_count = bbox_count = 0
    for line in lines:
        if not line.strip():
            continue
        raw_count += 1
        fields = line.rstrip('\r\n').split('\t')
        if len(fields) != 19:
            rejected['malformed_row'] += 1
            continue
        raw = dict(zip(FIELDS, fields))
        if not raw['geonameid'].isdigit() or not raw['name'].strip():
            rejected['missing_id_or_name'] += 1
            continue
        try:
            lat, lon = float(raw['latitude']), float(raw['longitude'])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError('invalid coordinates')
        except ValueError:
            rejected['invalid_coordinates'] += 1
            continue
        if not (south <= lat <= north and west <= lon <= east):
            rejected['outside_bbox'] += 1
            continue
        bbox_count += 1
        feature = raw['feature_class'] + '.' + raw['feature_code']
        if raw['country_code'] != 'KZ':
            rejected['outside_country'] += 1
            continue
        if (raw['feature_class'] != 'S' and feature not in NATURE_CODES) or raw['feature_code'].endswith('Q'):
            rejected['nonfacility_or_abandoned'] += 1
            continue
        aliases = sorted({name.strip() for name in [raw['asciiname'], *raw['alternatenames'].split(',')]
                          if name.strip() and name.strip() != raw['name'].strip()})
        try:
            updated = date.fromisoformat(raw['modification_date']).isoformat()
        except ValueError:
            updated = None
        ident = 'geonames:' + raw['geonameid']
        if ident in pois:
            rejected['duplicate_id'] += 1
        pois[ident] = {
            'id': ident, 'name': raw['name'].strip(), 'name_en': None, 'name_kk': None,
            'aliases': aliases, 'lat': lat, 'lon': lon, 'category': CATEGORIES.get(feature, 'other'),
            'tags': ['geonames:' + feature], 'raw_tags': raw, 'raw_taxonomy': {'feature': feature},
            'description': None, 'description_source': None, 'opening_hours': None,
            'phone': None, 'website': None, 'address': None, 'wheelchair': None,
            'kid_friendly': None, 'rating': None, 'rating_count': None,
            'source': 'geonames', 'source_url': f"https://www.geonames.org/{raw['geonameid']}/",
            'source_license': 'CC-BY-4.0', 'source_updated_at': updated,
        }
    return [pois[key] for key in sorted(pois, key=lambda key: int(key.split(':')[1]))], {
        'raw_count': raw_count, 'bbox_candidate_count': bbox_count, 'rejected': dict(rejected)}


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def _request_country():
    request = Request(SOURCE_URL, headers={'User-Agent': 'AstanaWalkAI-data-collector/1.0'})
    with urlopen(request, timeout=60) as response:
        status = response.status
        if status != 200:
            raise OSError(f'Unexpected GeoNames HTTP status {status}')
        payload = response.read()
        return payload, {'source_url': response.geturl(), 'http_status': status,
                         'last_modified': response.headers.get('Last-Modified'),
                         'etag': response.headers.get('ETag')}


def _validate_zip(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if 'KZ.txt' not in archive.namelist() or archive.testzip() is not None:
            raise ValueError('GeoNames ZIP lacks a complete valid KZ.txt')


def collect(raw_dir: Path, bbox: tuple | None = None, refresh: bool = False) -> dict:
    """Return all named physical candidates and a reproducible collection report."""
    bbox = _bbox(bbox)
    started = time.monotonic()
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive_path, metadata_path = raw_dir / 'KZ.zip', raw_dir / 'download.json'
    errors, stale, cached = [], False, False
    payload = metadata = None
    if archive_path.exists() and metadata_path.exists():
        try:
            payload = archive_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            _validate_zip(payload)
            if hashlib.sha256(payload).hexdigest() != metadata['sha256']:
                raise ValueError('Cached GeoNames ZIP checksum mismatch')
            cached = True
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            payload = metadata = None
    if payload is None or refresh:
        try:
            fresh, info = _request_country()
            _validate_zip(fresh)
            temporary = archive_path.with_suffix('.zip.tmp')
            temporary.write_bytes(fresh)
            temporary.replace(archive_path)
            payload = fresh
            metadata = {**info, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                        'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                        'license': 'CC-BY-4.0', 'license_url': LICENSE_URL, 'schema_url': SCHEMA_URL}
            _write_json(metadata_path, metadata)
            cached = False
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            errors.append({'source_url': SOURCE_URL, 'error': f'{type(error).__name__}: {error}'})
            stale = payload is not None
    if payload is not None:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive, archive.open('KZ.txt') as file:
            with io.TextIOWrapper(file, encoding='utf-8') as text:
                pois, parsed = parse_dump(text, bbox)
    else:
        pois, parsed = [], {'raw_count': 0, 'bbox_candidate_count': 0, 'rejected': {}}
        # Keep a prior usable export if the raw archive is temporarily missing.
        if (raw_dir / 'candidates.json').exists():
            pois = json.loads((raw_dir / 'candidates.json').read_text(encoding='utf-8'))
            stale = bool(pois)
    report = {
        'source': 'geonames', 'status': 'partial' if stale else 'ok' if payload is not None else 'unavailable',
        'count': len(pois), **parsed, 'bbox': list(bbox), 'bbox_order': 'south,west,north,east',
        'categories': dict(sorted(Counter(p['category'] for p in pois).items())),
        'source_urls': [SOURCE_URL, SCHEMA_URL], 'source_license': 'CC-BY-4.0',
        'license_url': LICENSE_URL, 'attribution': 'GeoNames (https://www.geonames.org/)',
        'collection_method': 'full_country_dump', 'record_limit': None, 'cached': cached,
        'stale_cache': stale, 'errors': errors, 'download': metadata,
        'collected_at': metadata.get('retrieved_at') if metadata else datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'notes': ['All country rows inspected; only named class-S facilities and explicit parks/nature reserves retained.',
                  'Administrative areas, settlements, roads and generic water features excluded. Root normalization clips the actual administrative polygon.',
                  'ASCII and alternate names are aliases; their language is unknown in the country table.',
                  'GeoNames is supplied as-is; historic names, facility status and point positions may be stale. No descriptions, opening hours or ratings invented.'],
    }
    if payload is not None:
        _write_json(raw_dir / 'candidates.json', pois)
    _write_json(raw_dir / 'report.json', report)
    return {'pois': pois, 'report': report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw/geonames'))
    parser.add_argument('--bbox', type=float, nargs=4)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    result = collect(args.raw_dir, tuple(args.bbox) if args.bbox else None, args.refresh)
    print(json.dumps(result['report'], ensure_ascii=False, indent=2))
    return 1 if result['report']['status'] == 'unavailable' else 0


if __name__ == '__main__':
    raise SystemExit(main())
