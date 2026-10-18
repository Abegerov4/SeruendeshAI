import io
import json
from pathlib import Path
from unittest.mock import patch
import zipfile
import pytest


def row(ident, name, feature_class='S', feature_code='HTL', lat='51.13', lon='71.43', aliases=''):
    return '\t'.join([str(ident), name, 'ASCII name', aliases, lat, lon, feature_class, feature_code,
                      'KZ', '', '05', '', '', '', '0', '', '350', 'Asia/Almaty', '2025-03-04'])


def archive(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as file:
        file.writestr('KZ.txt', text)
    return output.getvalue()


def test_parser_keeps_named_physical_places_and_real_aliases_without_language_guessing():
    from data.collect import geonames as geo
    text = '\n'.join([row(1, 'Бәйтерек', feature_code='TOWR', aliases='Байтерек,Bayterek'),
                      row(2, 'Museum', feature_code='MUS'), row(3, 'Park', 'L', 'PRK'),
                      row(4, 'Airport', feature_code='AIRP'), row(5, 'Hotel')])
    pois, report = geo.parse_dump(io.StringIO(text), (51.0, 71.2, 51.3, 71.7))
    assert len(pois) == 5
    tower = pois[0]
    assert tower['id'] == 'geonames:1'
    assert tower['name'] == 'Бәйтерек'
    assert set(tower['aliases']) == {'ASCII name', 'Байтерек', 'Bayterek'}
    assert tower['name_en'] is None and tower['name_kk'] is None
    assert tower['source_updated_at'] == '2025-03-04'
    assert tower['source_license'] == 'CC-BY-4.0'
    assert tower['source_url'] == 'https://www.geonames.org/1/'
    assert tower['description'] is None and tower['rating'] is None
    assert [p['category'] for p in pois] == ['other', 'museum', 'park', 'other', 'other']
    assert tower['raw_taxonomy']['feature'] == 'S.TOWR'
    assert tower['opening_hours'] is None
    assert report['raw_count'] == 5


def test_parser_excludes_nonfacilities_outside_invalid_abandoned_and_unnamed():
    from data.collect import geonames as geo
    text = '\n'.join([row(1, 'City', 'P', 'PPL'), row(2, 'Region', 'A', 'ADM1'),
        row(3, 'Lake', 'H', 'LK'), row(4, 'Outside', lat='52.0'), row(5, 'Bad', lat='nan'),
        row(6, 'Abandoned station', feature_code='RSTNQ'), row(7, ''), 'bad\trow',
        row(8, 'Station', feature_code='RSTN')])
    pois, report = geo.parse_dump(io.StringIO(text), (51.0, 71.2, 51.3, 71.7))
    assert [p['id'] for p in pois] == ['geonames:8']
    assert sum(report['rejected'].values()) == 8


def test_collect_uses_complete_country_zip_cache_and_preserves_stale_on_outage(tmp_path):
    from data.collect import geonames as geo
    payload = archive('\n'.join(row(i, f'Hotel {i}') for i in range(1301)))
    metadata = {'source_url': geo.SOURCE_URL, 'http_status': 200, 'last_modified': 'Sun, 18 Oct 2026 02:00:00 GMT'}
    with patch.object(geo, '_request_country', return_value=(payload, metadata)):
        first = geo.collect(tmp_path, bbox=(51.0, 71.2, 51.3, 71.7))
    assert len(first['pois']) == 1301
    assert (tmp_path / 'KZ.zip').exists()
    assert json.loads((tmp_path / 'candidates.json').read_text()) == first['pois']
    with patch.object(geo, '_request_country', side_effect=AssertionError('Cache missed')):
        cached = geo.collect(tmp_path, bbox=(51.0, 71.2, 51.3, 71.7))
    assert cached['pois'] == first['pois']
    with patch.object(geo, '_request_country', side_effect=OSError('Unavailable')):
        stale = geo.collect(tmp_path, bbox=(51.0, 71.2, 51.3, 71.7), refresh=True)
    assert stale['pois'] == first['pois']
    assert stale['report']['status'] == 'partial' and stale['report']['stale_cache']
    assert stale['report']['errors']


def test_country_outage_and_invalid_bbox_return_honest_failure(tmp_path):
    from data.collect import geonames as geo
    with patch.object(geo, '_request_country', side_effect=OSError('Unavailable')):
        result = geo.collect(tmp_path)
    assert result['pois'] == [] and result['report']['status'] == 'unavailable'
    assert not (tmp_path / 'candidates.json').exists()
    with pytest.raises(ValueError):
        geo.collect(tmp_path, bbox=(52.0, 71.2, 51.3, 71.7))
