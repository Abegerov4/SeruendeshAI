"""Deterministic, source-attributed answers for published city services."""
from __future__ import annotations

from copy import deepcopy
import datetime as dt
import re

from ayat_backend.app.textnorm import fold


def _key(value):
    return re.sub(r"[^a-zа-я0-9]", "", fold(value))


def select_services(query: str, services: list[dict], prior_id: str | None = None) -> list[dict]:
    text, key = fold(query), _key(query)
    if re.search(r"поесть|покушать|пюре|котлет|coffee|кофе|тамак", text) and not re.search(r"билет|рейс|посадк|ticket|depart", text):
        return []
    generic_place_aliases = {_key(value) for value in ("Ишим","Есиль","Есіл","Нуржол","Нұржол",
        "Национальный музей","Ұлттық музей","Аллея тысячелетий","Золотой человек","Алтын адам","киіз үй")}
    tour_intent = bool(re.search(r"экскурси|сити.?тур|гид|тур\b|круиз|катер|теплоход|лодк|корабл|на\s+воде|tour|cruise|boat|кеме|катермен",text))
    explicit = [s for s in services if any(len(_key(alias)) >= 4 and _key(alias) in key
                and (_key(alias) not in generic_place_aliases or tour_intent)
                for alias in [s["name"], *sum(s.get("aliases",{}).values(), [])])]
    if explicit:
        return explicit[:3]
    new_topic = bool(re.search(r"кино|музе[йяею]|парк|кофейн|ресторан|cinema|movie|museum|park|restaurant|мұражай|саябақ",text))
    if prior_id and not new_topic and len(query) <= 180 and re.search(r"последн|во сколько|сколько|цен|стоит|билет|посадк|где сесть|ребен|ребен|маршрут|last|when|how much|board|ticket|багасы|канша|кайда", text):
        return [s for s in services if s["id"] == prior_id][:1]
    if re.search(r"экскурси\w*.*автобус|автобус\w*.*экскурси|bus tour", text):
        return [s for s in services if s["kind"] == "bus_tour"][:3]
    if re.search(r"экскурси|guided tour|city tour",text):
        return services[:3]
    return []


def _validity_ok(valid: dict, day: dt.date) -> bool:
    if valid.get("valid_from") and day < dt.date.fromisoformat(valid["valid_from"]):
        return False
    if valid.get("valid_to") and day > dt.date.fromisoformat(valid["valid_to"]):
        return False
    if valid.get("months") and day.month not in valid["months"]:
        return False
    # A named-day/yearless schedule is not made current by a recent fetch.
    if valid.get("precision") == "year_unspecified":
        return False
    return True


def _valid(item: dict, day: dt.date, max_age=90, *, observed_day: dt.date | None = None) -> bool:
    if item.get("status", "confirmed") != "confirmed" or not _validity_ok(item.get("validity") or {}, day):
        return False
    observed_day = observed_day or day
    for evidence in item.get("evidence",[]):
        checked = dt.datetime.fromisoformat(evidence["checked_at"].replace("Z","+00:00")).astimezone(dt.timezone(dt.timedelta(hours=5))).date()
        if _validity_ok(evidence.get("validity") or {}, day) and 0 <= (observed_day-checked).days <= max_age:
            return True
    return False


def _say(lang, ru, kk, en):
    return {"ru":ru,"kk":kk,"en":en}.get(lang,ru)


def answer_services(selected: list[dict], query: str, now: dt.datetime, lang: str) -> tuple[list[dict], str, list[str]]:
    day, text = now.date(), fold(query)
    results, summaries, notes = [], [], []
    time_intent = bool(re.search(r"последн|во сколько|следующ|сегодня|завтра|расписан|когда|last|depart|when|schedule|кашан", text))
    boarding_intent = bool(re.search(r"посадк|где сесть|откуда|board|where.*(?:start|get on)|кайда",text))
    price_intent = bool(re.search(r"цен|стоим|стоит|сколько|билет|price|cost|ticket|канша|багасы",text))
    route_intent = bool(re.search(r"маршрут|route|бағыт",text))
    if re.search(r"завтра|tomorrow|ертен",text):
        day += dt.timedelta(days=1)
    for service in selected:
        result = deepcopy(service)
        result["facts"] = [f for f in result.get("facts",[]) if _valid(f,day,observed_day=now.date())]
        result["booking_rules"] = [f for f in result.get("booking_rules",[]) if _valid(f,day,observed_day=now.date())]
        result["ticket_offers"] = [o for o in result.get("ticket_offers",[]) if _valid(o,day,30,observed_day=now.date())]
        result["routes"] = [route for route in result.get("routes",[]) if _valid(route,day,observed_day=now.date())]
        for route in result["routes"]:
            route["stops"] = [stop for stop in route["stops"] if _valid(stop,day,observed_day=now.date())]
        boarding_ids = {stop["id"] for route in result["routes"] for stop in route["stops"] if stop["role"] == "boarding"}
        result["departures_today"] = [d for d in result.get("dated_departures",[]) if d["date"] == day.isoformat()
            and d["boarding_stop_id"] in boarding_ids and _valid(d,day,30,observed_day=now.date())]
        # Old timetables and conflicts remain in the evidence archive, not in a
        # list that the UI could mistake for current departures or confirmed facts.
        result["dated_departures"] = result["departures_today"]
        warnings = []
        if not result["departures_today"]:
            warnings.append(_say(lang, f"Расписание на {day.isoformat()} не подтверждено; время последнего рейса неизвестно.",
                f"{day.isoformat()} күнінің кестесі расталмаған; соңғы рейс уақыты белгісіз.",
                f"The schedule for {day.isoformat()} is not confirmed; the last departure is unknown."))
        conflicts = [f for f in service.get("facts",[])+service.get("booking_rules",[]) if f.get("status") == "conflicting"]
        if conflicts:
            warnings.append(_say(lang,"В источниках есть расхождения в условиях услуги; спорные сведения не подтверждены.",
                "Дереккөздердегі қызмет шарттары қайшы; даулы мәліметтер расталмаған.",
                "Sources disagree about some service conditions; disputed details are unconfirmed."))
        result["notes"] = warnings
        notes.extend(warnings)
        stops = {stop["id"]:stop for route in result.get("routes",[]) for stop in route.get("stops",[]) if stop["role"] == "boarding"}
        heading = result["name"] + ". "
        if time_intent:
            summary = heading + ("; ".join(d["time"][:5] for d in result["departures_today"]) if result["departures_today"] else warnings[0])
        elif boarding_intent:
            summary = heading + (_say(lang,"Посадка: ","Отыру орны: ","Boarding: ") + "; ".join(s["name"] for s in stops.values()) if stops else
                _say(lang,"Точная точка сбора не подтверждена; уточните у организатора.","Нақты жиналу орны расталмаған; ұйымдастырушыдан нақтылаңыз.","The exact meeting point is unconfirmed; ask the organizer."))
        elif route_intent:
            roles = {"boarding":_say(lang,"посадка","отыру","boarding"),
                     "visit":_say(lang,"посещение","бару","visit"),
                     "pass_by":_say(lang,"проезд мимо","жанынан өту","pass by")}
            routes = [r["name"] + ": " + " → ".join(f"{s['name']} ({roles[s['role']]})" for s in r["stops"])
                      for r in result["routes"] if r["stops"]]
            summary = heading + ("; ".join(routes) if routes else _say(lang,"Маршрут не подтверждён.","Бағыт расталмаған.","The route is unconfirmed."))
        elif price_intent:
            units = {"per_person":_say(lang,"с человека","адам басына","per person"),"per_group":_say(lang,"за группу","топқа","per group"),"per_person_group_size":_say(lang,"с участника группы","топ қатысушысына","per group participant")}
            offers = [f"{o['name']}: {o['amount']:g} {o['currency']} {units[o['unit']]}" for o in result["ticket_offers"]]
            summary = heading + ("; ".join(offers) if offers else _say(lang,"Цена билета не подтверждена.","Билет бағасы расталмаған.","The ticket price is unconfirmed."))
            formulas = [f["value"] for f in result["facts"] if f["field"] == "price_formula"]
            if formulas:
                summary += ". " + "; ".join(str(f) for f in formulas)
        else:
            summary = heading + _say(lang,"Условия, маршруты и опубликованные тарифы — в карточке услуги.","Қызмет шарттары, бағыттары және жарияланған бағалары қызмет карточкасында.","Service conditions, routes and published fares are shown in the service card.")
        summaries.append(summary)
        results.append(result)
    return results, "\n".join(summaries), list(dict.fromkeys(notes))
