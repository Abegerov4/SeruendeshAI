"""User food wishes must survive parsing without becoming invented POI facts."""
from importlib import import_module

import pytest
from pydantic import ValidationError


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield


def requirements(text):
    food = import_module("app.food")
    return [(item.kind, item.text) for item in food.parse_food_requirements(text)]


def test_preserves_expo_meal_home_style_and_price_wishes_as_verbatim_spans():
    assert requirements(
        "я рядом с экспо хотелось бы вкусно покушать домашней еды "
        "пюре с котлетой очень дешево где можно?"
    ) == [
        ("style", "домашней еды"),
        ("menu", "пюре"),
        ("menu", "котлетой"),
        ("price", "очень дешево"),
    ]


@pytest.mark.parametrize(("text", "expected"), [
    ("Хочу Борщ и пельмени", [("menu", "Борщ"), ("menu", "пельмени")]),
    ("Where can I eat mashed potatoes and cutlets?", [("menu", "mashed potatoes"), ("menu", "cutlets")]),
    ("Маған палау мен қуырдақ керек, арзан болсын", [("menu", "палау"), ("menu", "қуырдақ"), ("price", "арзан")]),
    ("I want vegan soup under 2000 KZT", [("diet", "vegan"), ("menu", "soup"), ("price", "under 2000 KZT")]),
    ("Хочу халал еду до 2 000 ₸", [("diet", "халал"), ("price", "до 2 000 ₸")]),
    ("Домашняя кухня, столовая, недорого", [("style", "Домашняя кухня"), ("style", "столовая"), ("price", "недорого")]),
    ("home-style food in a canteen for $5", [("style", "home-style food"), ("style", "canteen"), ("price", "for $5")]),
    ("Үй тағамы, асхана, 1500 теңге", [("style", "Үй тағамы"), ("style", "асхана"), ("price", "1500 теңге")]),
    ("Нужна грузинская кухня без мяса", [("style", "грузинская кухня"), ("diet", "без мяса")]),
    ("Italian cuisine and gluten-free pasta", [("style", "Italian cuisine"), ("diet", "gluten-free"), ("menu", "pasta")]),
    ("Қазақ тағамдары, етсіз", [("style", "Қазақ тағамдары"), ("diet", "етсіз")]),
    ("Бюджет 2500 тг, хочу лагман", [("price", "Бюджет 2500 тг"), ("menu", "лагман")]),
])
def test_explicit_food_requests_in_supported_languages(text, expected):
    assert requirements(text) == expected


@pytest.mark.parametrize("text", [
    "где поесть рядом",
    "Погулять у Экспо, потом кофе",
    "coffee near me",
    "тамақ ішетін жер қайда?",
    "Обед в 18:30, есть 40 минут",
    "Я рядом с Суши Весла, где поесть?",
    "Near Pizza Hut, I'd like a walk",
    "Блюдо и цена не важны",
    "не обязательно дешево",
    "не хочу котлеты",
    "котлеты не хочу",
    "I don't want cutlets",
    "cheap food is not important",
    "Арзан болуы міндетті емес",
    "котлет жегім келмейді",
])
def test_generic_origins_time_and_dismissed_wishes_do_not_add_constraints(text):
    assert requirements(text) == []


@pytest.mark.parametrize(("text", "expected"), [
    ("Не хочу котлеты, хочу пюре", [("menu", "пюре")]),
    ("Не обязательно дешево, но нужен борщ", [("menu", "борщ")]),
    ("не хочу пюре с котлетой; хочу суп", [("menu", "суп")]),
    ("I don't need cheap food, but I want soup", [("menu", "soup")]),
    ("Хочу пюре, цена не важна", [("menu", "пюре")]),
])
def test_negation_stays_in_its_own_clause(text, expected):
    assert requirements(text) == expected


def test_duplicate_wishes_are_stable_and_remain_verbatim():
    assert requirements("Хочу Пюре, пюре и котлеты") == [
        ("menu", "Пюре"), ("menu", "котлеты"),
    ]


def test_food_requirement_rejects_fact_shaped_or_oversize_payloads():
    food = import_module("app.food")
    with pytest.raises(ValidationError):
        food.FoodRequirement(kind="menu", text="пюре", poi_id="invented")
    with pytest.raises(ValidationError):
        food.FoodRequirement(kind="availability", text="пюре")
    with pytest.raises(ValidationError):
        food.FoodRequirement(kind="menu", text="x" * 121)
    with pytest.raises(ValidationError):
        food.FoodRequirement(kind="menu", text="")


@pytest.mark.parametrize(("text", "phrase", "expected"), [
    ("не хочу чак-чак", "чак-чак", False),
    ("не обязательно дешево", "дешево", False),
    ("Хочу чак-чак", "чак-чак", True),
    ("Я у Суши Весла", "Суши", False),
    ("Мне нужен котлетный суп", "котлет", False),
    ("Хочу суп", "су", False),
    ("Хочу чак-чак", "ЧАК-ЧАК", False),
    ("Хочу суп", "", False),
    ("Не хочу чак-чак, но хочу чак-чак", "чак-чак", True),
])
def test_model_spans_must_be_literal_asserted_user_phrases(text, phrase, expected):
    food = import_module("app.food")
    assert food.food_requirement_is_asserted(text, phrase) is expected


@pytest.mark.parametrize("text", [
    "дешёвый музей рядом",
    "билет в кино до 2000 тенге",
    "taxi under $10",
    "дешево",
    "Я возле столовой, хочу погулять",
    "I'm near a canteen and want a walk",
])
def test_prices_and_origin_format_words_do_not_turn_other_trips_into_food_requests(text):
    assert requirements(text) == []


@pytest.mark.parametrize(("text", "expected"), [
    ("cheap coffee near me", [("price", "cheap")]),
    ("Хочу недорого поесть", [("price", "недорого")]),
    ("Я возле столовой, хочу пюре", [("menu", "пюре")]),
    ("хочу пюре и не хочу котлеты", [("menu", "пюре")]),
    ("не хочу котлеты и хочу пюре", [("menu", "пюре")]),
    ("пюре и котлеты не важны", []),
])
def test_food_context_and_separate_affirmative_requests_survive(text, expected):
    assert requirements(text) == expected
