import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from rag.geo import haversine_m, resolve_landmark
from rag.hours import open_status

class HoursTests(unittest.TestCase):
    def test_cases(self):
        cases = [
            (None, '2026-10-19T12:00', 'unknown'),
            ('24/7', '2026-10-19T02:00', 'open'),
            ('Mo-Su 10:00-22:00', '2026-10-19T10:00', 'open'),
            ('Mo-Su 10:00-22:00', '2026-10-19T22:00', 'closed'),
            ('Mo-Fr 10:00-22:00; Sa-Su 12:00-18:00', '2026-10-18T11:00', 'closed'),
            ('Fr 22:00-02:00', '2026-10-17T01:00', 'open'),
            ('Su 22:00-02:00', '2026-10-19T01:00', 'open'),
            ('Mo-Su 10:00-22:00; PH off', '2026-10-19T12:00', 'unknown'),
            ('Mo 10:00-25:00', '2026-10-19T12:00', 'unknown'),
            ('Mo 10:00-12:00,14:00-18:00', '2026-10-19T13:00', 'closed'),
            ('Mo-Su 10:00-22:00; Mo off', '2026-10-19T12:00', 'closed'),
            ('Mo 10:00-22:00', '2026-10-19T05:00+00:00', 'open'),
        ]
        for hours, date, expected in cases:
            with self.subTest(hours=hours, date=date):
                self.assertEqual(open_status(hours, datetime.fromisoformat(date)),
                                 (expected, 'none' if expected == 'unknown' else 'high'))

class GeoTests(unittest.TestCase):
    def test_distance(self):
        self.assertEqual(haversine_m(51, 71, 51, 71), 0)
        self.assertAlmostEqual(haversine_m(0, 0, 0, 1), 111195, delta=1)
        self.assertEqual(haversine_m(1, 2, 3, 4), haversine_m(3, 4, 1, 2))
        with self.assertRaises(ValueError):
            haversine_m(float('nan'), 1, 2, 3)

class RetrievalTests(unittest.TestCase):
    @patch.dict(os.environ, {'RAG_SEARCH_MODE': 'bm25'})
    def test_landmark_aliases(self):
        from rag.retriever import search
        for query in ('Байтерек', 'Бәйтерек', 'Bayterek'):
            self.assertEqual(search(query, None, None, top_k=1)[0]['id'], 'osm:way/230401645')

    @patch.dict(os.environ, {'RAG_SEARCH_MODE': 'hybrid'})
    def test_dense_receives_only_geo_candidates(self):
        from rag.retriever import search
        def dense(query, pois, indices, digest):
            self.assertTrue(indices)
            self.assertTrue(all(pois[i]['category'] == 'cafe' and haversine_m(51.128, 71.430, pois[i]['lat'], pois[i]['lon']) <= 1500 for i in indices))
            return list(reversed(indices))[:30]
        with patch('rag.retriever._dense', side_effect=dense) as mocked:
            rows = search('кофе', 51.128, 71.430, 1500, ['cafe'], top_k=5)
            self.assertEqual(len(rows), 5)
            mocked.assert_called_once()

    @patch.dict(os.environ, {'RAG_SEARCH_MODE': 'bm25'})
    def test_geo_and_category(self):
        from rag.retriever import search
        rows = search('кофе тихо', 51.128, 71.430, 1500, ['cafe'])
        self.assertTrue(rows)
        self.assertTrue(all(p['distance_m'] <= 1500 and p['category'] == 'cafe' for p in rows))
        self.assertEqual([p['score'] for p in rows], sorted([p['score'] for p in rows], reverse=True))
        self.assertEqual(search('кофе', None, None, categories=[]), [])

if __name__ == '__main__':
    unittest.main()
