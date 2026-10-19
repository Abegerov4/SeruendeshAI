"""A selected real ID cannot launder unsupported model claims into data."""
import re
import pytest
from ayat_backend.app.categories import CATEGORIES
from ayat_backend.app.i18n import WHAT_TO_DO

from ayat_backend.app.generate import GenOut, GenPick, template_todo, validate
from ayat_backend.app.retrieval import Cand


def candidate(category="cafe"):
    return Cand(idx=0, poi={"id": "audit:1", "name": "Local place", "category": category,
                           "features": {}, "opening_hours": None, "popularity": 0},
                distance_m=100, travel_min=2, visit_min=15, visit_range=(15, 30),
                opening={"status": "unknown", "confidence": "low"})


def test_generated_facilities_and_events_do_not_become_poi_explanations():
    c = candidate()
    out = GenOut(summary="Здесь бесплатная выставка динозавров", picks=[GenPick(
        cand="c1", why="Есть бесплатный Wi-Fi, розетки и вход без ступеней.",
        what_to_do="Посетите бесплатную выставку динозавров.", visit_min=240)], idea=None)
    result = validate(out, {"c1": c}, None, "ru")
    visible = " ".join([result.summary, result.picks[0].why, result.picks[0].what_to_do]).lower()
    assert not any(word in visible for word in ["wi-fi", "розетки", "ступен", "динозавр", "бесплат"])
    assert result.picks[0].visit_min <= 30


def test_generic_coworking_action_does_not_claim_wifi_or_power():
    visible = template_todo(candidate("coworking"), "ru").lower()
    assert "wi-fi" not in visible and "розетки" not in visible


def test_category_cannot_create_free_or_child_facility_badges():
    from ayat_backend.app.retrieval import Plan
    from ayat_backend.app.service import _badges
    plan = Plan(origin=(51.128, 71.43), mode="walk", m_per_min=60, budget=60, t_max=20, radius_m=1000)
    assert "free" not in _badges(candidate("park"), plan)
    assert "kids" not in _badges(candidate("playground"), plan)


@pytest.mark.parametrize("category", sorted(CATEGORIES))
@pytest.mark.parametrize("lang", ["ru", "kk", "en"])
def test_category_actions_do_not_invent_facilities_menus_or_visit_lengths(category, lang):
    # Inspect both the source template and its rendered unknown-facts action:
    # a special-case renderer must not hide unsafe text in another code path.
    visible = (WHAT_TO_DO[category][lang] + " " + template_todo(candidate(category), lang)).casefold()
    assert not re.search(r"\d", visible), "Planner owns duration; generic advice cannot add times, prices or age limits"
    unsupported = ("скам", "bench", "орындық", "розет", "outlet", "socket", "wi-fi", "wifi",
                   "тишин", "тыныш", "silence", "quiet", "десерт", "dessert", "морожен", "ice cream",
                   "baursak", "баурсак", "бауырсақ", "курт", "dish of the day", "блюдо дня", "күннің тағам",
                   "speciality", "фудкорт", "food court", "главной алле", "main alley", "негізгі алле",
                   "таблич", "plaque", "тақтайша", "обычно", "usually", "онлайн", "online",
                   "тёплая", "warm stop", "жылы аялдама")
    assert not any(fragment in visible for fragment in unsupported), "Unknown local facilities/menu/conditions remain unknown"
