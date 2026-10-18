import json

from data.collect.web_sources import parse_marwin, parse_dodo, attach_directory_facts


def test_marwin_ignores_partner_pickups_and_preserves_real_branch_coordinates():
    stores = [{"name": "MARWIN Mega Silk Way", "code": "store-1", "address": "Кабанбай батыра, 62",
               "schedule": "10:00–22:00", "location": {"lat": "51.089", "lng": "71.416"}},
              {"name": "Пункт выдачи Europharma", "code": "pickup-1", "location": {"lat": "51.13", "lng": "71.43"}}]
    config = {"*": {"Magento_Ui/js/core/app": {"components": {"shops": {"config": {
        "stores": {"astana": {"shops": stores}}}}}}}}
    html = '<script type="text/x-magento-init">' + json.dumps(config) + '</script>'
    pois = parse_marwin(html)
    assert len(pois) == 1 and pois[0]["id"] == "marwin:store-1"
    assert pois[0]["lat"] == 51.089 and pois[0]["lon"] == 71.416
    assert pois[0]["opening_hours"] is None  # human display text is not silently interpreted as OSM hours
    assert pois[0]["raw_tags"]["schedule_text"] == "10:00–22:00"


def test_dodo_does_not_turn_closed_or_delivery_only_units_into_open_restaurants():
    rows = [{"Id": "one", "Name": "Астана-1", "Alias": "Додо Пицца", "State": 1, "Type": 1,
             "LocalityName": "Астана", "Address": "Улица, 1", "Coordinates": {"Latitude": 51.13, "Longitude": 71.43}},
            {"Id": "closed", "State": 0, "Type": 1}, {"Id": "delivery", "State": 1, "Type": 2}]
    pois = parse_dodo(rows)
    assert len(pois) == 1 and pois[0]["id"] == "dodo:one"
    assert pois[0]["opening_hours"] is None and pois[0]["rating"] is None


def test_directory_facts_attach_only_to_unambiguous_matches():
    base = [{"id": "osm:1", "name": "Библиотека А", "lat": 51.13, "lon": 71.43,
             "source": "osm", "source_url": "https://www.openstreetmap.org/node/1", "category": "library", "address": "улица Мира, 7"},
            {"id": "osm:2", "name": "Сеть", "lat": 51.14, "lon": 71.44},
            {"id": "osm:3", "name": "Сеть", "lat": 51.15, "lon": 71.45}]
    facts = [{"id": "library:a", "name": "Библиотека А", "source": "astana_library",
              "source_url": "https://astana-library.kz/contacts", "category": "library", "phone": "+7 7172 123456", "address": "улица Мира, 7"},
             {"id": "directory:ambiguous", "name": "Сеть", "source": "website", "source_url": "https://example.org"}]
    attached, unresolved = attach_directory_facts(base, facts)
    assert len(attached) == 1 and len(unresolved) == 1
    assert attached[0]["lat"] == 51.13 and attached[0]["phone"] == "+7 7172 123456"
    assert attached[0]["coordinate_source_id"] == "osm:1"


def test_dodo_uses_restaurant_week_seconds_and_excludes_temporary_closure():
    from data.collect import web_sources as web
    week = [{"DayIndex": n, "DayAlias": name, "WorkingTimeStart": 32400, "WorkingTimeEnd": 0}
            for n, name in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])]
    active = {"Id": "active", "Name": "Астана-1", "State": 1, "Type": 1,
              "Location": {"Latitude": 51.13, "Longitude": 71.43}, "RestaurantWeekWorkingTime": week,
              "IsTemporarilyClosed": False, "AddressDetails": {"LocalityName": "Астана"}}
    closed = {**active, "Id": "temp", "IsTemporarilyClosed": True}
    records = web.parse_dodo([active, closed])
    assert [p["id"] for p in records] == ["dodo:active"]
    assert records[0]["opening_hours"] == "Mo-Su 09:00-24:00"
    assert records[0]["raw_tags"]["restaurant_week_working_time"] == week
    assert records[0]["raw_tags"]["temporarily_closed"] is False


def test_citypass_reads_every_hydrated_attraction_with_source_coordinates():
    from data.collect import web_sources as web
    rows = [{"id": n, "slug": "museum-" + str(n), "title": "Museum " + str(n), "address": "Street " + str(n),
             "latitude": "51.13", "longitude": "71.43", "work_period": "Daily", "work_time": "09:00-21:00",
             "tags": [{"slug": "museum", "name": "Museum"}], "description": "not copied"} for n in range(1,15)]
    payload = '5:' + json.dumps(["$", "Component", None, {"initialItems": rows, "totalCount": 14}])
    html = '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'
    result = web.parse_citypass(html, "https://astana.citypass.kz/en/attractions")
    assert len(result) == 14
    assert result[-1]["id"] == "citypass:14"
    assert result[0]["lat"] == 51.13 and result[0]["address"] == "Street 1"
    assert result[0]["opening_hours"] == "Mo-Su 09:00-21:00"
    assert result[0]["description"] is None
    assert result[0]["category"] == "museum"


def test_sxodim_listing_keeps_card_address_and_excludes_event_links():
    from data.collect import web_sources as web
    html = '''<div class="impression-card" data-id="7" data-title="Real Coffee">
      <a class="impression-card-title" href="https://sxodim.com/astana/place/real-coffee">Real Coffee</a>
      <div class="impression-card-info">Астана, улица Мира, 7</div></div>
      <a href="https://sxodim.com/astana/event/party">Party</a>'''
    records = web.parse_sxodim(html, "https://sxodim.com/astana/places/kofejni", "cafe")
    assert len(records) == 1
    assert (records[0]["id"], records[0]["name"], records[0]["address"]) == ("sxodim:7", "Real Coffee", "Астана, улица Мира, 7")
    assert records[0].get("lat") is None


def test_pagination_follows_all_advertised_same_directory_pages_without_total_cap():
    from data.collect import web_sources as web
    pages = {
      "https://sxodim.com/astana/places/kofejni": '<a href="?page=2" rel="next">Next</a>',
      "https://sxodim.com/astana/places/kofejni?page=2": '<a href="?page=3">3</a>',
      "https://sxodim.com/astana/places/kofejni?page=3": '<a href="?page=2">2</a><a href="https://other.test/?page=4">4</a>',
    }
    class LocalFetcher:
        def get(self, url):
            return pages[url]
    result = list(web.iter_directory_pages(LocalFetcher(), next(iter(pages))))
    assert [url for url, _ in result] == list(pages)


def test_mega_keeps_official_branch_hours_without_inventing_coordinates():
    from data.collect import web_sources as web
    html = '''<div class="rest-card"><div class="logo-container"><img class="logo" alt="logo_starbucks" src="/media/images/logo_starbucks.svg"></div>
      <span class="address">MEGA Silk Way, 1 этаж<br>Ежедневно 8:00 – 23:00</span></div>
      <div class="rest-card"><img class="logo" alt="logo_other" src="/other.svg"><span class="address">MEGA Alma-Ata, 2 этаж<br>Ежедневно 10:00-22:00</span></div>'''
    records = web.parse_mega_restaurants(html, "https://restaurants.mega.kz/ru/?sm=2")
    assert len(records) == 1
    assert records[0]["name"] == "Starbucks"
    assert records[0]["opening_hours"] == "Mo-Su 08:00-23:00"
    assert records[0].get("lat") is None
    assert records[0]["raw_tags"]["mall"] == "MEGA Silk Way"
    assert records[0]["source_license"] == "not_specified"


def test_failed_provider_retains_prior_but_valid_closed_dodo_does_not(tmp_path, monkeypatch):
    from data.collect import web_sources as web
    prior = [{"id": "marwin:old", "source": "marwin", "name": "Old branch", "lat": 51.13, "lon": 71.43},
             {"id": "dodo:closed", "source": "dodo", "name": "Closed branch", "lat": 51.13, "lon": 71.43}]
    (tmp_path / "candidates.json").write_text(json.dumps(prior))
    class LocalFetcher:
        def __init__(self, raw_dir, refresh):
            self.log = []
        def get(self, url, **kwargs):
            if 'marwin.kz' in url:
                raise RuntimeError('provider unavailable')
            if 'dodois.io' in url:
                return json.dumps([{"Id": "closed", "Name": "Closed branch", "State": 1, "Type": 1,
                    "Location": {"Latitude": 51.13, "Longitude": 71.43}, "IsTemporarilyClosed": True}])
            return '<html></html>'
        def close(self):
            pass
    monkeypatch.setattr(web, 'Fetcher', LocalFetcher)
    result = web.collect(tmp_path)
    assert [p['id'] for p in result['pois']] == ['marwin:old']
    assert result['pois'][0]['stale_cache'] is True


def test_sxodim_does_not_reclassify_promoted_coffee_as_a_park():
    from data.collect import web_sources as web
    html = '''<div class="impression-best"><div class="impression-card" data-id="7" data-title="Coffee ad">
       <a class="impression-card-title" href="/astana/place/coffee-ad">Coffee ad</a></div></div>
       <div class="impression-items"><div class="impression-card" data-id="8" data-title="Real park">
       <a class="impression-card-title" href="/astana/place/real-park">Real park</a>
       <div class="impression-card-info">Астана, парк</div></div></div>'''
    result = web.parse_sxodim(html, 'https://sxodim.com/astana/places/parki-skvery-i-allei', 'park')
    assert [p['name'] for p in result] == ['Real park']


def test_empty_unrecognized_marwin_response_retains_existing_branch(tmp_path, monkeypatch):
    from data.collect import web_sources as web
    (tmp_path / 'candidates.json').write_text(json.dumps([{'id':'marwin:old','source':'marwin','name':'MARWIN','lat':51.13,'lon':71.43}]))
    class LocalFetcher:
        def __init__(self, raw_dir, refresh): self.log=[]
        def get(self, url, **kwargs): return '[]' if 'dodois.io' in url else '<html>Maintenance</html>'
        def close(self): pass
    monkeypatch.setattr(web, 'Fetcher', LocalFetcher)
    result=web.collect(tmp_path)
    assert [p['id'] for p in result['pois']] == ['marwin:old']
    assert result['pois'][0]['stale_cache'] is True


def test_posted_hours_parse_explicit_weekday_ranges_and_leave_tour_times_unknown():
    from data.collect import web_sources as web
    assert web._posted_hours('Tuesday - Sunday', '09:00-18:00') == 'Tu-Su 09:00-18:00'
    assert web._posted_hours('Вторник - Суббота', '10:00 – 18:00') == 'Tu-Sa 10:00-18:00'
    assert web._posted_hours('Tuesday — Sunday, 10:00-18:30. Monday is a technical day.', '') == 'Tu-Su 10:00-18:30'
    assert web._posted_hours('Ежедневно. Кроме понедельника.', '11:00; 15:00') is None
    assert web._posted_hours('', '10:00-23:00') is None


def test_dodo_error_object_is_not_treated_as_a_valid_empty_directory():
    import pytest
    from data.collect import web_sources as web
    with pytest.raises(ValueError):
        web.parse_dodo({'error':'maintenance'})


def test_unrecognized_empty_html_directory_retains_prior_provider_facts(tmp_path, monkeypatch):
    from data.collect import web_sources as web
    (tmp_path / 'unlocated.json').write_text(json.dumps([{'id':'greenmall:old','source':'greenmall','name':'Named store','category':'other'}]))
    class LocalFetcher:
        def __init__(self, raw_dir, refresh): self.log=[]
        def get(self, url, **kwargs): return '[]' if 'dodois.io' in url else '<html>Maintenance</html>'
        def close(self): pass
    monkeypatch.setattr(web, 'Fetcher', LocalFetcher)
    result=web.collect(tmp_path)
    assert [p['id'] for p in result['unlocated']] == ['greenmall:old']
    assert result['unlocated'][0]['stale_cache'] is True


def test_mall_scope_rejects_real_wrong_rumi_branch_and_accepts_nearby_coco():
    base = [
        {'id':'osm:mall','name':'Mega Silk Way','category':'mall','lat':51.0890897,'lon':71.40733035},
        {'id':'overture:mall','name':'Mega Silk Way','category':'mall','lat':51.089188,'lon':71.4062},
        {'id':'overture:rumi','name':'Rumi','category':'restaurant','lat':51.16236738,'lon':71.42142318},
        {'id':'osm:coco','name':'COCO','category':'cafe','lat':51.0891569,'lon':71.4087027},
    ]
    facts=[{'id':'mega:rumi','source':'mega_silkway','name':'Rumi','category':'restaurant','raw_tags':{'mall':'MEGA Silk Way'}},
           {'id':'mega:coco','source':'mega_silkway','name':'COCO','category':'restaurant','raw_tags':{'mall':'MEGA Silk Way'}}]
    attached, unresolved=attach_directory_facts(base,facts)
    assert [p['id']for p in attached] == ['mega:coco']
    assert [p['id']for p in unresolved] == ['mega:rumi']
    assert attached[0]['coordinate_source_id'] == 'osm:coco'
    assert attached[0]['coordinate_match_verified'] is True
    assert attached[0]['coordinate_match_method'] == 'mall_scope'


def test_mall_scope_requires_one_physical_anchor_cluster():
    venue={'id':'osm:coffee','name':'Coffee','category':'cafe','lat':51.13031,'lon':71.39005}
    fact={'id':'green:coffee','source':'greenmall','name':'Coffee','category':'cafe'}
    # The source offers no verified anchor here, so a matching venue alone is insufficient.
    assert attach_directory_facts([venue],[fact])[0] == []
    anchors=[{'id':'mall:1','name':'Green Mall','category':'mall','lat':51.1303,'lon':71.3900487},
             {'id':'mall:2','name':'GreenMall','category':'mall','lat':51.12465,'lon':71.4237}]
    assert attach_directory_facts(anchors+[venue],[fact])[0] == []


def test_directory_join_requires_matching_street_and_house_and_compatible_category():
    base=[{'id':'osm:venue','name':'Unique Coffee','category':'cafe','lat':51.13,'lon':71.43,'address':'Dostyk Street 13'}]
    facts=[{'id':'sx:good','source':'sxodim','name':'Unique Coffee','category':'restaurant','address':'улица Достык, 13'},
           {'id':'sx:otherstreet','source':'sxodim','name':'Unique Coffee','category':'cafe','address':'улица Мира, 13'},
           {'id':'sx:otherhouse','source':'sxodim','name':'Unique Coffee','category':'cafe','address':'улица Достык, 15'},
           {'id':'sx:city','source':'sxodim','name':'Unique Coffee','category':'cafe','address':'Астана'},
           {'id':'sx:nohouse','source':'sxodim','name':'Unique Coffee','category':'cafe','address':'улица Достык'},
           {'id':'sx:wrongtype','source':'sxodim','name':'Unique Coffee','category':'park','address':'улица Достык, 13'}]
    attached, unresolved=attach_directory_facts(base,facts)
    assert [p['id']for p in attached] == ['sx:good']
    assert len(unresolved) == 5
    assert attached[0]['coordinate_match_method'] == 'street_address'
    assert attached[0]['coordinate_match_verified'] is True


def test_proven_address_can_disambiguate_same_name_branches():
    base=[{'id':'osm:a','name':'Coffee','category':'cafe','lat':51.13,'lon':71.43,'address':'улица Мира, 7'},
          {'id':'osm:b','name':'Coffee','category':'cafe','lat':51.14,'lon':71.44,'address':'улица Мира, 9'}]
    fact={'id':'sx:a','source':'sxodim','name':'Coffee','category':'cafe','address':'улица Мира, 7'}
    attached, unresolved=attach_directory_facts(base,[fact])
    assert not unresolved and attached[0]['coordinate_source_id'] == 'osm:a'


def test_greenmall_name_uses_brand_heading_and_preserves_hours_separately():
    from data.collect import web_sources as web
    html='''<a class="brend__small" href="https://greenmall.kz/ru/brands/espresso-day">
        <p class="brend__small-text-title">Espresso Day</p>
        <p class="brend__small-text-date">10:00-21:00</p>
        <p class="brend__small-text-category">Кофейня</p></a>'''
    rows=web._directory_facts(html,'greenmall','https://greenmall.kz/ru/brands',r'/brands/[^/?#]+','other')
    assert rows[0]['name'] == 'Espresso Day'
    assert rows[0]['raw_tags']['schedule_text'] == '10:00-21:00'
    assert rows[0]['opening_hours'] is None
