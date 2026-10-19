"""User-facing strings in RU / KK / EN (templates are filled by code, never by the LLM)."""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    # opening hours
    "oh_open_until": {"ru": "Открыто до {t}", "kk": "{t} дейін ашық", "en": "Open until {t}"},
    "oh_open": {"ru": "Открыто по данным часов работы", "kk": "Жұмыс кестесі бойынша ашық", "en": "Open according to listed hours"},
    "oh_closing_soon": {"ru": "Закроется в {t} — на месте будет ~{m} мин", "kk": "{t}-де жабылады — шамамен {m} мин бар", "en": "Closes at {t} — about {m} min on site"},
    "oh_closed_until": {"ru": "Сейчас закрыто, откроется {d} в {t}", "kk": "Қазір жабық, {d} {t}-де ашылады", "en": "Closed now, opens {d} at {t}"},
    "oh_closed": {"ru": "В это время закрыто", "kk": "Бұл уақытта жабық", "en": "Closed at this time"},
    "oh_always": {"ru": "Открытая территория — часы не ограничены", "kk": "Ашық аумақ — уақыт шектелмеген", "en": "Open public space — no set hours"},
    "oh_unknown": {"ru": "Часы работы неизвестны — уточните перед визитом", "kk": "Жұмыс уақыты белгісіз — алдын ала нақтылаңыз", "en": "Opening hours unknown — check before going"},
    "oh_unparsed": {"ru": "Часы указаны нестандартно: «{raw}» — уточните", "kk": "Уақыт стандартты емес: «{raw}» — нақтылаңыз", "en": "Hours listed as «{raw}» — please double-check"},
    "oh_source": {"ru": " (источник часов: {source})", "kk": " (жұмыс уақытының дереккөзі: {source})", "en": " (hours source: {source})"},
    "rej_indoor": {"ru": "Нужно место в помещении", "kk": "Жабық орын қажет", "en": "An indoor place is required"},
    "oh_src": {"ru": " (данные OSM)", "kk": " (OSM деректері)", "en": " (OSM data)"},
    "oh_holiday": {"ru": " · сегодня праздник, часы могут отличаться", "kk": " · бүгін мереке, уақыт өзгеруі мүмкін", "en": " · public holiday, hours may differ"},
    "today": {"ru": "сегодня", "kk": "бүгін", "en": "today"},
    "tomorrow": {"ru": "завтра", "kk": "ертең", "en": "tomorrow"},
    # sources
    "src_poi": {"ru": "Данные POI", "kk": "POI деректері", "en": "POI data"},
    "src_generated": {"ru": "Идея ИИ", "kk": "ЖИ идеясы", "en": "AI idea"},
    # travel
    "walk": {"ru": "пешком", "kk": "жаяу", "en": "on foot"},
    "car": {"ru": "на машине", "kk": "көлікпен", "en": "by car"},
    # summary / notes
    "home_label": {"ru": "Дом", "kk": "Үй", "en": "Home"},
    "note_home_missing": {"ru": "Адрес дома ещё не сохранён — выберите «🏠 Дом» в списке мест или напишите, где вы.", "kk": "Үй мекенжайы әлі сақталмаған — тізімнен «🏠 Үй» таңдаңыз немесе қайда екеніңізді жазыңыз.", "en": "Your home is not saved yet — pick «🏠 Home» in the place list or say where you are."},
    "summary_nav": {"ru": "Маршрут от «{a}» до «{b}»: {d}, около {m} мин {how}.", "kk": "«{a}» — «{b}» бағыты: {d}, шамамен {m} мин {how}.", "en": "Route from “{a}” to “{b}”: {d}, about {m} min {how}."},
    "how_walk": {"ru": "пешком", "kk": "жаяу", "en": "on foot"},
    "how_car": {"ru": "на машине", "kk": "көлікпен", "en": "by car"},
    "summary": {"ru": "Подобрал {n} {places} рядом: {names}.", "kk": "Жақын жерден {n} орын таптым: {names}.", "en": "Found {n} {places} nearby: {names}."},
    "summary_none": {"ru": "Рядом не нашлось подходящих мест под эти условия.", "kk": "Осы шарттарға сай жақын орын табылмады.", "en": "No suitable places nearby for these conditions."},
    "summary_food_unverified": {"ru": "В данных нет подтверждения подходящего блюда, формата питания или цены под ваши условия. Могу подобрать места без этих ограничений — напишите «просто где поесть рядом».", "kk": "Сұраған тағам, тамақтану түрі не баға деректермен расталмаған. Шарттарсыз іздеу үшін «жақын жерде қайда тамақтануға болады» деп жазыңыз.", "en": "The data does not confirm the requested dish, meal format or budget. To relax these requirements, ask “just somewhere to eat nearby”."},
    "rej_food_evidence": {"ru": "нет подтверждения нужного блюда, формата или цены", "kk": "қажетті тағам, тамақтану түрі не баға расталмаған", "en": "requested dish, meal format or price is not confirmed"},
    "place_1": {"ru": "место", "kk": "орын", "en": "place"},
    "place_2": {"ru": "места", "kk": "орын", "en": "places"},
    "disclaimer": {
        "ru": "Ответ сформирован ИИ на основе открытых данных (OpenStreetMap, Wikidata/Wikipedia и др.). Часы работы и доступность могут измениться — проверяйте перед визитом.",
        "kk": "Жауапты ЖИ ашық деректер негізінде құрастырды (OpenStreetMap, Wikidata/Wikipedia және т.б.). Жұмыс уақыты өзгеруі мүмкін — барар алдында тексеріңіз.",
        "en": "AI-generated from open data (OpenStreetMap, Wikidata/Wikipedia, etc.). Hours and accessibility may change — please verify before visiting.",
    },
    "privacy": {
        "ru": "Локация округлена до ~100 м, используется только для этого запроса и не сохраняется. В языковую модель координаты не передаются.",
        "kk": "Орналасу ~100 м-ге дейін дөңгелектенген, тек осы сұрауға қолданылады және сақталмайды. Координаттар тілдік модельге жіберілмейді.",
        "en": "Location is rounded to ~100 m, used only for this request and not stored. Coordinates are never sent to the language model.",
    },
    "note_template": {"ru": "Языковая модель недоступна — показаны лучшие места по расчёту, тексты собраны из данных.", "kk": "Тілдік модель қолжетімсіз — есептеу бойынша үздік орындар көрсетілді.", "en": "Language model unavailable — showing top-ranked places with data-based texts."},
    "note_food_soft": {"ru": "Меню и цены в открытых данных почти не опубликованы, поэтому блюдо или бюджет не подтверждены — показываю ближайшие подходящие по типу места. Уточните меню перед визитом.", "kk": "Мәзір мен баға ашық деректерде сирек жарияланады, сондықтан тағам не бюджет расталмаған — түрі бойынша жақын жерлерді көрсетемін. Барар алдында мәзірді тексеріңіз.", "en": "Menus and prices are rarely published in open data, so the dish or budget is not confirmed — showing the closest places of the right kind. Check the menu before going."},
    "note_relaxed_radius": {"ru": "Рядом мало вариантов — расширил радиус поиска до {r} км.", "kk": "Жақын маңда нұсқа аз — іздеу радиусын {r} км-ге дейін кеңейттім.", "en": "Few options nearby — widened the search radius to {r} km."},
    "note_relaxed_needs": {"ru": "Не нашёл мест с подтверждённым «{f}» — показываю, где это не указано в данных.", "kk": "«{f}» расталған орын табылмады — деректе көрсетілмеген орындарды ұсынамын.", "en": "No places with confirmed «{f}» — showing places where it is not specified."},
    "note_cold": {"ru": "Ощущается как {t}°C, ветер {w} м/с — отдаю приоритет местам в помещении, на улице не дольше ~{m} мин.", "kk": "{t}°C сияқты сезіледі, жел {w} м/с — жабық орындарға басымдық, далада ~{m} минуттан артық емес.", "en": "Feels like {t}°C, wind {w} m/s — prioritising indoor places, max ~{m} min outdoors."},
    "note_air": {"ru": "Воздух сейчас загрязнён (индекс AQI {a}, PM2.5 {p} мкг/м³ по данным CAMS) — сокращаю время на улице и чаще предлагаю места в помещении.", "kk": "Қазір ауа ластанған (AQI {a}, PM2.5 {p} мкг/м³, CAMS) — далада аз уақыт, жабық орындарға басымдық.", "en": "The air is polluted right now (AQI {a}, PM2.5 {p} µg/m³, CAMS) — shorter time outdoors, more indoor places."},
    "note_cold_0": {"ru": "Ощущается как {t}°C, ветер {w} м/с — предлагаю только места в помещении.", "kk": "{t}°C сияқты сезіледі, жел {w} м/с — тек жабық орындарды ұсынамын.", "en": "Feels like {t}°C, wind {w} m/s — suggesting indoor places only."},
    "note_dark": {"ru": "Уже темно — парки без освещения не предлагаю, приоритет у работающих мест в оживлённых районах.", "kk": "Қараңғы — жарықсыз саябақтарды ұсынбаймын, жұмыс істеп тұрған орындарға басымдық.", "en": "It is dark — skipping unlit parks, preferring open venues in busy areas."},
    "note_child_night": {"ru": "После 22:00 подросткам до 18 лет нельзя находиться в развлекательных заведениях без взрослых (ст. 132 КоАП РК).", "kk": "22:00-ден кейін 18 жасқа толмағандарға ойын-сауық орындарында ересектерсіз болуға болмайды (ӘҚБтК 132-бап).", "en": "After 22:00 minors may not stay in entertainment venues without an adult (KZ Administrative Code art. 132)."},
    "note_deadline": {"ru": "Учёл дедлайн: прибыть нужно не позже {t}; запас {m} мин, дорога считается отдельно.", "kk": "Мерзім: {t}-ден кешікпей келу керек; қор {m} мин, жол бөлек есептеледі.", "en": "Arrive by {t}; reserved buffer {m} min, with travel calculated separately."},
    "note_flight_free_time": {"ru": "Считаю это время свободным до выезда в аэропорт: дорогу на такси уже учёл в «выйти до». Если это время до самого вылета, лучше ехать сразу — на регистрацию нужно 2–3 часа.", "kk": "Бұл уақытты әуежайға шыққанға дейінгі бос уақыт деп есептедім: таксимен жолды «шығу уақытына» қостым. Егер бұл ұшуға дейінгі уақыт болса, бірден барған дұрыс — тіркеуге 2–3 сағат керек.", "en": "I treat this as free time before you leave for the airport; the taxi ride is already in the 'leave by' time. If it is the time until departure itself, better head out now: check-in needs 2–3 hours."},
    "note_flight_assumption": {"ru": "До вылета оставляю {m} мин на регистрацию и контроль (тип рейса: {kind}); дорога и запас на неё отдельно. Если тип рейса не указан, уточните его.", "kk": "Ұшуға дейін тіркеу мен бақылауға {m} мин қалдырамын (рейс түрі: {kind}); жол мен оның қоры бөлек. Түрі белгісіз болса, нақтылаңыз.", "en": "Reserved {m} min before departure for check-in and security (flight type: {kind}); travel and road uncertainty are separate. Please clarify the flight type if unknown."},
    "note_taxi_back": {"ru": "Обратно до аэропорта/вокзала — на такси: время поездки учтено в «выйти до».", "kk": "Әуежайға/вокзалға қайту — таксимен: жол уақыты ескерілді.", "en": "Take a taxi back to the airport/station — the ride is included in the leave-by time."},
    "note_taxi_cold": {"ru": "Слишком холодно и ветрено для прогулки — считаю время в пути на такси.", "kk": "Серуенге тым суық — жол уақытын таксимен есептеймін.", "en": "Too cold and windy to walk — travel times are by taxi."},
    "note_requested_closed": {"ru": "«{what}» поблизости в это время закрыты — показываю то, что можно посетить сейчас.", "kk": "«{what}» маңайда бұл уақытта жабық — қазір баруға болатын орындарды ұсынамын.", "en": "Nearby «{what}» places are closed at this time — showing what you can visit now."},
    "route_back": {"ru": " + {m} мин на дорогу обратно", "kk": " + кері жолға {m} мин", "en": " + {m} min to get back"},
    "ask_location": {"ru": "Не удалось определить локацию — нажмите «Моё местоположение» или напишите, возле чего вы находитесь (например, «возле Байтерека»).", "kk": "Орналасуды анықтау мүмкін болмады — «Менің орным» батырмасын басыңыз немесе қай жердің жанында екеніңізді жазыңыз (мысалы, «Бәйтеректің жанында»).", "en": "Could not determine your location — tap “My location” or tell me what you are near (e.g. “near Baiterek”)."},
    "idea_near": {"ru": "Рядом с:", "kk": "Жанында:", "en": "Near:"},
    "off_topic": {"ru": "Я Серу и помогаю только с местами и прогулками по Астане. Напишите, где вы и чего хочется: кофе, прогулка, музей, место для детей.",
                  "kk": "Мен Серумін, тек Астанадағы орындар мен серуендерге көмектесемін. Қай жердесіз және не қалайсыз, жазыңыз: кофе, серуен, мұражай, балаларға арналған орын.",
                  "en": "I'm Seru and I only help with places and walks in Astana. Tell me where you are and what you'd like: coffee, a walk, a museum, somewhere for kids."},
    "photo_recognized": {"ru": "Похоже, на фото «{name}» — подбираю места рядом. Если это не так, напишите ориентир.",
                         "kk": "Суретте «{name}» сияқты — жақын орындарды іріктеймін. Олай болмаса, бағдарды жазыңыз.",
                         "en": "This looks like «{name}» — here are places nearby. If not, type a landmark."},
    "photo_unrecognized": {"ru": "Не удалось уверенно узнать место на фото. Напишите ориентир (например, «возле Байтерека») или нажмите «Моё местоположение».",
                           "kk": "Суреттегі орынды нақты тану мүмкін болмады. Бағдарды жазыңыз (мысалы, «Бәйтеректің жанында») немесе «Менің орным» батырмасын басыңыз.",
                           "en": "I couldn't recognise the place in the photo. Type a landmark (e.g. “near Baiterek”) or tap “My location”."},
    "photo_fallback": {"ru": "Место на фото не узнал — считаю от выбранного ориентира.", "kk": "Суреттегі орынды танымадым — таңдалған бағдардан есептеймін.",
                       "en": "Couldn't recognise the photo — using the landmark you selected."},
    "photo_privacy": {"ru": "Фото уменьшено, метаданные (включая GPS из EXIF) удалены до отправки в ИИ; фото не сохраняется.",
                      "kk": "Сурет кішірейтілді, метадеректер (EXIF ішіндегі GPS та) ЖИ-ге жіберер алдында өшірілді; сурет сақталмайды.",
                      "en": "The photo was downscaled and its metadata (including EXIF GPS) removed before it reached the AI; it is not stored."},
    "note_transit": {"ru": "Время на общественном транспорте оценено приблизительно (без расписаний).", "kk": "Қоғамдық көлікпен уақыт шамамен бағаланды.", "en": "Public transport time is a rough estimate (no timetables)."},
    "note_deadline_tight": {"ru": "Для прогулки времени недостаточно — отправляйтесь в аэропорт/на вокзал сейчас.", "kk": "Серуенге уақыт жеткіліксіз — әуежайға/вокзалға қазір барыңыз.", "en": "Too little time for a walk — head to the airport/station now."},
    "note_holiday": {"ru": "Сегодня праздник ({h}) — часы работы могут отличаться.", "kk": "Бүгін мереке ({h}) — жұмыс уақыты өзгеше болуы мүмкін.", "en": "Public holiday today ({h}) — opening hours may differ."},
    "note_outside_graph": {"ru": "Время в пути оценено по прямой с поправкой на город (точный пешеходный граф для этой зоны не построен).", "kk": "Жол уақыты түзу сызық бойынша бағаланды.", "en": "Travel time estimated from straight-line distance with a city detour factor."},
    "note_location_default": {"ru": "Локация не указана — считаю от центра (Байтерек). Нажмите «Моё местоположение» или выберите ориентир.", "kk": "Орналасу көрсетілмеген — орталықтан (Бәйтерек) есептеймін.", "en": "No location given — using the city centre (Baiterek). Share your location or pick a landmark."},
    "note_outside_city": {"ru": "Координаты вне Астаны — напиши ориентир в городе (например, «возле Байтерека»).", "kk": "Координаттар Астанадан тыс — қаладағы бағдарды жаз (мысалы, «Бәйтеректің жанында»).", "en": "Your coordinates are outside Astana — tell me a landmark in the city (e.g. “near Baiterek”)."},
    "note_pii": {"ru": "Личные данные из запроса (телефон, email, номера) скрыты и не отправлялись в ИИ.", "kk": "Сұраудағы жеке деректер (телефон, email, нөмірлер) жасырылды және ЖИ-ге жіберілмеді.", "en": "Personal data in your request (phone, email, numbers) was hidden and not sent to the AI."},
    "note_injection": {"ru": "Часть запроса похожа на попытку изменить инструкции — её я пропустил.", "kk": "Сұраудың бір бөлігі нұсқауларды өзгертуге ұқсайды — оны өткізіп жібердім.", "en": "Part of the request looked like an attempt to change my instructions — I skipped it."},
    "note_power": {"ru": "Розетки в открытых данных почти не отмечены: наличие розеток стоит уточнить на месте.", "kk": "Розеткалар ашық деректерде сирек белгіленеді — орнында нақтылаңыз.", "en": "Power outlets are rarely mapped in open data — please check on site."},
    "note_quiet": {"ru": "«Тихое место» — оценка по типу заведения (библиотека, кофейня, сквер), шум в данных не измеряется.", "kk": "«Тыныш орын» — орын түріне қарай бағаланады.", "en": "“Quiet” is inferred from the place type; noise is not measured in the data."},
    "note_event_source": {"ru": "События — по данным Ticketon/Sxodim на момент сбора; проверьте наличие билетов.", "kk": "Іс-шаралар — Ticketon/Sxodim деректері бойынша; билеттерді тексеріңіз.", "en": "Events are from Ticketon/Sxodim at collection time; check ticket availability."},
    "route_summary": {"ru": "Мини-маршрут: {stops}. Всего ≈ {total} мин ({travel} мин в пути + {visit} мин на местах{back}).", "kk": "Шағын маршрут: {stops}. Барлығы ≈ {total} мин ({travel} мин жолда + {visit} мин орындарда{back}).", "en": "Mini-route: {stops}. Total ≈ {total} min ({travel} min travelling + {visit} min at places{back})."},
    "route_return": {"ru": " С возвращением к старту.", "kk": " Бастапқы нүктеге оралумен.", "en": " Returning to start."},
    # weather
    "wx": {"ru": "{t}°C (ощущается {f}°C), ветер {w} м/с", "kk": "{t}°C ({f}°C сезіледі), жел {w} м/с", "en": "{t}°C (feels {f}°C), wind {w} m/s"},
    "wx_precip": {"ru": ", осадки", "kk": ", жауын-шашын", "en": ", precipitation"},
    # weekdays
    "weekdays": {"ru": "понедельник,вторник,среда,четверг,пятница,суббота,воскресенье",
                 "kk": "дүйсенбі,сейсенбі,сәрсенбі,бейсенбі,жұма,сенбі,жексенбі",
                 "en": "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"},
    # considered reasons
    "desc_cuisine": {"ru": "Кухня: {v}", "kk": "Ас мәзірі: {v}", "en": "Cuisine: {v}"},
    "desc_features": {"ru": "Удобства: {v}", "kk": "Ыңғайлылықтар: {v}", "en": "Amenities: {v}"},
    "desc_near": {"ru": "Рядом с «{name}»", "kk": "«{name}» жанында", "en": "Next to {name}"},
    "desc_near_m": {"ru": "В {m} м от «{name}»", "kk": "«{name}» нысанынан {m} м жерде", "en": "{m} m from {name}"},
    "desc_address": {"ru": "Адрес: {v}", "kk": "Мекенжайы: {v}", "en": "Address: {v}"},
    "note_text_origin": {"ru": "Считаю от «{name}», как ты написал (а не от геолокации).", "kk": "Сен жазғандай «{name}» нысанынан есептеймін (геолокациядан емес).", "en": "Counting from «{name}» as you wrote (not from your location)."},
    "rej_unreachable": {"ru": "не помещается в это время и маршрут", "kk": "бұл уақыт пен бағытқа сыймайды", "en": "does not fit this time and route"},
    "note_far_walk": {"ru": "Пешком это около {m} мин — удобнее на такси или автобусе.", "kk": "Жаяу шамамен {m} мин — такси не автобуспен ыңғайлырақ.", "en": "That is about {m} min on foot — a taxi or bus is easier."},
    "note_target_missing": {"ru": "{name}: {reason}, поэтому показываю, что подходит сейчас.", "kk": "{name}: {reason}, сондықтан қазір лайық орындарды көрсетемін.", "en": "{name}: {reason}, so here is what works right now."},
    "rej_closed": {"ru": "закрыто к моменту прихода", "kk": "барған кезде жабық", "en": "closed by the time you arrive"},
    "rej_far": {"ru": "дорога ~{m} мин — не укладывается во время", "kk": "жол ~{m} мин — уақытқа сыймайды", "en": "~{m} min away — does not fit your time"},
    "rej_kids": {"ru": "не для детей", "kk": "балаларға арналмаған", "en": "not suitable for children"},
    "rej_access": {"ru": "отмечено как недоступное для колясок", "kk": "арбамен кіруге болмайды", "en": "marked as not wheelchair accessible"},
    "rej_dark": {"ru": "неосвещённая открытая территория в тёмное время", "kk": "қараңғыда жарықсыз ашық аумақ", "en": "unlit outdoor area after dark"},
    "rej_cold": {"ru": "на улице — слишком холодно/ветрено сейчас", "kk": "далада — қазір тым суық/желді", "en": "outdoors — too cold/windy right now"},
}

WHAT_TO_DO: dict[str, dict[str, str]] = {
    "museum": {
        "ru": "Посмотрите экспозицию по своим интересам.",
        "kk": "Қызығушылығыңызға сай экспозицияны тамашалаңыз.",
        "en": "Explore the exhibition at your own pace."
    },
    "gallery": {
        "ru": "Рассмотрите работы, которые вас заинтересуют.",
        "kk": "Қызықтырған туындыларды тамашалаңыз.",
        "en": "Take a closer look at the works that interest you."
    },
    "theatre": {
        "ru": "Уточните афишу и выберите представление.",
        "kk": "Афишаны нақтылап, қойылым таңдаңыз.",
        "en": "Check the programme and choose a performance."
    },
    "cinema": {
        "ru": "Уточните расписание и выберите фильм.",
        "kk": "Кестені нақтылап, фильм таңдаңыз.",
        "en": "Check the schedule and choose a film."
    },
    "arts_centre": {
        "ru": "Уточните программу и выберите занятие по интересам.",
        "kk": "Бағдарламаны нақтылап, қызығушылығыңызға сай іс-шара таңдаңыз.",
        "en": "Check the programme and choose an activity that interests you."
    },
    "library": {
        "ru": "Уточните условия посещения и почитайте.",
        "kk": "Келу шарттарын нақтылап, кітап оқыңыз.",
        "en": "Check the visiting conditions and spend some time reading."
    },
    "landmark": {
        "ru": "Осмотрите место и выберите ракурс для фотографии.",
        "kk": "Орынды тамашалап, суретке түсетін ракурс таңдаңыз.",
        "en": "Look around and choose an angle for a photo."
    },
    "monument": {
        "ru": "Рассмотрите памятник и сделайте фотографию.",
        "kk": "Ескерткішті тамашалап, суретке түсіріңіз.",
        "en": "Take a closer look at the monument and take a photo."
    },
    "artwork": {
        "ru": "Рассмотрите арт-объект и опишите свои впечатления.",
        "kk": "Арт-нысанды тамашалап, әсеріңізді сипаттаңыз.",
        "en": "Look at the artwork and describe your impressions."
    },
    "viewpoint": {
        "ru": "Посмотрите на город и найдите интересный ракурс.",
        "kk": "Қаланы тамашалап, қызықты ракурс табыңыз.",
        "en": "Take in the city view and find an interesting angle."
    },
    "worship": {
        "ru": "Осмотрите архитектуру и соблюдайте местные правила посещения.",
        "kk": "Сәулетін тамашалап, жергілікті келу ережелерін сақтаңыз.",
        "en": "Admire the architecture and follow the local visiting rules."
    },
    "park": {
        "ru": "Прогуляйтесь по парку в удобном для вас темпе.",
        "kk": "Саябақта өзіңізге ыңғайлы қарқынмен серуендеңіз.",
        "en": "Walk around the park at your own pace."
    },
    "garden": {
        "ru": "Неспешно прогуляйтесь и понаблюдайте за окружением.",
        "kk": "Асықпай серуендеп, айналаңызды бақылаңыз.",
        "en": "Take a stroll and observe your surroundings."
    },
    "playground": {
        "ru": "Предложите ребёнку поиграть, учитывая условия на месте.",
        "kk": "Жергілікті жағдайды ескеріп, балаға ойнауды ұсыныңыз.",
        "en": "Invite the children to play, following the conditions on site."
    },
    "kids_indoor": {
        "ru": "Уточните условия посещения и предложите ребёнку поиграть.",
        "kk": "Келу шарттарын нақтылап, балаға ойнауды ұсыныңыз.",
        "en": "Check the visiting conditions and invite the children to play."
    },
    "zoo_aquarium": {
        "ru": "Понаблюдайте за животными и узнайте больше о них.",
        "kk": "Жануарларды бақылап, олар туралы көбірек біліңіз.",
        "en": "Observe the animals and learn more about them."
    },
    "water_park": {
        "ru": "Уточните условия посещения и выберите водное развлечение.",
        "kk": "Келу шарттарын нақтылап, судағы ойын-сауықты таңдаңыз.",
        "en": "Check the visiting conditions and choose a water activity."
    },
    "theme_park": {
        "ru": "Уточните условия и выберите развлечение по интересам.",
        "kk": "Шарттарды нақтылап, қызығушылығыңызға сай ойын-сауық таңдаңыз.",
        "en": "Check the conditions and choose an activity you enjoy."
    },
    "mall": {
        "ru": "Прогуляйтесь по торговому центру и осмотрите магазины.",
        "kk": "Сауда орталығында серуендеп, дүкендерді аралаңыз.",
        "en": "Walk around the shopping centre and browse the shops."
    },
    "market": {
        "ru": "Пройдитесь по рынку и посмотрите, что предлагают продавцы.",
        "kk": "Базарды аралап, сатушылардың ұсыныстарын қараңыз.",
        "en": "Explore the market and see what the sellers offer."
    },
    "souvenir": {
        "ru": "Присмотрите сувенир на память.",
        "kk": "Естелікке кәдесый таңдаңыз.",
        "en": "Look for a souvenir to remember your visit."
    },
    "cafe": {
        "ru": "Зайдите на кофе или перекус.",
        "kk": "Кофе ішуге немесе тіскебасарға кіріңіз.",
        "en": "Stop by for a coffee or a snack."
    },
    "restaurant": {
        "ru": "Зайдите поесть и выберите что-нибудь по вкусу.",
        "kk": "Тамақтануға кіріп, талғамыңызға сай ас таңдаңыз.",
        "en": "Stop for a meal and choose something you like."
    },
    "fast_food": {
        "ru": "Перекусите перед продолжением прогулки.",
        "kk": "Серуенді жалғастырмас бұрын тіскебасар алыңыз.",
        "en": "Grab a bite before continuing your walk."
    },
    "sweets": {
        "ru": "Загляните за чем-нибудь сладким.",
        "kk": "Тәтті бірдеңе алуға кіріңіз.",
        "en": "Stop by for something sweet."
    },
    "bar": {
        "ru": "Уточните условия посещения и выберите напиток.",
        "kk": "Келу шарттарын нақтылап, сусын таңдаңыз.",
        "en": "Check the visiting conditions and choose a drink."
    },
    "nightclub": {
        "ru": "Уточните программу и условия посещения.",
        "kk": "Бағдарлама мен келу шарттарын нақтылаңыз.",
        "en": "Check the programme and visiting conditions."
    },
    "karaoke": {
        "ru": "Уточните условия и выберите песню.",
        "kk": "Шарттарды нақтылап, ән таңдаңыз.",
        "en": "Check the conditions and choose a song."
    },
    "hookah": {
        "ru": "Уточните условия посещения и выберите формат отдыха.",
        "kk": "Келу шарттарын нақтылап, демалыс түрін таңдаңыз.",
        "en": "Check the visiting conditions and choose how to relax."
    },
    "active": {
        "ru": "Уточните доступные занятия и выберите подходящее.",
        "kk": "Қолжетімді жаттығуларды нақтылап, лайықтысын таңдаңыз.",
        "en": "Ask which activities are available and choose one that suits you."
    },
    "spa": {
        "ru": "Уточните доступные процедуры и выберите подходящую.",
        "kk": "Қолжетімді рәсімдерді нақтылап, лайықтысын таңдаңыз.",
        "en": "Ask which treatments are available and choose one that suits you."
    },
    "coworking": {
        "ru": "Уточните условия посещения и поработайте.",
        "kk": "Келу шарттарын нақтылап, жұмыс істеңіз.",
        "en": "Check the visiting conditions and get some work done."
    },
    "event_venue": {
        "ru": "Уточните актуальную афишу и выберите событие по интересам.",
        "kk": "Ағымдағы афишаны нақтылап, қызығушылығыңызға сай іс-шара таңдаңыз.",
        "en": "Check the current programme and choose an event that interests you."
    }
}


def t(key: str, lang: str, **kw) -> str:
    s = T[key].get(lang) or T[key]["ru"]
    return s.format(**kw) if kw else s


def weekday(i: int, lang: str) -> str:
    return t("weekdays", lang).split(",")[i]
