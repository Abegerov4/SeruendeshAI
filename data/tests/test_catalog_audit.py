"""Audit contracts: a reachable homepage is not a branch confirmation."""
import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest


def audit():
    return importlib.import_module("data.catalog_audit")


def place(**overrides):
    return {"id": "osm:node/1", "name": "Coffee One", "category": "cafe",
            "address": "улица Мира, 7", "lat": 51.13, "lon": 71.43,
            "source": "osm", "source_url": "https://www.openstreetmap.org/node/1",
            "website": "https://coffee.example/", **overrides}


def test_source_url_is_not_mistaken_for_an_official_website():
    mod = audit()
    rows = mod.build_rows([place(website=None), place(id="osm:node/2")], {}, {})
    assert len(rows) == 2
    assert rows[0]["website_check_status"] == "no_url"
    assert rows[0]["source_url"] == "https://www.openstreetmap.org/node/1"
    assert rows[0]["search_complete"] is False
    assert rows[0]["deletion_eligible"] is False
    assert rows[1]["website_check_status"] == "pending"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/a", "http://[::1]/",
    "http://169.254.169.254/", "https://10.0.0.1/", "http://localhost/", "http://abc.local/",
    "https://user:secret@example.com/", "https://example.com:8080/", "https://example.com/?token=abc"])
def test_private_internal_and_credential_urls_are_rejected(url):
    with pytest.raises(ValueError):
        audit().normalize_url(url)


def test_url_dedup_preserves_semantic_queries_and_strips_fragments():
    assert audit().normalize_url("HTTPS://Example.COM:443/a?city=astana#hours") == "https://example.com/a?city=astana"


def test_branch_matching_requires_name_and_address_or_nearby_geo():
    match = audit().identity_match
    assert match(place(), {"name": "Coffee One", "address": "улица Мира, 7"})["matched"]
    assert match(place(), {"name": "Coffee One", "lat": 51.13001, "lon": 71.43001})["matched"]
    assert not match(place(), {"name": "Coffee One"})["matched"]
    assert not match(place(), {"name": "Coffee One", "address": "улица Мира, 8", "lat": 51.13, "lon": 71.43})["matched"]
    assert not match(place(), {"name": "Coffee One", "address": "улица Мира, 7", "lat": 55.7, "lon": 37.6})["matched"]
    assert not match(place(), {"name": "Other Coffee", "address": "улица Мира, 7"})["matched"]


def test_jsonld_keeps_raw_business_facts_and_menu_links_without_inventing_hours():
    raw = {"@context": "https://schema.org", "@graph": [{"@type": "Organization", "name": "Parent"},
        {"@type": "CafeOrCoffeeShop", "name": "Coffee One", "address": {"streetAddress": "улица Мира, 7"},
         "geo": {"latitude": 51.13, "longitude": 71.43}, "telephone": "+77172123456",
         "openingHoursSpecification": [{"dayOfWeek": "https://schema.org/Monday", "opens": "09:00", "closes": "21:00"}],
         "hasMenu": "/menu", "priceRange": "₸₸", "aggregateRating": {"ratingValue": "4.2", "reviewCount": "12"}}]}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script><a href="/menu.pdf">Меню</a>'
    result = audit().extract_page(html, "https://coffee.example/")
    assert len(result["businesses"]) == 1
    fact = result["businesses"][0]
    assert fact["name"] == "Coffee One" and fact["address"] == "улица Мира, 7"
    assert fact["raw_jsonld"]["telephone"] == "+77172123456"
    assert fact["facts"]["opening_hours"] == "Mo 09:00-21:00"
    assert fact["facts"]["rating"] == 4.2
    assert fact["facts"]["price_range"] == "₸₸"
    assert {x["url"] for x in result["public_links"]} == {"https://coffee.example/menu", "https://coffee.example/menu.pdf"}


def test_http_success_and_errors_never_create_closure_or_completed_search():
    mod = audit()
    ps = [place(), place(id="osm:node/2", website="https://fail.example/")]
    fetches = {"https://coffee.example/": {"status": "successful_fetch", "extracted": {"businesses": []}},
               "https://fail.example/": {"status": "http_error", "http_status": 404}}
    rows = mod.build_rows(ps, fetches, {})
    assert rows[0]["confirmation_status"] == "unmatched"
    assert rows[1]["confirmation_status"] == "incomplete"
    assert all(not x["deletion_eligible"] and not x["search_complete"] for x in rows)
    assert all(x["operating_status"] == "unknown" for x in rows)


def test_category_gaps_do_not_demand_a_menu_from_a_park():
    gap = audit().field_gaps
    assert "menu_url" in gap(place())
    assert "menu_url" not in gap(place(category="park"))
    assert "opening_hours" in gap(place())
    assert "opening_hours" not in gap(place(category="monument"))
    assert "website" in gap(place(website=None))


def test_resumable_log_ignores_only_a_truncated_final_record(tmp_path):
    path = tmp_path / "fetches.jsonl"
    path.write_text('{"url":"https://a.example/","status":"network_error"}\n{"url":', encoding="utf-8")
    assert list(audit().read_jsonl(path))[0]["status"] == "network_error"
    path.write_text('bad\n{}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        list(audit().read_jsonl(path))


def test_fetch_blocks_private_redirect_and_never_fetches_the_target(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"}, request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        fetcher = audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0)
        async with fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "blocked_unsafe_url"
        assert len(result["redirect_chain"]) == 1
    asyncio.run(scenario())


def test_fetch_respects_robots_and_does_not_download_disallowed_page(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n", request=request)
            raise AssertionError("Disallowed page was requested")
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "blocked_robots"
    asyncio.run(scenario())


def test_fetch_bounds_body_and_reuses_completed_public_cache(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(200, text="a" * 100, request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0, max_bytes=20) as fetcher:
            first = await fetcher.fetch("https://coffee.example/")
            second = await fetcher.fetch("https://coffee.example/")
        assert first["status"] == "incomplete_body_limit"
        assert first["bytes_retained"] <= 20
        assert second["cache_hit"] is True
    asyncio.run(scenario())


def test_dns_work_is_bounded_before_timeout_starts(tmp_path):
    async def scenario():
        active = peak = 0
        async def resolver(host):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
            return ["93.184.216.34"]
        def response(request):
            return httpx.Response(404 if request.url.path == "/robots.txt" else 200, text="ok", request=request)
        async with audit().PublicFetcher(tmp_path, concurrency=3, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            results = await asyncio.gather(*(fetcher.fetch(f"https://coffee{i}.example/") for i in range(12)))
        assert peak <= 3
        assert all(r["status"] == "successful_fetch" for r in results)
    asyncio.run(scenario())


def test_osm_id_batches_cover_all_source_records_without_fetching_entire_city():
    mod = audit()
    pois = [place(source_records=[{"id": "osm:node/11", "source": "osm"}, {"id": "osm:way/22", "source": "osm"}]),
            place(id="overture:one", source="overture", source_records=[{"id": "osm:node/11", "source": "osm"}])]
    batches = mod.osm_id_batches(pois, batch_size=1)
    assert len(batches) == 2
    assert batches[0]["ids"] == ["osm:node/11"]
    assert batches[1]["ids"] == ["osm:way/22"]
    assert "node(id:11)" in batches[0]["query"] and "out meta center" in batches[0]["query"]
    assert "bbox" not in batches[0]["query"]


def test_osm_missing_object_and_explicit_lifecycle_are_review_observations_not_automatic_closures():
    mod = audit()
    pois = [place(id="osm:node/11"), place(id="osm:node/12")]
    payload = {"elements": [{"type": "node", "id": 11, "lat": 51.13, "lon": 71.43,
               "timestamp": "2026-10-18T10:00:00Z", "version": 3,
               "tags": {"name": "Coffee One", "amenity": "cafe", "opening_hours": "closed", "disused": "yes"}}]}
    observations, candidates, checks = mod.osm_observations(pois, ["osm:node/11", "osm:node/12"], payload,
        {"status": "successful_fetch", "url": "https://overpass-api.de/api/interpreter?data=...", "fetched_at": "2026-10-19T01:00:00Z"})
    assert observations[0]["status"] == "current_object_present"
    assert observations[0]["lifecycle_review_required"] is True
    assert observations[1]["status"] == "object_not_returned"
    assert checks["osm:node/12"]["branch_identity_confirmed"] is False
    assert all(c["publication_status"] == "candidate_requires_review" and c["operating_status"] == "unknown" for c in candidates)
    assert candidates[0]["facts"]["opening_hours"] == "closed"
    assert candidates[0]["source_updated_at"] == "2026-10-18T10:00:00Z"


def test_obvious_antibot_or_gambling_pages_are_not_branch_evidence():
    page = audit().extract_page('<html><title>Verify you are human</title><body>Cloudflare challenge</body></html>', "https://coffee.example/")
    assert "antibot_challenge" in page["content_flags"]
    spam = audit().extract_page('<title>Visit Astana</title><p>Онлайн казино игровые автоматы ставки на спорт</p>', "https://coffee.example/")
    assert "possible_gambling_or_seo_content" in spam["content_flags"]


def test_documented_readonly_api_policy_is_narrowly_scoped(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n", request=request)
            return httpx.Response(200, json={"elements": []}, request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            api = await fetcher.fetch("https://overpass-api.de/api/interpreter?data=test", documented_api=True)
            website = await fetcher.fetch("https://coffee.example/", documented_api=True)
        assert api["status"] == "successful_fetch"
        assert api["robots"]["status"] == "documented_read_only_api_policy"
        assert website["status"] == "blocked_robots"
    asyncio.run(scenario())


def test_osm_stops_retrying_endpoints_after_three_overload_responses(tmp_path, monkeypatch):
    mod = audit()
    catalog = [place(id=f"osm:node/{n}") for n in range(10)]
    (tmp_path / "input-pois.json").write_text(json.dumps(catalog))
    requests = []
    class Overloaded:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetch(self, url, **kwargs):
            requests.append(url)
            return {"status": "http_error", "http_status": 503, "url": url, "fetched_at": "2026-10-19T01:00:00Z"}
    monkeypatch.setattr(mod, "PublicFetcher", Overloaded)
    args = SimpleNamespace(output=str(tmp_path), input="unused", osm_batch_size=1, timeout=10, delay=0, as_of="2026-10-19")
    asyncio.run(mod.run_osm(args))
    assert len(requests) == 9
    observations = list(mod.read_jsonl(tmp_path / "audit-osm-observations.jsonl"))
    assert len(observations) == 10
    assert all(o["status"] == "incomplete" for o in observations)
    asyncio.run(mod.run_osm(args))
    assert len(requests) == 9


def test_malformed_redirect_is_a_recorded_failure_not_a_batch_crash(tmp_path):
    async def scenario():
        def response(request):
            return httpx.Response(302, headers={"location": "http:broken"}, request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "blocked_unsafe_url"
    asyncio.run(scenario())


def test_exact_directory_source_can_confirm_identity_without_a_listed_website():
    mod = audit()
    p = place(website=None, source="citypass", source_url="https://directory.example/coffee")
    fetched = {"https://directory.example/coffee": {"status": "successful_fetch", "fetched_at": "2026-10-19T01:00:00Z",
               "extracted": {"businesses": [{"name": "Coffee One", "address": "улица Мира, 7", "facts": {"phone": "123"}}]}}}
    rows = mod.build_rows([p], fetched, {})
    assert rows[0]["website_check_status"] == "no_url"
    assert rows[0]["source_check"]["status"] == "successful_fetch"
    assert rows[0]["confirmation_status"] == "branch_identity_confirmed"
    candidates = mod.make_candidates([p], fetched, "2026-10-19")
    assert len(candidates) == 1
    assert candidates[0]["canonical_id"] == "osm:node/1"
    assert candidates[0]["source_kind"] == "exact_catalog_source_jsonld"


def test_resume_retries_only_results_older_than_a_requested_cutoff(tmp_path, monkeypatch):
    mod = audit()
    (tmp_path / "input-pois.json").write_text(json.dumps([place(), place(id="osm:node/2", website="https://done.example/")]))
    (tmp_path / "fetches.jsonl").write_text(json.dumps({"url": "https://coffee.example/", "status": "network_error", "fetched_at": "2026-10-19T00:00:00Z"}) + "\n" + json.dumps({"url": "https://done.example/", "status": "network_error", "fetched_at": "2026-10-19T02:00:00Z"}) + "\n")
    class Reachable:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetch(self, url, **kwargs):
            return {"url": url, "status": "successful_fetch", "fetched_at": "2026-10-19T03:00:00Z"}
    monkeypatch.setattr(mod, "PublicFetcher", Reachable)
    args = SimpleNamespace(output=str(tmp_path), input="unused", as_of="2026-10-19", retry_incomplete=True,
                           retry_before="2026-10-19T01:00:00Z", limit=None, concurrency=8, timeout=10, delay=.8)
    asyncio.run(mod.run(args))
    rows = list(mod.read_jsonl(tmp_path / "rows.jsonl"))
    assert rows[0]["website_check_status"] == "successful_fetch"
    assert rows[1]["website_check_status"] == "network_error"
    assert rows[1]["website_fetched_at"] == "2026-10-19T02:00:00Z"


def test_a_slow_stream_cannot_extend_total_http_deadline_indefinitely(tmp_path):
    async def scenario():
        class Slow(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(10):
                    await asyncio.sleep(.01)
                    yield b"x"
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(200, stream=Slow(), request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0, timeout=.025) as fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "network_error"
        assert result["error"] == "TimeoutError"
    asyncio.run(scenario())


def test_refresh_keeps_the_previous_raw_response_available_for_its_provenance(tmp_path):
    async def scenario():
        values = iter(["original", "updated"])
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(200, text=next(values), request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            first = await fetcher.fetch("https://coffee.example/")
            second = await fetcher.fetch("https://coffee.example/", refresh=True)
        from pathlib import Path
        assert Path(first["raw_cache"]).read_text() == "original"
        assert Path(second["raw_cache"]).read_text() == "updated"
    asyncio.run(scenario())


def test_report_only_reparses_saved_pages_and_includes_source_check_gaps_without_network(tmp_path, monkeypatch):
    mod = audit()
    (tmp_path / "input-pois.json").write_text(json.dumps([place()]))
    body = tmp_path / "saved.body"
    body.write_text('<title>Verify you are human</title>Cloudflare challenge')
    (tmp_path / "fetches.jsonl").write_text(json.dumps({"url": "https://coffee.example/", "status": "successful_fetch", "content_type": "text/html", "raw_cache": str(body)}) + "\n")
    (tmp_path / "audit-osm-checks.json").write_text(json.dumps({"osm:node/1": {"status": "incomplete", "branch_identity_confirmed": False}}))
    class NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Report-only attempted network initialization")
    monkeypatch.setattr(mod, "PublicFetcher", NoNetwork)
    args = SimpleNamespace(output=str(tmp_path), input="unused", as_of="2026-10-19", retry_incomplete=False,
                           retry_before=None, report_only=True, limit=None, concurrency=8, timeout=10, delay=.8)
    asyncio.run(mod.run(args))
    rows = list(mod.read_jsonl(tmp_path / "rows.jsonl"))
    assert rows[0]["website_content_flags"] == ["antibot_challenge"]
    assert rows[0]["source_check"]["status"] == "incomplete"
    assert rows[0]["confirmation_status"] == "incomplete"
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["source_check_statuses"] == {"incomplete": 1}
    assert summary["no_data_after_completed_search"] == 0
    assert summary["fresh_exact_branch_identity_rows"] == 0
    assert summary["fetched_sources_without_branch_match_rows"] == 0
    assert summary["incomplete_branch_checks_rows"] == 1
    assert summary["target_urls"] == 1 and summary["pending_urls"] == 0
    assert len(summary["input_sha256"]) == 64


def test_api_permission_does_not_follow_a_redirect_to_an_unrelated_site(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/api/interpreter":
                return httpx.Response(302, headers={"location": "https://coffee.example/"}, request=request)
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n", request=request)
            raise AssertionError("Unrelated site inherited API permission")
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            result = await fetcher.fetch("https://overpass-api.de/api/interpreter?data=test", documented_api=True)
        assert result["status"] == "blocked_robots"
    asyncio.run(scenario())


def test_generated_description_does_not_count_as_a_sourced_description():
    mod = audit()
    assert "source_description" in mod.field_gaps(place(description="Место Coffee One в Астане", description_kind="structured_template"))
    assert "source_description" not in mod.field_gaps(place(description="A public source description", description_kind="source"))


def test_impossible_geo_cannot_wrap_around_and_confirm_a_branch():
    result = audit().identity_match(place(address=None), {"name": "Coffee One", "lat": 411.13, "lon": 71.43})
    assert result["matched"] is False
    assert result["distance_m"] is None


def test_known_public_dodo_payload_retains_branch_id_and_current_hours():
    payload = [{"Id": "unit-one", "Name": "Астана-1", "Alias": "Додо Пицца", "State": 1, "Type": 1,
                "Address": "улица Мира, 7", "Coordinates": {"Latitude": 51.13, "Longitude": 71.43},
                "IsAroundClockRestaurantWorkTime": True}]
    result = audit().extract_source_payload(json.dumps(payload).encode(), "https://publicapi.dodois.io/KZ/api/v1/unitinfo/all", "application/json")
    assert result["businesses"][0]["source_id"] == "dodo:unit-one"
    assert result["businesses"][0]["facts"]["opening_hours"] == "24/7"
    assert result["businesses"][0]["parser"] == "official_directory_structured"


def test_advertised_crawl_delay_is_applied_to_the_page_after_robots(tmp_path, monkeypatch):
    async def scenario():
        waits = []
        async def sleep(seconds):
            waits.append(seconds)
        def response(request):
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 2\n" if request.url.path == "/robots.txt" else "ok", request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        monkeypatch.setattr(asyncio, "sleep", sleep)
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "successful_fetch"
        assert any(seconds >= 1.9 for seconds in waits)
    asyncio.run(scenario())


def test_deeply_nested_untrusted_jsonld_is_retained_without_crashing_a_batch(tmp_path):
    async def scenario():
        html = '<script type="application/ld+json">' + '[' * 2000 + '{}' + ']' * 2000 + '</script>'
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(200, text=html, request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            result = await fetcher.fetch("https://coffee.example/")
        assert result["status"] == "incomplete_extraction_error"
        assert result["error"] == "RecursionError"
        from pathlib import Path
        assert Path(result["raw_cache"]).read_text() == html
    asyncio.run(scenario())


def test_redirect_preserves_the_requested_url_for_resumable_dedup(tmp_path):
    async def scenario():
        def response(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            if request.url.path == "/old":
                return httpx.Response(301, headers={"location": "/new"}, request=request)
            return httpx.Response(200, text="ok", request=request)
        async def resolver(host):
            return ["93.184.216.34"]
        async with audit().PublicFetcher(tmp_path, transport=httpx.MockTransport(response), resolver=resolver, delay=0) as fetcher:
            first = await fetcher.fetch("https://coffee.example/old")
            cached = await fetcher.fetch("https://coffee.example/old")
        assert first["url"] == "https://coffee.example/old"
        assert cached["url"] == "https://coffee.example/old"
        assert first["final_url"] == "https://coffee.example/new"
    asyncio.run(scenario())


def test_legacy_redirect_metadata_is_recovered_from_its_original_cache_key(tmp_path):
    import hashlib
    mod = audit()
    original = "https://coffee.example/old"
    final = "https://coffee.example/new"
    cache = tmp_path / "cache"
    cache.mkdir()
    legacy = {"url": final, "final_url": final, "status": "successful_fetch", "fetched_at": "2026-10-19T01:00:00Z"}
    (cache / (hashlib.sha256(original.encode()).hexdigest() + ".json")).write_text(json.dumps(legacy))
    log = tmp_path / "fetches.jsonl"
    log.write_text(json.dumps(legacy) + "\n")
    results = mod.load_fetch_results(log, cache, {original})
    assert set(results) == {original}
    assert results[original]["url"] == original
    assert results[original]["final_url"] == final


def test_host_outage_tail_remains_explicitly_uncompleted_and_keeps_previous_observations(tmp_path):
    mod = audit()
    url = "https://wa.me/77171234567"
    (tmp_path / "input-pois.json").write_text(json.dumps([place(website=url)]))
    prior = {"url": url, "status": "network_error", "fetched_at": "2026-10-19T00:00:00Z"}
    log = tmp_path / "fetches.jsonl"
    log.write_text(json.dumps(prior) + "\n")
    (tmp_path / "audit-host-outage.json").write_text(json.dumps({"network_pass_status": "partial_host_outage", "deferred_retry_count": 1,
        "deferred_domains": {"wa.me": 1}, "deferred": [{"url": url, "status": "retry_not_completed_host_outage", "previous_status": "network_error"}]}))
    args = SimpleNamespace(output=str(tmp_path), input="unused", as_of="2026-10-19", retry_incomplete=False,
                           retry_before="2026-10-19T01:00:00Z", report_only=True, limit=None, concurrency=8, timeout=10, delay=.8)
    asyncio.run(mod.run(args))
    rows = list(mod.read_jsonl(tmp_path / "rows.jsonl"))
    assert rows[0]["website_check_status"] == "retry_not_completed_host_outage"
    assert rows[0]["website_previous_observation_status"] == "network_error"
    assert rows[0]["confirmation_status"] == "incomplete"
    assert list(mod.read_jsonl(log)) == [prior]
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["network_pass_status"] == "partial_host_outage"
    assert summary["deferred_retry_count"] == 1
    assert summary["initial_queue_affected_outcomes_remaining"] == 1
