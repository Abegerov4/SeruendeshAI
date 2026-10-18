# Проверка текущего кода Data

Дата подготовки: 18 октября 2026. Data создавалась параллельно другой работой; QA не изменяла эти исходники или тесты.

Последний общий прогон: **377 passed / 4 failed / 57 skipped**. Исходники Data менялись во время этого прогона: **нет**.

Это результат конкретного среза, а не утверждение о ещё не завершённой версии. Полный JUnit и журнал — в `eval/evidence/`.

## Невыполненные ожидания в этом срезе

### `data.tests.test_web_sources::test_dodo_uses_restaurant_week_seconds_and_excludes_temporary_closure`

```text
AssertionError: assert ['dodo:active', 'dodo:temp'] == ['dodo:active']

  Left contains one more item: 'dodo:temp'
  Use -v to get more diff
def test_dodo_uses_restaurant_week_seconds_and_excludes_temporary_closure():
        from data.collect import web_sources as web
        week = [{"DayIndex": n, "DayAlias": name, "WorkingTimeStart": 32400, "WorkingTimeEnd": 0}
                for n, name in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])]
        active = {"Id": "active", "Name": "Астана-1", "State": 1, "Type": 1,
                  "Location": {"Latitude": 51.13, "Longitude": 71.43}, "RestaurantWeekWorkingTime": week,
                  "IsTemporarilyClosed": False, "AddressDetails": {"LocalityName": "Астана"}}
        closed = {**active, "Id": "temp", "IsTemporarilyClosed": True}
        records = web.parse_dodo([active, closed])
>       assert [p["id"] for p in records] == ["dodo:active"]
E       AssertionError: assert ['dodo:active', 'dodo:temp'] == ['dodo:active']
E
E         Left contains one more item: 'dodo:temp'
E         Use -v to get more diff

data/tests/test_web_sources.py:52: AssertionError
```

### `data.tests.test_web_sources::test_citypass_reads_every_hydrated_attraction_with_source_coordinates`

```text
AttributeError: module 'data.collect.web_sources' has no attribute 'parse_citypass'
def test_citypass_reads_every_hydrated_attraction_with_source_coordinates():
        from data.collect import web_sources as web
        rows = [{"id": n, "slug": "museum-" + str(n), "title": "Museum " + str(n), "address": "Street " + str(n),
                 "latitude": "51.13", "longitude": "71.43", "work_period": "Daily", "work_time": "09:00-21:00",
                 "tags": [{"slug": "museum", "name": "Museum"}], "description": "not copied"} for n in range(1,15)]
        payload = '5:' + json.dumps(["$", "Component", None, {"initialItems": rows, "totalCount": 14}])
        html = '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'
>       result = web.parse_citypass(html, "https://astana.citypass.kz/en/attractions")
                 ^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'data.collect.web_sources' has no attribute 'parse_citypass'

data/tests/test_web_sources.py:65: AttributeError
```

### `data.tests.test_web_sources::test_sxodim_listing_keeps_card_address_and_excludes_event_links`

```text
AttributeError: module 'data.collect.web_sources' has no attribute 'parse_sxodim'. Did you mean: 'parse_dodo'?
def test_sxodim_listing_keeps_card_address_and_excludes_event_links():
        from data.collect import web_sources as web
        html = '''<div class="impression-card" data-id="7" data-title="Real Coffee">
          <a class="impression-card-title" href="https://sxodim.com/astana/place/real-coffee">Real Coffee</a>
          <div class="impression-card-info">Астана, улица Мира, 7</div></div>
          <a href="https://sxodim.com/astana/event/party">Party</a>'''
>       records = web.parse_sxodim(html, "https://sxodim.com/astana/places/kofejni", "cafe")
                  ^^^^^^^^^^^^^^^^
E       AttributeError: module 'data.collect.web_sources' has no attribute 'parse_sxodim'. Did you mean: 'parse_dodo'?

data/tests/test_web_sources.py:80: AttributeError
```

### `data.tests.test_web_sources::test_pagination_follows_all_advertised_same_directory_pages_without_total_cap`

```text
AttributeError: module 'data.collect.web_sources' has no attribute 'iter_directory_pages'
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
>       result = list(web.iter_directory_pages(LocalFetcher(), next(iter(pages))))
                      ^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: module 'data.collect.web_sources' has no attribute 'iter_directory_pages'

data/tests/test_web_sources.py:96: AttributeError
```

## Перед повторным прогоном

Запустить `python -m pytest` после завершения текущих правок Data. Зависимости коллектора нужны дополнительно к QA: `pyarrow`, `beautifulsoup4`, `shapely`, `osmium`, `overturemaps` (версии проверенного окружения сохранены в evidence). Не менять ожидания тестов ради зелёной сводки; сначала сверить фактическое требование.

Найденные ранее проверки повреждённого PBF, паузы после 429, сохранения metadata при DNS-сбое и исключения vacant-объектов проходили повторную оценку по мере параллельных правок. Актуальный статус каждого теста определяет сохранённый JUnit, а не ранний промежуточный лог.
