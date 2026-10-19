"""Build reviewed service facts from captured public pages, without generation APIs."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from data.city_services import CityServicesCatalog

OUT = Path(__file__).resolve().parent
SOURCES = {path.stem.removeprefix("services-source-"): json.loads(path.read_text())
           for path in OUT.glob("services-source-*.json") if path.stem != "services-source-manifest"}


def ev(key, excerpt, validity=None):
    source = SOURCES[key]
    assert source["status"] == 200
    assert excerpt in source["text"] or excerpt in source.get("full_text", ""), (key, excerpt)
    return {"source_url": source["source_url"], "checked_at": source["checked_at"], "excerpt": excerpt,
            "validity": validity or {"precision": "undated"},
            "archive_path": str((OUT / f"services-source-{key}.json").relative_to(ROOT))}


def fact(field, value, evidence, **kwargs):
    return {"field": field, "value": value, "evidence": evidence, **kwargs}


def offer(identifier, name, audience, amount, evidence, **kwargs):
    return {"id": identifier, "name": name, "audience": audience, "amount": amount,
            "currency": "KZT", "unit": "per_person", "evidence": evidence, **kwargs}


def stop(identifier, name, role, evidence, **kwargs):
    return {"id": identifier, "name": name, "role": role, "evidence": evidence, **kwargs}


def service(identifier, name, kind, key, title, aliases, **kwargs):
    return {"id": identifier, "name": name, "kind": kind, "aliases": aliases,
            "evidence": [ev(key, title)], **kwargs}


def build():
    redbus_price = [ev("redbus-routes", "Взрослый билет 6 000 тенге Льготный билет для детей и пенсионеров 3 000 тенге"),
                    ev("visit-redbus", "Стоимость: 6 000 ₸ с человека (взрослый билет) / 3 000 ₸ (льготный билет — дети, многодетные семьи, пенсионеры, лица с инвалидностью II и III группы)")]
    redbus_free = ev("redbus-routes", "Детям до 3 лет (включительно) бесплатно * Без предоставления места")
    redbus_faq_age = ev("redbus-faq", "льготные билеты (3000 ₽) доступны для детей в возрасте от 3 до 15 лет")
    # This control says Borovoe, so it is evidence of page ambiguity, not Astana age policy.
    redbus_borovoe_age = ev("redbus-routes", "Оформление билета Боровое Пассажиры Взрослый 6 000 ₸ / чел. − 1 + Льготный До 12 лет · 3 000 ₸ / чел.")
    boarding_evidence = ev("redbus-routes", "Посадка перед главным входом в Байтерек")
    boarding = stop("stop:redbus-baiterek", "Перед главным входом в монумент «Астана-Байтерек»", "boarding",
                    [boarding_evidence, ev("redbus-routes", "Место посадки на карте 2GIS")],
                    map_url="https://2gis.kz/astana/firm/70000001089193403",
                    notes="Ссылка места посадки опубликована оператором. Координаты и canonical_poi_id не установлены: одноимённая запись OSM является городским автобусным остановочным пунктом.")
    left = ["Монумент «Байтерек» и бульвар Нуржол", "Театр «Астана Опера»", "ТРЦ «Хан Шатыр» и Парк влюблённых",
            "Медицинский кластер", "«Барыс Арена» и «Астана Арена»", "Легкоатлетический спортивный комплекс Qazaqstan",
            "Назарбаев Университет", "Театр «Астана Балет» и Казахская национальная академия хореографии",
            "EXPO и сфера «Нур Алем»", "MEGA Silk Way", "Главная Республиканская мечеть",
            "Триумфальная арка «Мәңгілік Ел»", "Ботанический сад", "Abu Dhabi Plaza"]
    right = ["Монумент «Байтерек» и бульвар Нуржол", "ЖК «Триумф Астаны»", "Астана Цирк", "Площадь государственных символов",
             "Центр семейного отдыха Ailand", "Памятник Курмангазы", "Столичный парк", "Набережная реки Есиль",
             "Государственная филармония и Демалыс Променад", "Проспект Республики", "Парк Жамбыла Жабаева",
             "Триатлон-парк", "Дворец мира и согласия", "Площадь и монумент «Қазақ елі»",
             "Национальный музей Республики Казахстан", "Президентский парк"]
    routes = []
    for bank, names, label in [("left", left, "Левый берег 14 локаций"), ("right", right, "Правый берег 16 локаций")]:
        locations = [stop(f"location:redbus-{bank}-{index}", name, "pass_by", [ev("redbus-routes", name)],
                          notes="Объект из списка «Что мы посмотрим?». Это не подтверждение посадки или высадки пассажиров.")
                     for index, name in enumerate(names, 1)]
        routes.append({"id": f"route:redbus-{bank}", "name": "Левый берег" if bank == "left" else "Правый берег",
                       "evidence": [ev("redbus-routes", label)], "stops": [deepcopy(boarding), *locations]})
    raw_schedule = "12.10 - 11:00 / 14:00 / 16:00 / 18:00 13.10 - 11:00 / 18:00 14.10 - 14:00 / 16:00 / 18:00 15.10 - 11:00 / 13:00 / 15:00 / 17:00 16.10 - 11:00 / 13:00 / 15:00 / 17:00 17.10 - 11:00 / 13:00 / 15:00 / 17:00 18.10 - 11:00 / 13:00 / 15:00 / 17:00"
    yearless = {"precision": "year_unspecified", "notes": "На странице указаны день и месяц 12.10–18.10 без года. Датированные отправления не создаются; расписание на 19.10 не опубликовано в этом блоке."}
    redbus = service("service:redbus-astana", "RedBus — обзорная экскурсия по Астане", "bus_tour", "redbus-routes",
                     "Экскурсии по городу Астана на двухэтажных автобусах Red Bus.",
                     {"ru": ["РедБас", "Ред Бас", "Красный автобус", "двухэтажный автобус", "Red Bus Астана"],
                      "kk": ["RedBus Астана", "Редбас", "екі қабатты автобус", "қалаға шолу экскурсиясы"],
                      "en": ["RedBus Astana", "Red Bus", "double decker sightseeing bus", "Astana sightseeing bus"]},
                     operator_id="operator:crocos-travel", routes=routes, schedule_status="date_unverified", dated_departures=[],
                     ticket_offers=[offer("ticket:redbus-adult", "Взрослый билет", "Взрослый", 6000, redbus_price),
                                    offer("ticket:redbus-concession", "Льготный билет", "Дети и пенсионеры; другие льготные категории по условиям оператора", 3000,
                                          redbus_price, notes="Возрастные границы детской льготы расходятся на страницах оператора; уточните возраст ребёнка и условия у оператора."),
                                    offer("ticket:redbus-child-free", "Бесплатно без отдельного места", "Ребёнок до 3 лет включительно, по странице маршрутов", 0,
                                          [redbus_free, redbus_faq_age], age_max=3, age_max_inclusive=True, status="conflicting",
                                          notes="Страница маршрутов включает 3 года в бесплатную категорию; FAQ назначает льготный билет с 3 лет. Не обещать бесплатный проезд трёхлетнему без уточнения.")],
                     facts=[fact("duration_minutes", ["Маршруты/расписание: 60–90", "FAQ: 120", "Visit Astana: 90–120"],
                                 [ev("redbus-routes", "Длительность маршрута 1-1,5 часа"),
                                  ev("redbus-faq", "Продолжительность маршрута составляет 2 часа."),
                                  ev("visit-redbus", "Продолжительность: 1,5–2 часа")], unit="minutes", status="conflicting",
                                 notes="Длительность расходится между официальными страницами; сообщать диапазон источников и уточнять конкретный маршрут."),
                            fact("child_age_policy", ["Маршруты: до 3 лет включительно бесплатно без места", "FAQ: льготный билет с 3 до 15 лет"],
                                 [redbus_free, redbus_faq_age], status="conflicting",
                                 notes="В модальном блоке Боровое также указано «До 12 лет», но это другой город: не переносить на Астану."),
                            fact("concession_currency", ["Маршруты и Visit Astana: 3000 KZT", "FAQ: 3000 ₽"],
                                 [*redbus_price, redbus_faq_age], status="conflicting",
                                 notes="Не исправлять символ валюты в исходной FAQ без подтверждения. Для оценки бюджета указаны подтверждённые цены в тенге со страницы маршрутов и Visit Astana."),
                            fact("published_schedule_notice", raw_schedule, [ev("redbus-routes", raw_schedule, yearless)], validity=yearless),
                            fact("other_undated_schedule", "Visit Astana перечисляет сеансы 11:00 / 14:00 / 17:00 без даты; таблица оператора также содержит иные круги.",
                                 [ev("visit-redbus", "сеансы: 11:00 / 14:00 / 17:00"), ev("redbus-routes", "Монумент Астана-Байтерек 19:45 20:00")],
                                 status="conflicting", notes="Не использовать эти строки для ответа о последнем рейсе сегодня."),
                            fact("route_alternation", "Маршруты по правому и левому берегу чередуются; привязка к рейсам не опубликована.",
                                 [ev("redbus-routes", "экскурсии по правому и левому берегу горду будут чередоваться.")]),
                            fact("languages", ["kk", "ru", "en"], [ev("visit-redbus", "Язык проведения: казахский, русский, английский")]),
                            fact("wheelchair_access", True, [ev("redbus-faq", "наш автобус оборудован для доступа инвалидных колясок.")]),
                            fact("route_location_counts", ["Левый берег: 14", "Правый берег: 16"],
                                 [ev("redbus-routes", "Левый берег 14 локаций"), ev("redbus-routes", "Правый берег 16 локаций")],
                                 notes="Число достопримечательностей; не количество мест посадки."),
                            fact("legacy_stop_table", "В недатированной таблице указаны ЦСО Айланд, Лодочная станция (Набережная), Хан Шатыр, Триумфальная арка; актуальность посадки требует уточнения.",
                                 [ev("redbus-routes", "ЦСО Айланд Остановка по требованию Остановка по требованию Лодочная станция (Набережная) 11:30 11:40 ТРЦ Хан Шатыр Остановка по требованию Остановка по требованию Триумфальная Арка Остановка по требованию")],
                                 status="conflicting", notes="Не смешивать со списком 14/16 локаций. Текущий блок посадки указывает главный вход Байтерека.")],
                     booking_rules=[fact("boarding_minutes_before_departure", 20, [ev("redbus-routes", "посадка на автобус начинается строго за 20 минут до времени отправления")], unit="minutes"),
                                    fact("boarding_queue", "Живая очередь независимо от наличия билета", [ev("redbus-routes", "осуществляется в порядке живой очереди, независимо от наличия билета.")]),
                                    fact("seat_reservation", False, [ev("redbus-faq", "бронирование мест не предусмотрено.")]),
                                    fact("ticket_sales", "На сайте, в кассе у Байтерека и в автобусе на остановках", [ev("redbus-faq", "Билеты можно приобрести онлайн на нашем сайте или на кассе около Монумента «Астана-Байтерек». Также билеты можно приобрести на других остановках внутри автобуса.")]),
                                    fact("confirm_schedule", "Уточнить расписание до посещения по +7 777 555 7575", [ev("redbus-routes", "Рекомендуем уточнять расписание перед посещением экскурсии, так как оно может меняться."), ev("redbus-routes", "Узнай больше о RedBus: +7 777 555 7575")])])

    river_price = "Стоимость: группа от 3 человек — 250 у.е. за группу (в тенге по курсу на день оплаты)"
    river_season = {"precision": "seasonal", "months": [5, 6, 7, 8, 9, 10], "notes": "Указан сезон май–октябрь; конкретные даты и навигация на 19 октября не подтверждены."}
    river_parks = service("service:dual-parks-river", "Пеший сити-тур по паркам с прогулкой по Ишиму", "city_tour", "river-parks",
                          "Пеший групповой сити-тур по паркам Астаны с прогулкой на теплоходе по Ишиму",
                          {"ru": ["теплоход", "Ишим", "Есиль", "парки и речная прогулка", "Dual.KZ"],
                           "kk": ["Есілдегі кеме серуені", "саябақтар экскурсиясы"], "en": ["Ishim river cruise and parks tour", "Dual.KZ", "Esil boat tour"]},
                          operator_id="operator:dual-kz", schedule_status="on_request",
                          facts=[fact("duration_minutes", 450, [ev("river-parks", "Маршрут длится с 10:00 до 17:30")], unit="minutes"),
                                 fact("river_segment_minutes", 45, [ev("river-parks", "речная прогулка — около 45 минут")], unit="minutes"),
                                 fact("season", "Май–октябрь", [ev("river-parks", "Сезон: с мая по октябрь", river_season)], validity=river_season),
                                 fact("group_minimum", 3, [ev("river-parks", river_price)]),
                                 fact("group_price_text", "250 у.е. за группу; оплата в тенге по курсу дня", [ev("river-parks", river_price)],
                                      notes="Валюта у.е. и курс не определены. Не преобразовывать в USD/KZT и не использовать средний чек ~118000 как подтверждённую цену."),
                                 fact("included", ["Сопровождение гида", "Билеты в парки", "Теплоход", "Юрта"],
                                      [ev("river-parks", "Что входит: сопровождение квалифицированного гида; билеты на посещение парков, теплохода и юрты.")]),
                                 fact("river_stop_names", ["Центральный парк", "Чубары", "Времена года", "Самал", "памятник Кенесары", "Radisson"],
                                      [ev("river-parks", "Пассажирский маршрут насчитывает 6 остановок: Центральный парк, микрорайон Чубары, сквер «Времена года», микрорайон «Самал», памятник Кенесары и отель Radisson.")],
                                      notes="Описаны остановки речного маршрута; конкретная точка сбора этого пакетного тура не подтверждена.")],
                          booking_rules=[fact("booking_contact", "+7 707 828 15 48; dualkz@bk.ru", [ev("river-parks", "Телефон: +7 707 828 15 48 E-mail: dualkz@bk.ru")])])

    river_fare = ev("river-necklace", "Стоимость: 20 000 тг за аренду катера + 4 000 тг с человека (входной билет)")
    river = service("service:blue-necklace-river", "Голубое ожерелье столицы — прогулка на катере", "river_cruise", "river-necklace",
                    "«Голубое ожерелье столицы»",
                    {"ru": ["катер", "речная прогулка", "Есиль", "Ишим", "Голубое ожерелье столицы"],
                     "kk": ["Есілде катермен серуен", "өзен серуені"], "en": ["Blue Necklace of the Capital", "Esil boat cruise", "Ishim river boat"]},
                    schedule_status="not_published",
                    ticket_offers=[offer("ticket:blue-necklace-boat", "Аренда катера", "Группа, аренда катера", 20000, [river_fare], unit="per_group", notes="К аренде дополнительно 4000 тенге с каждого человека."),
                                   offer("ticket:blue-necklace-entry", "Входной билет, доплата к аренде", "Каждый участник", 4000, [river_fare], notes="Не является полной стоимостью прогулки: дополнительно 20000 тенге за катер.")],
                    facts=[fact("duration_minutes", 60, [ev("river-necklace", "Продолжительность: 1 час")], unit="minutes"),
                           fact("languages", ["kk", "ru", "en"], [ev("river-necklace", "Языки проведения: казахский, русский, английский")]),
                           fact("price_formula", "20000 KZT за катер + 4000 KZT × число участников", [river_fare])])

    museum = service("service:national-museum-gold", "Экскурсия по залам «Золото» Национального музея", "guided_museum", "gold-museum",
                     "Экскурсия по залам «Золото»",
                     {"ru": ["Национальный музей", "Золотой человек", "Золото 1", "Золото 2"],
                      "kk": ["Ұлттық музей", "Алтын адам", "Алтын залдары"], "en": ["National Museum gold halls tour", "Golden Man", "Gold halls"]},
                     operator_id="operator:national-museum", schedule_status="on_request",
                     facts=[fact("duration_minutes", 60, [ev("gold-museum", "Продолжительность: 1 час (полный осмотр всех залов музея занимает от 2 до 4 часов)")], unit="minutes"),
                            fact("address", "Астана, проспект Тауелсиздик, 54", [ev("gold-museum", "Адрес: г. Астана, проспект Тауелсиздик, 54")]),
                            fact("venue_hours", "Вторник–воскресенье 09:30–18:00; последний вход и касса до 17:00; понедельник технический день; последний вторник месяца санитарный день.",
                                 [ev("gold-museum", "График работы: вторник–воскресенье 09:30–18:00 (касса до 17:00, последний вход в 17:00). Технический день — понедельник, санитарный день — последний вторник месяца.")],
                                 notes="Это часы музея, не подтверждённые часы начала экскурсии."),
                            fact("advertised_average_spend", 2000, [ev("gold-museum", "Средний чек:: ~2000 тг")], unit="KZT",
                                 notes="Средний чек страницы, не официальный тариф входного/экскурсионного билета; ticket_offers остаются пустыми.")],
                     booking_rules=[fact("booking_contact", "+7 (7172) 91-90-35, +7 (7172) 91-90-36", [ev("gold-museum", "Телефон: +7 (7172) 91-90-35, +7 (7172) 91-90-36")])])

    opera = service("service:astana-opera-theatre-lesson", "Театральный урок в «Астана Опера»", "cultural_activity", "opera",
                    "Театральный урок в театре «Астана Опера»",
                    {"ru": ["Астана Опера экскурсия", "закулисье театра", "театральный урок"],
                     "kk": ["Астана Опера театр сабағы", "театрға экскурсия"], "en": ["Astana Opera backstage tour", "theatre lesson", "opera house tour"]},
                    operator_id="operator:astana-opera", schedule_status="on_request",
                    ticket_offers=[offer("ticket:opera-lesson", "Театральный урок", "Участник организованной группы от 10 человек", 5000,
                                         [ev("opera", "Стоимость: 5000 тг с человека")])],
                    facts=[fact("duration_minutes", ["75", "80"], [ev("opera", "Продолжительность: 1 час 15–20 минут")], unit="minutes"),
                           fact("group_minimum", 10, [ev("opera", "Группа: от 10 человек")]),
                           fact("languages", ["ru"], [ev("opera", "Язык проведения: русский")]),
                           fact("activities", ["Большой зал", "Костюмерные и театральные цеха", "Репетиционные залы", "Закулисье"],
                                [ev("opera", "В программу входят: посещение Большого зала; знакомство с общественными пространствами театра; посещение театральных цехов")])],
                    booking_rules=[fact("advance_booking", True, [ev("opera", "Для организации театрального урока необходимо заранее связаться с театром, согласовать дату и время, а также забронировать места для группы.")]),
                                   fact("suggested_start_times", ["11:00", "15:00"], [ev("opera", "рекомендуемое время начала — 11:00 или 15:00")],
                                        notes="Рекомендованное время по согласованию; не ежедневные отправления и не наличие билетов."),
                                   fact("booking_contact", "+7 7172 709-571; +7 7172 709-622", [ev("opera", "Телефон для связи: +7 7172 709-571 +7 7172 709-622")])])

    notice = "Сообщаем вам, что с 3 августа этноцентр «Тамыр», а именно этническая юрта, переходит на режим работы по предварительной записи. Все программы, включая чайные церемонии, мастер-классы, экскурсии и другие мероприятия, будут проводиться только по предварительному бронированию."
    tamyr_notice = ev("tamyr", notice, {"precision": "year_unspecified", "notes": "3 августа указано без года. Более поздний текст страницы противоречит раннему предложению посещать дегустацию без записи."})
    tamyr_facts = [fact("address", "Парк Ailand, Коргалжынское шоссе 2", [ev("tamyr", "Адрес: парк Ailand, Коргалжынское шоссе 2")]),
                   fact("venue_hours", "11:00–21:00", [ev("tamyr", "Режим работы: с 11:00 до 21:00")], notes="Часы площадки; посещение требуется согласовать."),
                   fact("group_size", ["3", "15"], [ev("tamyr", "Количество мест: от 3 до 15 человек")])]
    tamyr_rules = [fact("booking_contact", "+7 708 024 39 41", [ev("tamyr", "Телефон: +7 708 024 39 41")]),
                   fact("advance_booking", "По предварительной записи согласно позднему объявлению на той же странице; год начала правила не указан.", [tamyr_notice])]
    tea_price = ev("tamyr", "Вариант 2 — Чайная церемония (6000 тг, дети до 8 лет — 5000 тг)")
    tea = service("service:tamyr-tea-ceremony", "Чайная церемония в этноцентре «Тамыр»", "cultural_activity", "tamyr",
                  "Чайная церемония в этноцентре «Тамыр»",
                  {"ru": ["Тамыр", "чай в юрте", "казахский чай", "жент", "талкан", "национальные костюмы"],
                   "kk": ["Тамыр", "шай рәсімі", "киіз үй", "жент"], "en": ["Tamyr tea ceremony", "Kazakh yurt experience", "tea ceremony"]},
                  operator_id="operator:tamyr", schedule_status="on_request",
                  facts=[*deepcopy(tamyr_facts), fact("duration_minutes", 60, [ev("tamyr", "Продолжительность: 1 час. Предварительная бронь обязательна.")], unit="minutes"),
                         fact("activities", ["Три вида национального чая", "Баурсаки и сладости", "Фото в национальных костюмах", "Мастер-класс жент/талкан"],
                              [ev("tamyr", "дегустация 3 видов национального чая; баурсаки и национальные сладости; фотосессия в национальных костюмах; мастер-класс по приготовлению жента/талкана.")])],
                  ticket_offers=[offer("ticket:tamyr-tea-adult", "Чайная церемония", "Обычный участник", 6000, [tea_price]),
                                 offer("ticket:tamyr-tea-child", "Детская чайная церемония", "Ребёнок до 8 лет", 5000, [tea_price], age_max=8, age_max_inclusive=False)],
                  booking_rules=[*deepcopy(tamyr_rules), fact("advance_booking_required", True, [ev("tamyr", "Продолжительность: 1 час. Предварительная бронь обязательна.")])])
    tasting = service("service:tamyr-ethno-tasting", "Этно-дегустация в юрте «Тамыр»", "cultural_activity", "tamyr",
                      "Вариант 1 — Этно-дегустация (3000 тг)",
                      {"ru": ["Тамыр дегустация", "тары-шай", "баурсаки", "национальные сладости"],
                       "kk": ["Тамыр этно-дегустация", "тары шай", "бауырсақ"], "en": ["Tamyr ethno tasting", "Kazakh tea tasting", "yurt tasting"]},
                      operator_id="operator:tamyr", schedule_status="on_request",
                      facts=[*deepcopy(tamyr_facts), fact("duration_minutes", 30, [ev("tamyr", "Продолжительность: 30 минут.")], unit="minutes"),
                             fact("included", ["Тары-шай", "Горячие баурсаки", "Национальные сладости", "Рассказ о чае"],
                                  [ev("tamyr", "В программу входит: тары-шай; горячие баурсаки; дегустация национальных сладостей; рассказ о чае и национальных угощениях.")])],
                      ticket_offers=[offer("ticket:tamyr-tasting", "Этно-дегустация", "Участник", 3000, [ev("tamyr", "Вариант 1 — Этно-дегустация (3000 тг)")])],
                      booking_rules=[*deepcopy(tamyr_rules), fact("advance_booking_conflict", "Раннее описание допускает посещение без записи, позднее объявление требует бронь для всех программ.",
                                                               [ev("tamyr", "Без предварительной регистрации — можно прийти сразу."), tamyr_notice], status="conflicting",
                                                               notes="Рекомендовать предварительно связаться с этноцентром; не обещать вход без записи.")])

    walk_fares = ev("walk-nurzhol", "Стоимость: 7000 тг с человека (взрослый) / 3500 тг (детский от 5 до 14 лет, пенсионеры)")
    walking = service("service:nurzhol-interest-love", "Об Астане: с интересом и любовью — прогулка по Нуржолу", "walking_tour", "walk-nurzhol",
                      "Об Астане: с интересом и любовью",
                      {"ru": ["Нуржол", "Аллея тысячелетий", "Айжан Омиралина", "пешая экскурсия"],
                       "kk": ["Нұржол", "жаяу экскурсия", "Айжан Омиралина"], "en": ["Nurzhol walking tour", "Astana with interest and love", "Aomi Travel"]},
                      operator_id="operator:aomi-travel", schedule_status="on_request",
                      facts=[fact("duration_minutes", 120, [ev("walk-nurzhol", "Продолжительность: 2 часа (12:00–14:00)")], unit="minutes"),
                             fact("group_size", ["5", "15"], [ev("walk-nurzhol", "Группа: от 5 до 15 человек")]),
                             fact("languages", ["ru"], [ev("walk-nurzhol", "Язык проведения: русский")]),
                             fact("route_description", "По бульвару между Хан-Шатыром и резиденцией Ак Орда; точка сбора не опубликована.",
                                  [ev("walk-nurzhol", "Бульвар простираясь от Хан-Шатыра до резиденции Президента «Ак Орды»")])],
                      ticket_offers=[offer("ticket:nurzhol-adult", "Взрослый билет", "Взрослый", 7000, [walk_fares]),
                                     offer("ticket:nurzhol-concession", "Детский/пенсионный билет", "Дети от 5 до 14 лет и пенсионеры", 3500, [walk_fares], age_min=5, age_max=14,
                                           notes="Возрастные границы относятся к детям, не к пенсионерам.")],
                      booking_rules=[fact("suggested_time_window", "12:00–14:00, дата не указана", [ev("walk-nurzhol", "Продолжительность: 2 часа (12:00–14:00)")], notes="Не ежедневное подтверждённое отправление."),
                                     fact("booking_contact", "+7 775 334 56 65; Omiralina.aijan@gmail.com", [ev("walk-nurzhol", "Телефон: +7 775 334 56 65 E-mail: Omiralina.aijan@gmail.com")])])

    operators = [
        {"id": "operator:crocos-travel", "name": "ТОО Crocos Travel / RedBus", "evidence": [ev("redbus-routes", "Товарищество с ограниченной ответственностью «Crocos Travel»")],
         "facts": [fact("phone", "+7 777 555 7575", [ev("redbus-routes", "Узнай больше о RedBus: +7 777 555 7575")]),
                   fact("email", "info@redbus.kz", [ev("redbus-routes", "info@redbus.kz")]),
                   fact("office_address", "БЦ Нұр Тау, Проспект Республики 34а, 602 офис, 6 этаж", [ev("redbus-routes", "БЦ Нұр Тау, Проспект Республики 34а, 602 офис, 6 этаж")],
                        notes="Адрес офиса, не посадки и не туристическая достопримечательность.")]},
        {"id": "operator:dual-kz", "name": "ТОО Dual.KZ", "evidence": [ev("river-parks", "ТОО Dual.KZ, г. Астана")]},
        {"id": "operator:national-museum", "name": "Национальный музей Республики Казахстан", "evidence": [ev("gold-museum", "Национальный музей Республики Казахстан приглашает на экскурсию")]},
        {"id": "operator:astana-opera", "name": "Астана Опера", "evidence": [ev("opera", "Контакты для записи: Астана Опера")]},
        {"id": "operator:tamyr", "name": "Этноцентр «Тамыр»", "evidence": [ev("tamyr", "этноцентр «Тамыр»")]},
        {"id": "operator:aomi-travel", "name": "Омиралина Айжан / Aomi Travel", "evidence": [ev("walk-nurzhol", "Контакты для записи: Омиралина Айжан")]},
    ]
    payload = {"schema_version": 1, "as_of": "2026-10-19", "collected_at": max(source["checked_at"] for source in SOURCES.values()),
               "operators": operators, "services": [redbus, river_parks, river, museum, opera, tea, tasting, walking]}
    addendum_path = ROOT / "data/sources/city_services_addendum_2026-10-19.json"
    if addendum_path.exists():
        addendum = CityServicesCatalog.model_validate(json.loads(addendum_path.read_text()))
        known = {service["id"] for service in payload["services"]}
        payload["services"].extend(service.model_dump(mode="json") for service in addendum.services if service.id not in known)
    return CityServicesCatalog.model_validate(payload)


if __name__ == "__main__":
    catalog = build()
    output = ROOT / "data/sources/city_services_2026-10-19.json"
    output.write_text(json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"as_of": "2026-10-19", "catalog_path": str(output.relative_to(ROOT)),
              "catalog_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "service_code_sha256": hashlib.sha256((ROOT / "data/city_services.py").read_bytes()).hexdigest(),
              "services": len(catalog.services), "operators": len(catalog.operators),
              "ticket_offers": sum(len(service.ticket_offers) for service in catalog.services),
              "dated_departures": sum(len(service.dated_departures) for service in catalog.services),
              "sources_requested": len(SOURCES), "sources_http_200": sum(source.get("status") == 200 for source in SOURCES.values()),
              "source_anomalies_excluded": [{"key": key, "source_url": SOURCES[key]["source_url"], "title": SOURCES[key]["title"],
                                             "reason": "Gambling/SEO content anomaly in title; candidate not accepted as a reliable tour page."}
                                            for key in ["mosque", "murals"]],
              "search_aliases": "Editorial RU/KK/EN retrieval translations, not source-claimed language support.",
              "limitations": ["No exact-date departure evidence; no today's last-departure claim.",
                              "RedBus duration, age, currency and legacy schedule conflict explicitly retained.",
                              "River navigation dates/boarding point not verified. 250 у.е. not converted.",
                              "Museum advertised average spend not turned into ticket fare.",
                              "Tamyr 3-August booking-policy notice omits year; same-page contradiction retained.",
                              "No operator office was converted into an attraction or stop; no ambiguous canonical stop IDs bound."],
              "external_llm_or_embedding_cost_usd": 0}
    (OUT / "services-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"source_anomalies_excluded", "limitations"}}, ensure_ascii=False, indent=2))
