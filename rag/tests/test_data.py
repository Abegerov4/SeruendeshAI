import json
import unittest
from pathlib import Path
from data.collect.normalize import normalize, ALLOWED

class DatasetTests(unittest.TestCase):
    def test_contract(self):
        rows = json.loads((Path(__file__).resolve().parents[2] / 'data/processed/pois.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(rows), 300)
        self.assertEqual(len(rows), len({p['id'] for p in rows}))
        for p in rows:
            self.assertIn(p['category'], ALLOWED)
            self.assertTrue(51.05 <= p['lat'] <= 51.25 and 71.25 <= p['lon'] <= 71.60)
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
        self.assertEqual(len(normalize(rows)), 2)

if __name__ == '__main__':
    unittest.main()
