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
    "summary": {"ru": "Подобрал {n} {places} рядом: {names}.", "kk": "Жақын жерден {n} орын таптым: {names}.", "en": "Found {n} {places} nearby: {names}."},
    "summary_none": {"ru": "Рядом не нашлось подходящих мест под эти условия.", "kk": "Осы шарттарға сай жақын орын табылмады.", "en": "No suitable places nearby for these conditions."},
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
    "note_relaxed_radius": {"ru": "Рядом мало вариантов — расширил радиус поиска до {r} км.", "kk": "Жақын маңда нұсқа аз — іздеу радиусын {r} км-ге дейін кеңейттім.", "en": "Few options nearby — widened the search radius to {r} km."},
    "note_relaxed_needs": {"ru": "Не нашёл мест с подтверждённым «{f}» — показываю, где это не указано в данных.", "kk": "«{f}» расталған орын табылмады — деректе көрсетілмеген орындарды ұсынамын.", "en": "No places with confirmed «{f}» — showing places where it is not specified."},
    "note_cold": {"ru": "Ощущается как {t}°C, ветер {w} м/с — отдаю приоритет местам в помещении, на улице не дольше ~{m} мин.", "kk": "{t}°C сияқты сезіледі, жел {w} м/с — жабық орындарға басымдық, далада ~{m} минуттан артық емес.", "en": "Feels like {t}°C, wind {w} m/s — prioritising indoor places, max ~{m} min outdoors."},
    "note_dark": {"ru": "Уже темно — парки без освещения не предлагаю, приоритет у работающих мест в оживлённых районах.", "kk": "Қараңғы — жарықсыз саябақтарды ұсынбаймын, жұмыс істеп тұрған орындарға басымдық.", "en": "It is dark — skipping unlit parks, preferring open venues in busy areas."},
    "note_child_night": {"ru": "После 22:00 подросткам до 18 лет нельзя находиться в развлекательных заведениях без взрослых (ст. 132 КоАП РК).", "kk": "22:00-ден кейін 18 жасқа толмағандарға ойын-сауық орындарында ересектерсіз болуға болмайды (ӘҚБтК 132-бап).", "en": "After 22:00 minors may not stay in entertainment venues without an adult (KZ Administrative Code art. 132)."},
    "note_deadline": {"ru": "Учёл дедлайн: в аэропорту/на вокзале нужно быть не позже {t} (с запасом 30 мин); у каждого места указано, когда выйти.", "kk": "Мерзімді ескердім: әуежайда/вокзалда {t}-ден кешіктірмей болу керек (30 мин қор); әр орында қашан шығу керектігі көрсетілген.", "en": "Deadline respected: be at the airport/station by {t} (30-min buffer); each place shows when to leave."},
    "note_flight_assumption": {"ru": "Считаю, что через {m} мин вам нужно уже быть в аэропорту. Если это время вылета — оставьте ещё ~1,5 ч на регистрацию и сократите прогулку.", "kk": "{m} минуттан кейін әуежайда болуыңыз керек деп есептеймін. Егер бұл ұшу уақыты болса — тіркеуге тағы ~1,5 сағат қалдырыңыз.", "en": "I assume you need to be at the airport in {m} min. If that is the departure time, keep ~1.5 h extra for check-in and shorten the walk."},
    "note_taxi_back": {"ru": "Обратно до аэропорта/вокзала — на такси: время поездки учтено в «выйти до».", "kk": "Әуежайға/вокзалға қайту — таксимен: жол уақыты ескерілді.", "en": "Take a taxi back to the airport/station — the ride is included in the leave-by time."},
    "note_taxi_cold": {"ru": "Слишком холодно и ветрено для прогулки — считаю время в пути на такси.", "kk": "Серуенге тым суық — жол уақытын таксимен есептеймін.", "en": "Too cold and windy to walk — travel times are by taxi."},
    "note_requested_closed": {"ru": "«{what}» поблизости в это время закрыты (отброшено: {n}) — показываю то, что можно посетить сейчас.", "kk": "«{what}» маңайда бұл уақытта жабық ({n}) — қазір баруға болатын орындарды ұсынамын.", "en": "Nearby «{what}» places are closed at this time ({n} skipped) — showing what you can visit now."},
    "route_back": {"ru": " + {m} мин на дорогу обратно", "kk": " + кері жолға {m} мин", "en": " + {m} min to get back"},
    "ask_location": {"ru": "Не удалось определить локацию — нажмите «Моё местоположение» или напишите, возле чего вы находитесь (например, «возле Байтерека»).", "kk": "Орналасуды анықтау мүмкін болмады — «Менің орным» батырмасын басыңыз немесе қай жердің жанында екеніңізді жазыңыз (мысалы, «Бәйтеректің жанында»).", "en": "Could not determine your location — tap “My location” or tell me what you are near (e.g. “near Baiterek”)."},
    "idea_near": {"ru": "Рядом с:", "kk": "Жанында:", "en": "Near:"},
    "note_transit": {"ru": "Время на общественном транспорте оценено приблизительно (без расписаний).", "kk": "Қоғамдық көлікпен уақыт шамамен бағаланды.", "en": "Public transport time is a rough estimate (no timetables)."},
    "note_deadline_tight": {"ru": "До дедлайна слишком мало времени для прогулки — советую остаться рядом с аэропортом/вокзалом.", "kk": "Серуенге уақыт өте аз — әуежай/вокзал маңында қалғаныңыз жөн.", "en": "Too little time before the deadline — better stay near the airport/station."},
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
    "rej_unreachable": {"ru": "не помещается в это время и маршрут", "kk": "бұл уақыт пен бағытқа сыймайды", "en": "does not fit this time and route"},
    "note_target_missing": {"ru": "{name}: {reason}, поэтому показываю, что подходит сейчас.", "kk": "{name}: {reason}, сондықтан қазір лайық орындарды көрсетемін.", "en": "{name}: {reason}, so here is what works right now."},
    "rej_closed": {"ru": "закрыто к моменту прихода", "kk": "барған кезде жабық", "en": "closed by the time you arrive"},
    "rej_far": {"ru": "дорога ~{m} мин — не укладывается во время", "kk": "жол ~{m} мин — уақытқа сыймайды", "en": "~{m} min away — does not fit your time"},
    "rej_kids": {"ru": "не для детей", "kk": "балаларға арналмаған", "en": "not suitable for children"},
    "rej_access": {"ru": "отмечено как недоступное для колясок", "kk": "арбамен кіруге болмайды", "en": "marked as not wheelchair accessible"},
    "rej_dark": {"ru": "неосвещённая открытая территория в тёмное время", "kk": "қараңғыда жарықсыз ашық аумақ", "en": "unlit outdoor area after dark"},
    "rej_cold": {"ru": "на улице — слишком холодно/ветрено сейчас", "kk": "далада — қазір тым суық/желді", "en": "outdoors — too cold/windy right now"},
}

WHAT_TO_DO: dict[str, dict[str, str]] = {
    "museum": {"ru": "Пройдите основную экспозицию и выберите 1–2 зала по интересам; проверьте временные выставки на входе.", "kk": "Негізгі экспозицияны аралап, қызықты 1–2 залды таңдаңыз; уақытша көрмелерді тексеріңіз.", "en": "Walk the main exhibition and pick 1–2 halls you like; ask about temporary exhibitions at the entrance."},
    "gallery": {"ru": "Посмотрите текущую выставку, не спеша, и загляните в лавку/каталог.", "kk": "Ағымдағы көрмені асықпай көріңіз.", "en": "See the current show at a slow pace and browse the shop or catalogue."},
    "theatre": {"ru": "Проверьте афишу на сегодня; если спектакля нет — посмотрите на здание и фойе снаружи.", "kk": "Бүгінгі афишаны тексеріңіз; спектакль болмаса — ғимаратты сырттан тамашалаңыз.", "en": "Check today's programme; if there is no show, admire the building from outside."},
    "cinema": {"ru": "Выберите ближайший сеанс и возьмите билеты заранее онлайн.", "kk": "Жақын сеансты таңдап, билетті онлайн алыңыз.", "en": "Pick the nearest showtime and book tickets online."},
    "arts_centre": {"ru": "Узнайте программу на сегодня — выставка, лекция или мастер-класс.", "kk": "Бүгінгі бағдарламаны біліңіз — көрме, дәріс немесе шеберлік сабағы.", "en": "Check today's programme — exhibition, talk or workshop."},
    "library": {"ru": "Найдите читальный зал, возьмите книгу или поработайте в тишине.", "kk": "Оқу залын тауып, тыныш жерде кітап оқыңыз немесе жұмыс істеңіз.", "en": "Find the reading room and read or work in silence."},
    "landmark": {"ru": "Обойдите вокруг, сделайте фото с лучшего ракурса и прочитайте пару фактов об объекте.", "kk": "Айналып шығып, жақсы ракурстан суретке түсіңіз.", "en": "Walk around it, take photos from the best angle and read a couple of facts about it."},
    "monument": {"ru": "Остановитесь на 5–10 минут: прочитайте табличку и сделайте фото.", "kk": "5–10 минут аялдап, тақтайшаны оқып, суретке түсіңіз.", "en": "Stop for 5–10 minutes: read the plaque and take a photo."},
    "artwork": {"ru": "Найдите арт-объект и сделайте фото — хорошая точка по пути.", "kk": "Арт-нысанды тауып, суретке түсіңіз.", "en": "Find the artwork and snap a photo — a nice stop on the way."},
    "viewpoint": {"ru": "Поднимитесь на смотровую и посмотрите на город — лучше всего на закате.", "kk": "Көру алаңына көтеріліп, қаланы тамашалаңыз.", "en": "Go up and take in the city view — best at sunset."},
    "worship": {"ru": "Посмотрите архитектуру снаружи и внутри; соблюдайте дресс-код и тишину.", "kk": "Сәулетін сырттан және іштен көріңіз; киім үлгісін сақтаңыз.", "en": "See the architecture outside and inside; follow the dress code and keep quiet."},
    "park": {"ru": "Пройдите круг по главной аллее, найдите скамейку у воды или зелени.", "kk": "Негізгі аллеямен айналып серуендеңіз.", "en": "Do a loop along the main alley and find a bench by the water or greenery."},
    "garden": {"ru": "Неспешно пройдитесь и передохните на скамейке.", "kk": "Асықпай серуендеп, орындықта демалыңыз.", "en": "Stroll slowly and rest on a bench."},
    "playground": {"ru": "Дайте ребёнку поиграть 20–40 минут; рядом обычно есть скамейки для взрослых.", "kk": "Балаға 20–40 минут ойнауға мүмкіндік беріңіз.", "en": "Let the kids play for 20–40 minutes; benches for adults are usually nearby."},
    "kids_indoor": {"ru": "Купите билет на 1 час игровой зоны; уточните возрастные ограничения на входе.", "kk": "Ойын аймағына 1 сағаттық билет алыңыз.", "en": "Get a 1-hour ticket for the play zone; check age limits at the entrance."},
    "zoo_aquarium": {"ru": "Пройдите маршрут по залам; проверьте расписание кормлений/шоу.", "kk": "Залдарды аралап, тамақтандыру/шоу кестесін тексеріңіз.", "en": "Follow the route through the halls; check feeding/show times."},
    "water_park": {"ru": "Возьмите купальные принадлежности и закладывайте минимум 1,5–2 часа.", "kk": "Шомылу керек-жарақтарын алып, кемінде 1,5–2 сағат жоспарлаңыз.", "en": "Bring swimwear and plan at least 1.5–2 hours."},
    "theme_park": {"ru": "Выберите 2–3 аттракциона по возрасту и росту.", "kk": "Жасқа сай 2–3 аттракционды таңдаңыз.", "en": "Pick 2–3 rides suitable for age and height."},
    "mall": {"ru": "Тёплая остановка: прогуляйтесь по галереям, загляните на фудкорт или в кино.", "kk": "Жылы аялдама: галереяларды аралап, фудкортқа кіріңіз.", "en": "A warm stop: wander the galleries, grab food at the food court or catch a film."},
    "market": {"ru": "Пройдитесь по рядам, попробуйте местные продукты (курт, баурсаки, сухофрукты).", "kk": "Қатарларды аралап, жергілікті өнімдерден дәм татыңыз.", "en": "Walk the stalls and try local products (kurt, baursaks, dried fruit)."},
    "souvenir": {"ru": "Выберите сувенир или книгу о Казахстане на память.", "kk": "Қазақстан туралы кәдесый немесе кітап таңдаңыз.", "en": "Pick a souvenir or a book about Kazakhstan."},
    "cafe": {"ru": "Возьмите кофе и десерт, займите столик на 20–40 минут.", "kk": "Кофе мен десерт алып, 20–40 минут отырыңыз.", "en": "Grab a coffee and a dessert, sit down for 20–40 minutes."},
    "restaurant": {"ru": "Пообедайте или поужинайте; спросите блюдо дня или местную кухню.", "kk": "Түскі немесе кешкі ас ішіңіз; күннің тағамын сұраңыз.", "en": "Have a meal; ask for the dish of the day or a local speciality."},
    "fast_food": {"ru": "Быстро перекусите и продолжайте прогулку.", "kk": "Тез тамақтанып, серуенді жалғастырыңыз.", "en": "Grab a quick bite and keep going."},
    "sweets": {"ru": "Возьмите выпечку или мороженое с собой — хороший повод для паузы.", "kk": "Тоқаш немесе балмұздақ алыңыз.", "en": "Pick up a pastry or ice cream — a nice pause."},
    "bar": {"ru": "Закажите напиток и посидите 45–60 минут (только 21+).", "kk": "Сусын алып, 45–60 минут отырыңыз (тек 21+).", "en": "Order a drink and stay 45–60 minutes (21+ only)."},
    "nightclub": {"ru": "Проверьте программу вечера и фейс-контроль заранее (21+).", "kk": "Кешкі бағдарламаны алдын ала тексеріңіз (21+).", "en": "Check tonight's line-up and door policy in advance (21+)."},
    "karaoke": {"ru": "Забронируйте кабинку или зал на час.", "kk": "Бір сағатқа кабина брондаңыз.", "en": "Book a room for an hour."},
    "hookah": {"ru": "Посидите в лаунже 1–1,5 часа (21+).", "kk": "Лаунжда 1–1,5 сағат отырыңыз (21+).", "en": "Relax in the lounge for 1–1.5 hours (21+)."},
    "active": {"ru": "Уточните наличие свободных слотов и прокат инвентаря.", "kk": "Бос уақыт пен жабдық жалдауды нақтылаңыз.", "en": "Check free slots and equipment rental."},
    "spa": {"ru": "Заложите 1–2 часа на парную и отдых; уточните сеансы.", "kk": "Моншаға 1–2 сағат жоспарлаңыз.", "en": "Plan 1–2 hours for the sauna and rest; check session times."},
    "coworking": {"ru": "Возьмите дневной пропуск и садитесь работать — розетки и Wi-Fi обычно есть.", "kk": "Күндік рұқсатнама алып, жұмыс істеңіз.", "en": "Get a day pass and settle in to work."},
    "event_venue": {"ru": "Проверьте афишу площадки на сегодня.", "kk": "Бүгінгі афишаны тексеріңіз.", "en": "Check today's programme at the venue."},
}


def t(key: str, lang: str, **kw) -> str:
    s = T[key].get(lang) or T[key]["ru"]
    return s.format(**kw) if kw else s


def weekday(i: int, lang: str) -> str:
    return t("weekdays", lang).split(",")[i]
