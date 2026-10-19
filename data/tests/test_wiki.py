"""Wikimedia acquisition tests use real HTTPX responses with a local transport."""
from pathlib import Path

import httpx

from data.collect import enrich_wiki as wiki

HTTPX_CLIENT = httpx.Client


def transport(monkeypatch, handler):
    monkeypatch.setattr(wiki.httpx, "Client", lambda **kwargs: HTTPX_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(wiki, "REQUEST_INTERVAL", 0)


def entity(qid="Q1", *, links=True):
    return {
        "id": qid,
        "labels": {"ru": {"language": "ru", "value": "Музей"}, "kk": {"language": "kk", "value": "Мұражай"}, "en": {"language": "en", "value": "Museum"}},
        "descriptions": {"ru": {"language": "ru", "value": "музей в Астане"}},
        "claims": {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 51.12, "longitude": 71.43, "globe": "http://www.wikidata.org/entity/Q2"}}}}], "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q33506"}}}}]},
        "sitelinks": {"ruwiki": {"site": "ruwiki", "title": "Музей", "url": "https://ru.wikipedia.org/wiki/Музей"}, "kkwiki": {"site": "kkwiki", "title": "Мұражай", "url": "https://kk.wikipedia.org/wiki/Мұражай"}} if links else {},
    }


def test_collect_paginates_and_keeps_multilingual_cc0_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "PAGE_SIZE", 2)
    def handle(request):
        p = request.url.params
        if request.url.host == "query.wikidata.org":
            offset = int(str(p["query"]).split("OFFSET ")[1])
            ids = ["Q1", "Q2"] if offset == 0 else ["Q3"]
            return httpx.Response(200, json={"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/" + q}, "coord": {"value": "Point(71.43 51.12)"}, "kind": {"value": "http://www.wikidata.org/entity/Q33506"}} for q in ids]}})
        return httpx.Response(200, json={"entities": {q: entity(q) for q in p["ids"].split("|")}})
    transport(monkeypatch, handle)
    result = wiki.collect(tmp_path)
    assert len(result["pois"]) == 3
    first = result["pois"][0]
    assert (first["id"], first["name"], first["name_en"], first["name_kk"], first["category"]) == ("wikidata:Q1", "Музей", "Museum", "Мұражай", "museum")
    assert first["source_license"] == "CC0-1.0"
    assert first["description_source"] is None
    assert result["report"]["complete"] is True
    assert (tmp_path / "candidates.json").exists()


def test_enrich_prefers_ru_article_and_preserves_original_input(tmp_path, monkeypatch):
    original = {"id": "osm:node/1", "name": "Museum", "raw_tags": {"wikidata": "Q1"}, "description": None}
    def handle(request):
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": entity()}})
        return httpx.Response(200, json={"query": {"pages": [{"pageid": 7, "title": "Музей", "extract": "Музей — культурное учреждение Астаны. Здесь хранится коллекция.", "fullurl": "https://ru.wikipedia.org/wiki/Музей", "pageprops": {"wikibase_item": "Q1"}}]}})
    transport(monkeypatch, handle)
    result = wiki.enrich([original], tmp_path)
    poi = result["pois"][0]
    assert poi["description"].startswith("Музей — культурное учреждение Астаны.")
    assert poi["description_source"] == "wikipedia"
    assert poi["description_attribution"]["language"] == "ru"
    assert poi["description_attribution"]["origin"] == "wikipedia_article"
    assert poi["description_attribution"]["license"] == "CC-BY-SA-4.0"
    assert original["description"] is None


def test_enrich_uses_kk_after_empty_ru_and_preserves_supported_description(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": entity()}})
        is_kk = request.url.host == "kk.wikipedia.org"
        return httpx.Response(200, json={"query": {"pages": [{"pageid": 8, "title": "Мұражай" if is_kk else "Музей", "extract": "Астанада орналасқан мұражай." if is_kk else "", "fullurl": "https://kk.wikipedia.org/wiki/Мұражай" if is_kk else "https://ru.wikipedia.org/wiki/Музей"}]}})
    transport(monkeypatch, handle)
    records = [{"id": "wikidata:Q1", "wikidata_ids": ["Q1"]}, {"id": "osm:node/2", "raw_tags": {"wikidata": "Q1"}, "description": "Official original", "description_source": "website"}]
    result = wiki.enrich(records, tmp_path)
    assert result["pois"][0]["description"] == "Астанада орналасқан мұражай."
    assert result["pois"][0]["description_attribution"]["language"] == "kk"
    assert result["pois"][1]["description"] == "Official original"
    assert result["pois"][1]["description_source"] == "website"


def test_entity_only_description_never_claims_wikipedia_article(tmp_path, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"entities": {"Q1": entity(links=False)}}))
    result = wiki.enrich([{"id": "wikidata:Q1"}], tmp_path)
    poi = result["pois"][0]
    assert poi["wikidata_descriptions"]["ru"] == "музей в Астане"
    assert poi.get("description_source") != "wikipedia"
    assert not poi.get("description")


def test_enrich_resolves_osm_wikipedia_to_entity(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": entity()}})
        return httpx.Response(200, json={"query": {"pages": [{"pageid": 7, "title": "Музей", "extract": "Достоверный текст статьи.", "fullurl": "https://ru.wikipedia.org/wiki/Музей", "pageprops": {"wikibase_item": "Q1"}}]}})
    transport(monkeypatch, handle)
    result = wiki.enrich([{"id": "osm:node/9", "raw_tags": {"wikipedia": "ru:Музей"}}], tmp_path)
    poi = result["pois"][0]
    assert poi["wikidata_ids"] == ["Q1"]
    assert poi["description"] == "Достоверный текст статьи."


def test_enrich_caches_http_and_batches_max_50_entities(tmp_path, monkeypatch):
    seen = []
    def handle(request):
        ids = request.url.params["ids"].split("|")
        seen.append(len(ids))
        return httpx.Response(200, json={"entities": {q: entity(q, links=False) for q in ids}})
    transport(monkeypatch, handle)
    pois = [{"id": "wikidata:Q" + str(n)} for n in range(1, 53)]
    assert len(wiki.enrich(pois, tmp_path)["pois"]) == 52
    assert seen == [50, 2]
    assert len(wiki.enrich(pois, tmp_path)["pois"]) == 52
    assert seen == [50, 2]


def test_collect_reports_blocked_sources_without_fabrication(tmp_path, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(403, text="blocked"))
    result = wiki.collect(tmp_path)
    assert result["pois"] == []
    assert result["report"]["complete"] is False
    assert result["report"]["errors"]
    assert "fallback" in result["report"]


def test_collect_rejects_outside_coordinates(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == "query.wikidata.org":
            return httpx.Response(200, json={"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1"}, "coord": {"value": "Point(71.43 51.12)"}}]}})
        bad = entity()
        bad["claims"]["P625"][0]["mainsnak"]["datavalue"]["value"]["latitude"] = 53
        return httpx.Response(200, json={"entities": {"Q1": bad}})
    transport(monkeypatch, handle)
    assert wiki.collect(tmp_path)["pois"] == []


def test_collect_keeps_partial_sparql_candidates_if_later_page_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "PAGE_SIZE", 1)
    def handle(request):
        if request.url.host == "query.wikidata.org":
            if "OFFSET 0" in request.url.params["query"]:
                return httpx.Response(200, json={"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1"}}]}})
            return httpx.Response(403, text="blocked")
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": entity()}})
        return httpx.Response(403, text="blocked")
    transport(monkeypatch, handle)
    result = wiki.collect(tmp_path)
    assert [poi["id"] for poi in result["pois"]] == ["wikidata:Q1"]
    assert result["report"]["complete"] is False


def test_article_attribution_is_also_in_source_refs(tmp_path, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"query": {"pages": [{"pageid": 8, "title": "Музей", "extract": "Статья о музее.", "fullurl": "https://ru.wikipedia.org/wiki/Музей"}]}}))
    result = wiki.enrich([{"id": "osm:node/1", "raw_tags": {"wikipedia": "ru:Музей"}}], tmp_path)
    refs = result["pois"][0]["source_refs"]
    assert any(ref["source"] == "wikipedia" and ref["license"] == "CC-BY-SA-4.0" for ref in refs)


def test_failed_refresh_preserves_previous_nonempty_snapshot(tmp_path, monkeypatch):
    import json
    old = [{"id": "wikidata:Q7", "name": "Previously acquired"}]
    (tmp_path / "candidates.json").write_text(json.dumps(old))
    transport(monkeypatch, lambda request: httpx.Response(403, text="blocked"))
    result = wiki.collect(tmp_path, refresh=True)
    assert result["pois"] == old
    assert result["report"]["retained_previous_candidates"] == 1
    assert json.loads((tmp_path / "candidates.json").read_text()) == old


def test_partial_nonempty_discovery_preserves_other_previously_acquired_records(tmp_path, monkeypatch):
    import json
    old = [{"id": "wikipedia:ru:99", "name": "Earlier museum", "lat": 51.12, "lon": 71.43}]
    (tmp_path / "candidates.json").write_text(json.dumps(old))
    def handle(request):
        if request.url.host == "ru.wikipedia.org" and request.url.params.get("list") == "geosearch":
            return httpx.Response(200, json={"query": {"geosearch": [{"pageid": 7, "title": "New museum", "lat": 51.12, "lon": 71.43}]}})
        return httpx.Response(403, text="blocked")
    transport(monkeypatch, handle)
    result = wiki.collect(tmp_path, bbox=(51.10, 71.40, 51.15, 71.45))
    assert {p["id"] for p in result["pois"]} == {"wikipedia:ru:99", "wikipedia:ru:7"}


def test_geosearch_fallback_can_resolve_titles_through_wikidata_api(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == "query.wikidata.org":
            return httpx.Response(403, text="blocked")
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": entity()}})
        if request.url.params.get("list") == "geosearch":
            return httpx.Response(200, json={"query": {"geosearch": [{"pageid": 7, "title": "Музей", "lat": 51.12, "lon": 71.43}]}})
        return httpx.Response(403, text="article endpoint unavailable")
    transport(monkeypatch, handle)
    result = wiki.collect(tmp_path, bbox=(51.10, 71.40, 51.15, 71.45))
    assert "wikidata:Q1" in [poi["id"] for poi in result["pois"]]
    assert result["report"]["complete"] is False


def test_geosearch_articles_survive_failed_entity_resolution(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == "ru.wikipedia.org" and request.url.params.get("list") == "geosearch":
            return httpx.Response(200, json={"query": {"geosearch": [{"pageid": 7, "title": "Музей", "lat": 51.12, "lon": 71.43}]}})
        return httpx.Response(403, text="blocked")
    transport(monkeypatch, handle)
    result = wiki.collect(tmp_path, bbox=(51.10, 71.40, 51.15, 71.45))
    assert len(result["pois"]) == 1
    poi = result["pois"][0]
    assert (poi["id"], poi["name"], poi["lat"], poi["lon"], poi["category"]) == ("wikipedia:ru:7", "Музей", 51.12, 71.43, "other")
    assert poi["source"] == "wikipedia"
    assert poi["source_url"] == "https://ru.wikipedia.org/wiki/%D0%9C%D1%83%D0%B7%D0%B5%D0%B9"
    assert result["report"]["complete"] is False


def test_rate_limit_retry_after_survives_a_new_client(tmp_path, monkeypatch):
    import pytest
    transport(monkeypatch, lambda request: httpx.Response(429, headers={"Retry-After": "60"}, text="cool down"))
    first = wiki.WikimediaClient(tmp_path)
    with pytest.raises(RuntimeError):
        first.get("https://ru.wikipedia.org/w/api.php", {"action": "query"})
    first.close()
    second = wiki.WikimediaClient(tmp_path)
    with pytest.raises(RuntimeError):
        second.get("https://ru.wikipedia.org/w/api.php", {"action": "query", "titles": "New title"})
    assert second.report()["http_requests"] == 0
    second.close()


def test_forbidden_api_is_not_retried_because_url_contains_maxlag(tmp_path, monkeypatch):
    import pytest
    transport(monkeypatch, lambda request: httpx.Response(403, text="forbidden"))
    client = wiki.WikimediaClient(tmp_path)
    with pytest.raises(RuntimeError):
        client.get("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "maxlag": 5})
    assert client.report()["http_requests"] == 1
    client.close()


def test_semantic_entity_cache_fetches_only_missing_ids_after_batch_regrouping(tmp_path, monkeypatch):
    requested = []
    def handle(request):
        ids = request.url.params['ids'].split('|')
        requested.append(ids)
        return httpx.Response(200, json={'entities': {qid: entity(qid, links=False) for qid in ids}})
    transport(monkeypatch, handle)
    wiki.enrich([{'id':'wikidata:Q1'}, {'id':'wikidata:Q2'}, {'id':'wikidata:Q3'}], tmp_path)
    result = wiki.enrich([{'id':'wikidata:Q4'}, {'id':'wikidata:Q2'}], tmp_path)
    assert result['pois'][1]['wikidata_descriptions']['ru'] == 'музей в Астане'
    assert requested == [['Q1','Q2','Q3'], ['Q4']]


def test_semantic_article_cache_preserves_redirect_provenance_after_batch_regrouping(tmp_path, monkeypatch):
    def good(request):
        return httpx.Response(200,json={'query':{'normalized':[{'from':'старое имя','to':'Старое имя'}],
            'redirects':[{'from':'Старое имя','to':'Музей'}], 'pages':[
            {'pageid':7,'title':'Музей','extract':'Проверенный текст о музее.','fullurl':'https://ru.wikipedia.org/wiki/Музей','lastrevid':123},
            {'pageid':8,'title':'Другой','extract':'Проверенный текст о другом месте.','fullurl':'https://ru.wikipedia.org/wiki/Другой'}]}})
    transport(monkeypatch, good)
    first = wiki.enrich([{'id':'old:1','wikipedia':'ru:старое_имя'}, {'id':'old:2','wikipedia':'ru:Другой'}],tmp_path)
    transport(monkeypatch, lambda request: httpx.Response(403,text='provider unavailable'))
    result = wiki.enrich([{'id':'new:3','wikipedia':'ru:Третий'}, {'id':'old:2','wikipedia':'ru:Другой'}, {'id':'old:1','wikipedia':'ru:старое_имя'}],tmp_path)
    assert result['pois'][1].get('description') == 'Проверенный текст о другом месте.'
    recovered = result['pois'][2]
    assert recovered.get('description') == 'Проверенный текст о музее.'
    attribution = recovered['description_attribution']
    assert attribution['title'] == 'Музей'
    assert attribution['history_url'] == 'https://ru.wikipedia.org/w/index.php?title=%D0%9C%D1%83%D0%B7%D0%B5%D0%B9&action=history'
    assert attribution['license'] == 'CC-BY-SA-4.0'
    assert attribution['revision_id'] == 123
    assert attribution['raw_cache'].startswith('cache/')
    assert attribution['fetched_at'] == first['pois'][0]['description_attribution']['fetched_at']


def test_refresh_failure_falls_back_to_semantic_entity_and_article_cache(tmp_path, monkeypatch):
    def good(request):
        if request.url.host == 'www.wikidata.org':
            values={}
            for qid,title in [('Q1','Первый'),('Q2','Второй')]:
                item=entity(qid); item['sitelinks']={'ruwiki':{'title':title}}
                values[qid]=item
            return httpx.Response(200,json={'entities':values})
        return httpx.Response(200,json={'query':{'pages':[
            {'pageid':1,'title':'Первый','extract':'Первый подтверждённый текст.'},
            {'pageid':2,'title':'Второй','extract':'Второй подтверждённый текст.'}]}})
    transport(monkeypatch,good)
    first=wiki.enrich([{'id':'wikidata:Q1'},{'id':'wikidata:Q2'}],tmp_path)
    transport(monkeypatch,lambda request:httpx.Response(403,text='provider unavailable'))
    result=wiki.enrich([{'id':'wikidata:Q1'}],tmp_path,refresh=True)
    assert result['pois'][0].get('description') == 'Первый подтверждённый текст.'
    assert result['pois'][0]['description_attribution']['stale_cache'] is True
    assert result['pois'][0]['description_attribution']['fetched_at'] == first['pois'][0]['description_attribution']['fetched_at']
    assert result['report']['complete'] is False


def test_semantic_cache_cannot_enrich_a_suppressed_bad_wikimedia_link(tmp_path, monkeypatch):
    def handle(request):
        if request.url.host == 'www.wikidata.org':
            return httpx.Response(200,json={'entities':{'Q1':entity()}})
        return httpx.Response(200,json={'query':{'pages':[{'pageid':7,'title':'Музей','extract':'Текст другой организации.'}]}})
    transport(monkeypatch,handle)
    wiki.enrich([{'id':'wikidata:Q1'}],tmp_path)
    result=wiki.enrich([{'id':'osm:university','skip_wikimedia_enrichment':True,'raw_tags':{'wikidata':'Q1','wikipedia':'ru:Музей'}}],tmp_path)
    assert not result['pois'][0].get('description')
    assert result['report']['http_requests'] == 0
