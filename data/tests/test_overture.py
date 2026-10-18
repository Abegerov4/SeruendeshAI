"""Literal source fixtures exercise Overture normalization and cache behavior."""

import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


if importlib.util.find_spec("data.collect.overture") is not None:
    from data.collect import overture
else:
    overture = None


RELEASE = "2026-09-23.1"
BBOX = (50.9, 71.0, 51.4, 71.9)


def place(**changes):
    row = {
        "id": "08f45287-87de-3355-9240-2b69cfd957b2",
        "geometry": struct.pack("<BIdd", 1, 1, 71.43049, 51.12825),
        "names": {
            "primary": "Кофейня",
            "common": [("en", "Coffee house"), ("kk", "Кофехана")],
        },
        "basic_category": "coffee_shop",
        "taxonomy": {"primary": "coffee_shop", "hierarchy": ["food_and_drink", "cafe", "coffee_shop"]},
        "operating_status": "open",
        "sources": [{"property": "", "dataset": "Microsoft", "record_id": "source-123"}],
        "websites": ["https://example.org/"],
        "phones": ["+7 7172 123456"],
        "addresses": [{"freeform": "Астана, проспект Мангилик Ел, 1"}],
    }
    row.update(changes)
    return row


class OvertureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(overture, "Overture collector must exist")

    def test_current_taxonomy_and_multilingual_names_preserve_provenance(self):
        row = place()
        poi = overture.normalize_place(row, RELEASE)
        self.assertEqual(poi["category"], "cafe")
        self.assertEqual(poi["name_en"], "Coffee house")
        self.assertEqual(poi["name_kk"], "Кофехана")
        self.assertAlmostEqual(poi["lat"], 51.12825)
        self.assertAlmostEqual(poi["lon"], 71.43049)
        self.assertEqual(poi["sources"], row["sources"])
        self.assertEqual(poi["raw_taxonomy"]["taxonomy"], row["taxonomy"])
        self.assertEqual(poi["source_license"], "CDLA-Permissive-2.0")
        self.assertIn(RELEASE, poi["source_url"])
        self.assertIn(row["id"], poi["source_url"])
        self.assertIsNone(poi["opening_hours"])
        self.assertIsNone(poi["rating"])
        self.assertIsNone(poi["description"])

    def test_legacy_category_and_source_specific_license(self):
        poi = overture.normalize_place(place(basic_category=None, taxonomy=None,
            categories={"primary": "art_museum"}, sources=[{"dataset": "Foursquare"}]), RELEASE)
        self.assertEqual(poi["category"], "museum")
        self.assertEqual(poi["source_license"], "Apache-2.0")
        poi = overture.normalize_place(place(sources=[{"dataset": "AllThePlaces"}]), RELEASE)
        self.assertEqual(poi["source_license"], "CC0-1.0")
        poi = overture.normalize_place(place(sources=[{"dataset": "Microsoft"}, {"dataset": "UnknownProvider"}]), RELEASE)
        self.assertIsNone(poi["source_license"])

    def test_current_source_license_properties_are_authoritative(self):
        sources = [
            {"property": "", "dataset": "Foursquare", "license": "Apache-2.0", "update_time": "2025-02-21T00:00:00.000"},
            {"property": "/properties/confidence", "dataset": "Overture", "license": "CDLA-Permissive-2.0"},
        ]
        poi = overture.normalize_place(place(sources=sources), RELEASE)
        self.assertEqual(poi["source_license"], "Apache-2.0 AND CDLA-Permissive-2.0")
        self.assertEqual(poi["source_updated_at"], "2025-02-21T00:00:00.000")
        self.assertEqual(poi["sources"], sources)

    def test_unknown_categories_are_kept_without_false_park_match(self):
        poi = overture.normalize_place(place(basic_category="parking_garage", taxonomy=None), RELEASE)
        self.assertEqual(poi["category"], "other")
        self.assertIn("parking_garage", poi["tags"])

    def test_explicit_housing_and_parking_taxonomy_conflicts_are_flagged(self):
        for name in ('ЖК Олимп Палас2', 'ЖК Торлет', 'ЖК Форт-Строй', '"ЖК "Премьера!""', 'Жилой комплекс Riverside'):
            row = place(names={"primary": name}, basic_category="historic_site",
                        taxonomy={"primary": "historic_site", "hierarchy": ["landmark", "historic_site"]})
            poi = overture.normalize_place(row, RELEASE)
            self.assertEqual(poi["category"], "other")
            self.assertIn("upstream_category_conflict", poi["quality_flags"])
            self.assertEqual(poi["raw_taxonomy"]["taxonomy"]["primary"], "historic_site")
        poi = overture.normalize_place(place(names={"primary": "Парковочное пространство Астаны"},
            basic_category="park", taxonomy={"primary": "park"}), RELEASE)
        self.assertEqual(poi["category"], "other")
        self.assertIn("upstream_category_conflict", poi["quality_flags"])
        unaffected = overture.normalize_place(place(names={"primary": "ЖК Парк"},
            basic_category="park", taxonomy={"primary": "park"}), RELEASE)
        self.assertEqual(unaffected["category"], "park")
        self.assertNotIn("upstream_category_conflict", unaffected["quality_flags"])

    def test_closed_and_unnamed_places_are_excluded_unknown_status_retained(self):
        for status in ("permanently_closed", "temporarily_closed", "closed", "closed_permanently"):
            self.assertIsNone(overture.normalize_place(place(operating_status=status), RELEASE))
        for names in (None, {"primary": " "}):
            self.assertIsNone(overture.normalize_place(place(names=names), RELEASE))
        self.assertIsNotNone(overture.normalize_place(place(operating_status=None), RELEASE))

    def test_original_description_is_preserved_without_generating_hours(self):
        poi = overture.normalize_place(place(description="Original venue description.", operating_status="open"), RELEASE)
        self.assertEqual(poi["description"], "Original venue description.")
        self.assertIsNone(poi["description_source"])
        self.assertIsNone(poi["opening_hours"])

    def test_collection_has_no_record_cap_and_reuses_bbox_cache(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        rows = [place(id=f"place-{i}") for i in range(1203)]
        rows += [place(id="closed", operating_status="permanently_closed"),
                 place(id="outside", geometry=struct.pack("<BIdd", 1, 1, 74.0, 52.0))]
        rows = copy.deepcopy(rows)
        # The parquet fixture represents Arrow's map readback as list pairs.
        for row in rows:
            row["names"]["common"] = {"en": "Coffee house", "kk": "Кофехана"}

        def download(path, bbox):
            self.assertEqual(tuple(bbox), BBOX)
            pq.write_table(pa.Table.from_pylist(rows), path)
            return {"release": RELEASE, "source_urls": ["https://stac.overturemaps.org/catalog.json"]}

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(overture, "_download_subset", side_effect=download) as fetch:
                result = overture.collect(Path(folder), bbox=BBOX)
                cached = overture.collect(Path(folder), bbox=BBOX)
            self.assertEqual(len(result["pois"]), 1203)
            self.assertEqual(cached["pois"], result["pois"])
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(result["report"]["counts"]["closed_excluded"], 1)
            self.assertEqual(result["report"]["counts"]["outside_bbox_excluded"], 1)
            self.assertIsNotNone(result["pois"][0].get("collected_at"))
            self.assertEqual(result["pois"][0].get("source_records", [{}])[0].get("upstream_sources"), rows[0]["sources"])
            self.assertTrue((Path(folder) / "overture" / "subset.parquet").exists())
            self.assertTrue((Path(folder) / "overture" / "candidates.json").exists())

    def test_failed_refresh_keeps_prior_candidates_and_reports_failure(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        row = place()
        row["names"]["common"] = {"en": "Coffee house", "kk": "Кофехана"}

        def download(path, bbox):
            pq.write_table(pa.Table.from_pylist([row]), path)
            return {"release": RELEASE, "source_urls": []}

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(overture, "_download_subset", side_effect=download):
                first = overture.collect(Path(folder))
            with patch.object(overture, "_download_subset", side_effect=RuntimeError("temporary outage")):
                failed = overture.collect(Path(folder), refresh=True)
            self.assertEqual(failed["pois"], first["pois"])
            self.assertEqual(failed["report"]["status"], "stale_cache")
            self.assertIn("temporary outage", str(failed["report"]["errors"]))
            stored = json.loads((Path(folder) / "overture" / "candidates.json").read_text())
            self.assertEqual(stored, first["pois"])

    def test_old_normalization_is_rebuilt_from_raw_subset_without_network(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        row = place(names={"primary": "Fixture"})

        def download(path, bbox):
            pq.write_table(pa.Table.from_pylist([row]), path)
            return {"release": RELEASE, "source_urls": []}

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(overture, "_download_subset", side_effect=download):
                overture.collect(Path(folder))
            report_path = Path(folder) / "overture" / "report.json"
            old = json.loads(report_path.read_text())
            old["normalization_version"] = 0
            report_path.write_text(json.dumps(old))
            with patch.object(overture, "_download_subset", side_effect=RuntimeError("network forbidden")) as fetch:
                rebuilt = overture.collect(Path(folder))
            fetch.assert_not_called()
            self.assertTrue(rebuilt["report"].get("normalization_rebuilt_from_cache", False))
            self.assertEqual(len(rebuilt["pois"]), 1)

    def test_invalid_bbox_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                overture.collect(Path(folder), bbox=(51.4, 71.0, 50.9, 71.9))

    def test_official_reader_gets_live_release_stac_and_correct_bbox_order(self):
        import httpx
        import pyarrow as pa
        import pyarrow.parquet as pq

        def response(request):
            if request.url.path == "/catalog.json":
                return httpx.Response(200, json={"latest": RELEASE})
            if request.url.path.endswith("/collection.json"):
                return httpx.Response(200, json={"license": "other", "links": [
                    {"rel": "license", "href": overture.LICENSE_URL}]})
            return httpx.Response(200, text="<h3>Places</h3><li>Data from Microsoft. Available under CDLA Permissive 2.0.</li>")

        table = pa.Table.from_pylist([{"id": "a", "geometry": place()["geometry"]}])
        reader = pa.RecordBatchReader.from_batches(table.schema, table.to_batches())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "subset.parquet"
            with patch("httpx.HTTPTransport", return_value=httpx.MockTransport(response)):
                with patch("overturemaps.core.record_batch_reader", return_value=reader) as fetch:
                    metadata = overture._download_subset(path, BBOX)
            self.assertEqual(fetch.call_args.kwargs["bbox"], (71.0, 50.9, 71.9, 51.4))
            self.assertEqual(fetch.call_args.kwargs["release"], RELEASE)
            self.assertTrue(fetch.call_args.kwargs["stac"])
            self.assertEqual(metadata["source_licenses"], {"microsoft": "CDLA-Permissive-2.0"})
            self.assertEqual(pq.ParquetFile(path).metadata.num_rows, 1)

    def test_recent_verified_metadata_survives_dns_outage(self):
        import httpx
        import pyarrow as pa

        def unavailable(request):
            raise httpx.ConnectError("temporary DNS outage", request=request)

        table = pa.Table.from_pylist([{"id": "a", "geometry": place()["geometry"]}])
        reader = pa.RecordBatchReader.from_batches(table.schema, table.to_batches())
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "stac_catalog.json").write_text(json.dumps({"latest": RELEASE}))
            (folder / "stac_collection.json").write_text(json.dumps({"license": "other", "partition:glob": f"https://example.org/{RELEASE}/*.parquet"}))
            (folder / "licensing.html").write_text("Data from Microsoft. Available under CDLA Permissive 2.0.")
            with patch("httpx.HTTPTransport", return_value=httpx.MockTransport(unavailable)):
                with patch("overturemaps.core.record_batch_reader", return_value=reader):
                    try:
                        metadata = overture._download_subset(folder / "subset.parquet", BBOX)
                    except httpx.ConnectError as error:
                        self.fail(f"A recent verified metadata snapshot must remain usable: {error}")
            self.assertTrue(metadata["metadata_cache_used"])
            self.assertIn("temporary DNS outage", str(metadata["metadata_errors"]))


if __name__ == "__main__":
    unittest.main()
