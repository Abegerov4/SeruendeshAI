import json
import unittest
from pathlib import Path
from shapely.geometry import Point, shape

from data.collect.normalize import normalize_candidates, CATEGORIES
from data.collect.osm_overpass import parse_elements

class DatasetTests(unittest.TestCase):
    def test_contract(self):
        rows = json.loads((Path(__file__).resolve().parents[2] / 'data/processed/pois.json').read_text(encoding='utf-8'))
        boundary = json.loads((Path(__file__).resolve().parents[2] / 'data/processed/boundary.geojson').read_text(encoding='utf-8'))
        geometry = shape(boundary.get('geometry', boundary))
        self.assertTrue(geometry.is_valid and not geometry.is_empty)
        self.assertGreaterEqual(len(rows), 300)
        self.assertEqual(len(rows), len({p['id'] for p in rows}))
        for p in rows:
            self.assertIn(p['category'], CATEGORIES)
            self.assertTrue(geometry.covers(Point(p['lon'], p['lat'])), p['id'])
            self.assertTrue(p['name'])
            self.assertIn(p['description_source'], ('osm', 'wikipedia', 'website', 'llm_generated'))
            self.assertIn(p['wheelchair'], ('yes', 'no', 'limited', None))
            self.assertIsNone(p['rating'])

    def test_dedup_missing_name_and_coordinates(self):
        rows = [
            dict(type='node', id=1, lat=51.1, lon=71.4, tags={'name': 'Cafe A', 'amenity': 'cafe'}),
            dict(type='way', id=2, center={'lat': 51.10001, 'lon': 71.4}, tags={'name': 'cafe a', 'amenity': 'cafe'}),
            dict(type='node', id=3, lat=51.2, lon=71.4, tags={'name': 'Cafe A', 'amenity': 'cafe'}),
            dict(type='node', id=4, lat=51.1, lon=71.4, tags={'amenity': 'cafe'}),
            dict(type='node', id=5, tags={'name': 'Missing coordinates', 'amenity': 'cafe'}),
        ]
        candidates, rejected = parse_elements({'elements': rows})
        normalized, _ = normalize_candidates(candidates)
        self.assertEqual(len(normalized), 2)
        self.assertEqual({p['id'] for p in normalized}, {'osm:node/1', 'osm:node/3'})
        self.assertEqual(rejected, {'unnamed': 1, 'invalid_coordinates': 1})

if __name__ == '__main__':
    unittest.main()
