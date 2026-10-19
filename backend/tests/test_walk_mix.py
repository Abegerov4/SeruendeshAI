from app.query import parse_rules


def test_coffee_and_a_walk_is_a_mix_not_three_cafes():
    assert parse_rules("хочу попить кофе и прогулка на час").walk_mix
    assert parse_rules("coffee and a walk").walk_mix
    assert not parse_rules("кофе рядом").walk_mix          # no walk: cafés only
    assert not parse_rules("погулять в парке").walk_mix    # no food: the walk itself
