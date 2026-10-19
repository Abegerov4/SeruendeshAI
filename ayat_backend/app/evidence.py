"""Match explicit food wishes to accepted branch evidence, never category guesses."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import datetime as dt
import re

import numpy as np
import snowballstemmer

from ayat_backend.app.food import FoodRequirement
from ayat_backend.app.geo import hav_m
from ayat_backend.app.textnorm import fold
from data.meal_cost import complete_meal_price, cost_evidence_current

_RU = snowballstemmer.stemmer("russian")
_EN = snowballstemmer.stemmer("english")
_STOP = {"еда", "food", "кухня", "cuisine", "meal", "нужный", "хочу", "с", "и", "a", "and", "with"}


def _terms(text: str) -> set[str]:
    text = fold(text)
    for pattern, replacement in [(r"mashed potatoes", "пюре"), (r"cutlets?", "котлета"),
                                  (r"\bpizzas?\b", "пицца"),
                                  (r"home[ -](?:style|cooked|made)", "домашняя"), (r"canteens?|cafeterias?", "столовая")]:
        text = re.sub(pattern, replacement, text)
    words = {(_EN if re.fullmatch(r"[a-z]+", word) else _RU).stemWord(word)
            for word in re.findall(r"[a-zа-я]+", text) if len(word) > 1 and word not in _STOP}
    return words - {_RU.stemWord(word) for word in _STOP}


def _accepted(item: dict, today: dt.date, age: int = 30) -> bool:
    try:
        checked = dt.date.fromisoformat(item["source"]["checked_at"])
        return (item.get("status") == "accepted" and item.get("conflict_status") == "none"
                and item.get("branch_scope") == "exact" and item["source"].get("url", "").startswith(("http://", "https://"))
                and 0 <= (today-checked).days <= age
                and (not item.get("valid_from") or dt.date.fromisoformat(item["valid_from"]) <= today)
                and (not item.get("valid_to") or today <= dt.date.fromisoformat(item["valid_to"])))
    except (KeyError, TypeError, ValueError):
        return False


def accepted_details(poi: dict, today: dt.date) -> dict:
    data = poi.get("place_details") or {}
    result = {key:[deepcopy(item) for item in data.get(key, []) if _accepted(item, today, 90 if key == "facts" else 30)]
              for key in ("facts", "menu_items", "prices")}
    for item in result["menu_items"]:
        if "cost" in item and not cost_evidence_current(item, today):
            item.pop("cost")
        item["total_price"] = complete_meal_price(item, today)
        item["cost_status"] = "complete" if item["total_price"] is not None else "unknown"
    return result


def price_comparison_group(poi: dict, today: dt.date) -> str | None:
    groups={p.get("comparison_group",poi.get("category")) for p in accepted_details(poi,today)["prices"]
            if p.get("kind")=="average_check" and p.get("currency")=="KZT" and p.get("channel")=="dine_in"}
    return next(iter(groups)) if len(groups)==1 else None


def price_benchmarks(pois: list[dict], origin, today: dt.date) -> dict:
    """Local, category-specific check statistics; no meal price is inferred."""
    samples = {}
    for poi in pois:
        if float(hav_m(*origin, poi["lat"], poi["lon"])) > 5000:
            continue
        prices = [p for p in accepted_details(poi, today)["prices"]
                  if p.get("kind") == "average_check" and p.get("currency") == "KZT"
                  and p.get("channel") == "dine_in" and isinstance(p.get("amount"), (int,float))]
        if prices:
            # One observation per branch, avoiding chain/menu duplication.
            group = price_comparison_group(poi,today)
            if group in {"cafe", "restaurant"}:
                samples.setdefault(group, []).append(float(prices[0]["amount"]))
    return {category:{"n":len(values), "mean":round(float(np.mean(values)),2),
                      "median":float(np.median(values)), "q25":float(np.quantile(values,.25)),
                      "radius_m":5000, "basis":"reported_average_check", "currency":"KZT"}
            for category, values in samples.items() if len(values) >= 8}


@dataclass
class FoodMatch:
    gaps: list[str] = field(default_factory=list)
    menu_items: list[dict] = field(default_factory=list)
    prices: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)

    @property
    def matched(self):
        return not self.gaps


def match_food(poi: dict, requirements: list[FoodRequirement], today: dt.date, benchmark: dict | None = None,
               *, arrive_at: dt.datetime | None = None, check_kitchen: bool = True) -> FoodMatch:
    data = accepted_details(poi, arrive_at.date() if arrive_at else today)
    result = FoodMatch(**data)
    def available(hours):
        if not arrive_at or not isinstance(hours, str) or not hours.strip():
            return True
        from ayat_backend.app.hours import opening_status
        return opening_status({"opening_hours": hours}, arrive_at, 0, "ru", None)["status"] != "closed"

    kitchens = {f["value"] for f in data["facts"] if f["field"] == "kitchen_hours" and isinstance(f["value"], str)} if check_kitchen else set()
    if len(kitchens) == 1 and not available(next(iter(kitchens))):
        result.gaps.append("kitchen_hours")
    cutoffs = {f["value"] for f in data["facts"] if f["field"] == "kitchen_closes_at" and isinstance(f["value"], str)} if check_kitchen else set()
    if arrive_at and len(cutoffs) == 1:
        cutoff = next(iter(cutoffs))
        # A daily evening cutoff proves only that evening's unavailability.
        # A closing-only 02:00 cannot establish when the next service starts.
        if re.fullmatch(r"(?:1[2-9]|2[0-3]):[0-5]\d", cutoff) and arrive_at.strftime("%H:%M") >= cutoff:
            result.gaps.append("kitchen_hours")
    if not requirements:
        return result
    menu_wishes = [r for r in requirements if r.kind == "menu"]
    # Combined meal requests are proved by one published offering, never by
    # adding an unrelated burger's patty to a separately advertised side dish.
    matching = [m for m in data["menu_items"] if (m.get("channel") or (m.get("price") or {}).get("channel")) == "dine_in"
                and available(m.get("serving_hours"))
                and all(_terms(r.text) <= _terms(" ".join(
        [m["name"], *m.get("components",[]), *m.get("aliases",[])])) for r in menu_wishes)]
    if menu_wishes and not matching:
        result.gaps.append("menu")
    facts_text = " ".join(str(f["value"]) for f in data["facts"] if f["field"] in {"format","cuisine","cuisines"})
    # Narrow one pool through all dish constraints before testing its prices.
    # The order of requirements in natural language must not affect the result.
    for wish in [r for r in requirements if r.kind != "price"]:
        if wish.kind == "style":
            required = _terms(wish.text)
            if required and not required <= _terms(facts_text):
                matching = [m for m in matching if required <= _terms(m["name"])]
            if not required or not required <= _terms(facts_text) and not matching:
                result.gaps.append("style")
        elif wish.kind == "diet":
            s = fold(wish.text)
            fields = ("vegan_options",) if re.search(r"веган|vegan",s) else ("vegetarian_options",) if re.search(r"вегетари|vegetarian|без мяса|етсиз",s) else ("halal",) if re.search(r"халал|halal",s) else ()
            confirmed = any(f["field"] in fields and f["value"] is True for f in data["facts"])
            if (menu_wishes or any(r.kind == "price" for r in requirements)) and fields in {( "vegan_options",),("vegetarian_options",)}:
                pattern = r"веган|vegan" if fields == ("vegan_options",) else r"вегетари|vegetarian|без мяса|етсиз|веган|vegan"
                matching = [m for m in matching if re.search(pattern,fold(" ".join([m["name"],*m.get("components",[])])))]
                confirmed = bool(matching)
            if not confirmed:
                result.gaps.append("diet")
    for wish in [r for r in requirements if r.kind == "price"]:
        if wish.kind == "price":
            number = re.search(r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?",wish.text)
            if number:
                limit = float(number.group().replace(" ","").replace("\u00a0","").replace(",","."))
                currency = "KZT" if re.search(r"тенге|тенге|тг|₸|kzt",fold(wish.text)) else "USD" if "$" in wish.text or "usd" in fold(wish.text) else "EUR" if "€" in wish.text else None
                candidates = matching if menu_wishes else [m for m in matching if m.get("role") == "meal"]
                affordable = [m for m in candidates if (price := m.get("total_price")) and price.get("currency") == currency
                              and price.get("channel") == "dine_in" and price["amount"] <= limit]
                if not affordable:
                    result.gaps.append("price")
                else:
                    matching = affordable
            else:
                checks = [p for p in data["prices"] if p.get("kind") == "average_check" and p.get("currency") == "KZT" and p.get("channel") == "dine_in"]
                if menu_wishes or not benchmark or not checks or not (checks[0]["amount"] <= benchmark["q25"] and checks[0]["amount"] < benchmark["median"]):
                    result.gaps.append("price")
    result.menu_items = matching
    result.gaps = sorted(set(result.gaps))
    return result
