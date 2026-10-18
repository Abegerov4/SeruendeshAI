"""Behavior tests for uncapped, attributed OSM collection (no live API calls)."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def collector():
    try:
        return importlib.import_module("data.collect.osm_overpass")
    except ModuleNotFoundError:
        return None


class OSMTests(unittest.TestCase):
    def setUp(self):
        self.osm = collector()
        self.assertIsNotNone(self.osm, "The OSM collector has not been implemented")

    def test_named_ways_and_localized_names_keep_source_facts(self):
        pois, rejected = self.osm.parse_elements({"elements": [
            {"type": "way", "id": 12, "center": {"lat": 51.12, "lon": 71.43},
             "tags": {"name:kk": "Саябақ", "name:en": "Garden", "leisure": "garden",
                      "description": "Public botanic collection.", "opening_hours": "24/7",
                      "wheelchair": "limited", "addr:street": "Көше", "addr:housenumber": "5",
                      "contact:phone": "+7 123", "contact:website": "https://example.org"}},
            {"type": "relation", "id": 44, "center": {"lat": 51.10, "lon": 71.4},
             "tags": {"name": "Museum", "tourism": "museum"}},
        ]})
        self.assertEqual(rejected, {})
        self.assertEqual([p["id"] for p in pois], ["osm:relation/44", "osm:way/12"])
        garden = pois[1]
        self.assertEqual((garden["name"], garden["name_kk"], garden["name_en"]),
                         ("Саябақ", "Саябақ", "Garden"))
        self.assertEqual((garden["category"], garden["lat"], garden["lon"]), ("park", 51.12, 71.43))
        self.assertEqual(garden["description_source"], "osm")
        self.assertEqual(garden["description"], "Public botanic collection.")
        self.assertEqual(garden["address"], "Көше, 5")
        self.assertEqual(garden["source_license"], "ODbL-1.0")
        self.assertEqual(garden["source_url"], "https://www.openstreetmap.org/way/12")
        self.assertEqual(garden["raw_tags"]["leisure"], "garden")
        self.assertEqual(garden["wheelchair"], "limited")
        self.assertEqual(garden["phone"], "+7 123")
        self.assertEqual(garden["website"], "https://example.org")
        self.assertIsNone(garden["kid_friendly"])
        self.assertIsNone(garden["rating"])

    def test_rejects_closed_unnamed_non_poi_and_invalid_locations(self):
        tags = [
            {"name": "Gone", "amenity": "cafe", "disused": "yes"},
            {"name": "Gone", "amenity": "cafe", "opening_hours": "closed"},
            {"name": "Gone", "disused:amenity": "cafe"},
            {"amenity": "cafe"},
            {"name": "Road", "highway": "residential"},
            {"name": "House", "building": "yes"},
            {"name": "Bad", "amenity": "cafe"},
            {"name": "Good", "amenity": "cafe", "wheelchair": "unknown"},
            {"name": "Closed now", "amenity": "cafe", "opening_hours": "Mo-Fr 09:00-18:00"},
            {"name": "Vacant", "shop": "vacant"},
        ]
        elements = [{"type": "node", "id": i, "lat": 95 if i == 6 else 51.1,
                     "lon": 71.4, "tags": t} for i, t in enumerate(tags)]
        pois, rejected = self.osm.parse_elements({"elements": elements})
        self.assertEqual([p["name"] for p in pois], ["Good", "Closed now"])
        self.assertEqual(sum(rejected.values()), 8)
        self.assertIsNone(pois[0]["wheelchair"])
        self.assertIsNone(pois[0]["description_source"])
        self.assertIsNone(pois[0]["description"])

    def test_broad_taxonomy_retains_all_records_and_deduplicates_osm_ids(self):
        elements = [{"type": "node", "id": i, "lat": 51.1, "lon": 71.4,
                     "tags": {"name": f"Shop {i}", "shop": "supermarket"}} for i in range(1201)]
        elements += [elements[0],
            {"type": "node", "id": 9001, "lat": 51.1, "lon": 71.4,
             "tags": {"name": "Airport", "aeroway": "aerodrome"}},
            {"type": "node", "id": 9002, "lat": 51.1, "lon": 71.4,
             "tags": {"name": "Play", "leisure": "playground"}},
        ]
        pois, _ = self.osm.parse_elements({"elements": elements})
        self.assertEqual(len(pois), 1203)
        self.assertEqual(next(p["category"] for p in pois if p["name"] == "Airport"), "other")
        self.assertTrue(next(p["kid_friendly"] for p in pois if p["name"] == "Play"))

    def test_boundary_assembles_reversed_outer_segments_and_inner_hole(self):
        def member(role, coordinates):
            return {"type": "way", "role": role,
                    "geometry": [{"lat": y, "lon": x} for x, y in coordinates]}
        payload = {"elements": [{"type": "relation", "id": 1,
            "tags": {"boundary": "administrative", "wikidata": "Q1520"}, "members": [
                member("outer", [(0, 0), (4, 0), (4, 4)]),
                member("outer", [(0, 0), (0, 4), (4, 4)]),
                member("inner", [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]),
                member("outer", [(5, 0), (6, 0), (6, 1), (5, 1), (5, 0)]),
            ]}]}
        boundary = self.osm.boundary_geometry(payload)
        self.assertEqual(boundary["type"], "MultiPolygon")
        self.assertEqual(len(boundary["coordinates"]), 2)
        self.assertEqual(sorted(len(p) for p in boundary["coordinates"]), [1, 2])
        self.assertEqual(self.osm.geometry_bbox(boundary), (0, 0, 4, 6))
        self.assertIsNone(self.osm.boundary_geometry({"elements": []}))

    def test_query_uses_uncapped_all_types_and_broad_name_tags(self):
        query = self.osm.poi_query((50.9, 71.0, 51.4, 71.9))
        self.assertIn("nwr", query)
        self.assertIn("shop", query)
        self.assertIn("amenity", query)
        self.assertIn("natural", query)
        self.assertIn("50.9,71.0,51.4,71.9", query)
        self.assertIn("out center", query)
        self.assertNotRegex(query, r"out[^;]*\b[1-9][0-9]*\s*;")

    def test_collect_cache_is_reproducible_and_outage_keeps_previous_data(self):
        boundary = {"elements": []}
        places = {"version": 0.6, "elements": [
            {"type": "node", "id": 1, "lat": 51.1, "lon": 71.4,
             "tags": {"name": "Cafe", "amenity": "cafe"}}]}
        def answer(query, endpoint):
            return boundary if "Q1520" in query else places
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            with patch.object(self.osm, "_request_overpass", side_effect=answer):
                first = self.osm.collect(raw_dir)
            self.assertEqual(len(first["pois"]), 1)
            self.assertTrue((raw_dir / "candidates.json").exists())
            self.assertEqual(json.loads((raw_dir / "candidates.json").read_text()), first["pois"])
            with patch.object(self.osm, "_request_overpass", side_effect=AssertionError("Cache missed")):
                cached = self.osm.collect(raw_dir)
            self.assertEqual(cached["pois"], first["pois"])
            with patch.object(self.osm, "_request_overpass", side_effect=OSError("Unavailable")), \
                 patch.object(self.osm.time, "sleep"):
                stale = self.osm.collect(raw_dir, refresh=True)
            self.assertEqual(stale["pois"], first["pois"])
            self.assertEqual(stale["report"]["status"], "partial")
            self.assertTrue(stale["report"]["errors"])
            self.assertTrue(stale["report"]["stale_cache"])

    def test_source_outage_returns_report_after_finite_sequential_attempts(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.osm, "_request_overpass", side_effect=OSError("Unavailable")) as request, \
             patch.object(self.osm.time, "sleep"):
            result = self.osm.collect(Path(directory))
        self.assertEqual(result["pois"], [])
        self.assertIsNone(result["boundary"])
        self.assertEqual(result["report"]["status"], "unavailable")
        self.assertEqual(request.call_count, 2 * len(self.osm.OVERPASS_ENDPOINTS))
        self.assertTrue(result["report"]["errors"])

    def test_lifecycle_tag_for_active_poi_key_excludes_known_disused_venue(self):
        pois, rejected = self.osm.parse_elements({"elements": [
            {"type": "node", "id": 10, "lat": 51.1, "lon": 71.4,
             "tags": {"name": "Gone", "amenity": "cafe", "disused:amenity": "cafe"}},
            {"type": "node", "id": 11, "lat": 51.1, "lon": 71.4,
             "tags": {"name": "Station cafe", "amenity": "cafe", "disused:railway": "station"}},
        ]})
        self.assertEqual([p["name"] for p in pois], ["Station cafe"])
        self.assertEqual(rejected, {"closed_or_inactive": 1})

    def test_incomplete_boundary_is_never_returned_as_complete_polygon(self):
        payload = {"elements": [{"type": "relation", "id": 1,
            "tags": {"boundary": "administrative", "wikidata": "Q1520"}, "members": [
                {"type": "way", "role": "outer", "geometry": [
                    {"lat": 0, "lon": 0}, {"lat": 0, "lon": 1},
                    {"lat": 1, "lon": 1}, {"lat": 0, "lon": 0}]},
                {"type": "way", "role": "outer", "ref": 2},
            ]}]}
        self.assertIsNone(self.osm.boundary_geometry(payload))

    def test_throttling_waits_at_least_thirty_seconds_before_next_instance(self):
        from urllib.error import HTTPError
        calls = []
        def request(query, endpoint):
            calls.append(endpoint)
            if len(calls) == 1:
                raise HTTPError(endpoint, 429, "Too Many Requests", {}, None)
            return {"elements": []}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.osm, "_request_overpass", side_effect=request), \
             patch.object(self.osm.time, "sleep") as sleep:
            result = self.osm.collect(Path(directory))
        self.assertEqual(result["report"]["status"], "partial")
        self.assertTrue(any(call.args[0] >= 30 for call in sleep.call_args_list))

    def test_local_osm_extract_recovers_boundary_and_node_way_relation_pois(self):
        xml = '''<?xml version="1.0"?><osm version="0.6" generator="test">
          <node id="1" lat="51.0" lon="71.0"/>
          <node id="2" lat="51.0" lon="71.8"/>
          <node id="3" lat="51.4" lon="71.8"/>
          <node id="4" lat="51.4" lon="71.0"/>
          <node id="5" lat="51.1" lon="71.4"><tag k="name" v="Cafe"/><tag k="amenity" v="cafe"/></node>
          <node id="6" lat="52.1" lon="71.4"><tag k="name" v="Outside"/><tag k="amenity" v="cafe"/></node>
          <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
          <way id="11"><nd ref="1"/><nd ref="2"/><tag k="name" v="Monument"/><tag k="historic" v="monument"/></way>
          <relation id="20"><member type="way" ref="10" role="outer"/>
            <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="wikidata" v="Q1520"/>
          </relation>
          <relation id="21"><member type="way" ref="10" role="outer"/>
            <tag k="type" v="multipolygon"/><tag k="name" v="Park"/><tag k="leisure" v="park"/>
          </relation>
          <relation id="22"><member type="way" ref="11" role=""/>
            <tag k="type" v="site"/><tag k="name" v="Campus library"/><tag k="amenity" v="library"/>
          </relation>
        </osm>'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "literal.osm"
            source.write_text(xml)
            result = self.osm.read_osm_file(source)
            raw_dir = Path(directory) / "cache"
            exported = self.osm.collect_file(source, raw_dir)
            self.assertEqual(exported["pois"], result["pois"])
            with patch.object(self.osm, "_request_overpass", side_effect=AssertionError("Local cache missed")):
                cached = self.osm.collect(raw_dir)
            self.assertEqual(cached["pois"], result["pois"])
            self.assertTrue(cached["report"]["cached"]["pois"])
            self.assertEqual(json.loads((raw_dir / "candidates.json").read_text()), result["pois"])
        self.assertEqual(result["boundary"]["type"], "MultiPolygon")
        self.assertEqual(self.osm.geometry_bbox(result["boundary"]), (51.0, 71.0, 51.4, 71.8))
        self.assertEqual({p["id"] for p in result["pois"]}, {"osm:node/5", "osm:way/11", "osm:relation/21", "osm:relation/22"})
        monument = next(p for p in result["pois"] if p["id"] == "osm:way/11")
        self.assertEqual((monument["lat"], monument["lon"]), (51.0, 71.4))
        self.assertEqual(result["boundary_source_urls"], ["https://www.openstreetmap.org/relation/20"])

    def test_boundary_resolves_full_osm_api_node_and_way_references(self):
        payload = {"elements": [
            {"type": "node", "id": 1, "lat": 51.0, "lon": 71.0},
            {"type": "node", "id": 2, "lat": 51.0, "lon": 71.8},
            {"type": "node", "id": 3, "lat": 51.4, "lon": 71.8},
            {"type": "way", "id": 10, "nodes": [1, 2, 3, 1]},
            {"type": "relation", "id": 20, "tags": {"boundary": "administrative", "wikidata": "Q1520"},
             "members": [{"type": "way", "ref": 10, "role": "outer"}]},
        ]}
        result = self.osm.boundary_geometry(payload)
        self.assertIsNotNone(result)
        self.assertEqual(self.osm.geometry_bbox(result), (51.0, 71.0, 51.4, 71.8))

    def test_regional_download_is_atomic_and_cached_and_rejects_truncation(self):
        import io
        class Response(io.BytesIO):
            status = 200
            def __init__(self, body, size):
                super().__init__(body)
                self.headers = {"Content-Length": str(size)}
            def geturl(self):
                return "https://download.geofabrik.de/asia/kazakhstan-261017.osm.pbf"
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            with patch.object(self.osm, "urlopen", return_value=Response(b"pbf", 3)):
                path = self.osm.download_extract(raw_dir)
            self.assertEqual(path.read_bytes(), b"pbf")
            with patch.object(self.osm, "urlopen", side_effect=AssertionError("Download cache missed")):
                self.assertEqual(self.osm.download_extract(raw_dir), path)
            with patch.object(self.osm, "urlopen", return_value=Response(b"pb", 3)):
                with self.assertRaises(OSError):
                    self.osm.download_extract(raw_dir, refresh=True)
            self.assertEqual(path.read_bytes(), b"pbf")

    def test_corrupt_local_extract_reports_failure_without_erasing_prior_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory)
            source = raw_dir / "bad.osm.pbf"
            source.write_bytes(b"broken pbf")
            previous = [{"id": "osm:node/1", "name": "Existing"}]
            (raw_dir / "candidates.json").write_text(json.dumps(previous))
            result = self.osm.collect_file(source, raw_dir, refresh=True)
            self.assertEqual(result["pois"], previous)
            self.assertEqual(result["report"]["status"], "partial")
            self.assertTrue(result["report"]["stale_cache"])
            self.assertTrue(result["report"]["errors"])
            self.assertEqual(json.loads((raw_dir / "candidates.json").read_text()), previous)

    def test_throttling_on_final_instance_still_waits_before_next_query(self):
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.osm, "OVERPASS_ENDPOINTS", ("https://example.org/api",)), \
             patch.object(self.osm, "_request_overpass", side_effect=HTTPError("https://example.org", 429, "Too Many Requests", {}, None)), \
             patch.object(self.osm.time, "sleep") as sleep:
            self.osm.collect(Path(directory))
        self.assertTrue(any(call.args[0] >= 30 for call in sleep.call_args_list))

    def test_invalid_bbox_is_rejected_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self.osm.collect(Path(directory), bbox=(51.4, 71.0, 50.9, 71.9))


if __name__ == "__main__":
    unittest.main()
