"""The Decisions API as the auxiliary judge: intent, fit and photo checks, and that the assistant works without it."""
import asyncio
import types

import pytest

from app import decisions, llm, photo, service
from app.query import Parsed
from app.retrieval import Cand


def cand(pid, name="X", cat="cafe"):
    return Cand(idx=0, poi={"id": pid, "name": name, "category": cat, "lat": 51.1, "lon": 71.4}, distance_m=300,
                travel_min=5, visit_min=20, visit_range=(15, 30), opening={"status": "open", "confidence": "high"})


# --- intent ------------------------------------------------------------------------------------------

def test_intent_adds_only_what_the_judge_is_sure_of_when_the_parse_answered():
    p = Parsed()
    added = service.apply_intent(p, {"with_kids": 0.97, "indoor": 0.9, "quiet": 0.99, "night": 0.99, "unusual": 0.99},
                                 parse_answered=True)
    assert added == ["with_kids", "quiet"] and p.needs == {"kids", "quiet"}
    assert not p.night and not p.surprise  # these change the search a lot: only when the parse did not answer


def test_intent_stands_in_for_a_parse_that_did_not_answer():
    p = Parsed()
    added = service.apply_intent(p, {"with_kids": 0.85, "night": 0.9, "unusual": 0.2}, parse_answered=False)
    assert added == ["with_kids", "night"] and "kids" in p.needs and p.night and not p.surprise


def test_intent_never_removes_and_ignores_no_answer():
    p = Parsed(needs={"kids"}, party="family_kids")
    assert service.apply_intent(p, {"with_kids": 0.01, "indoor": 0.01}, parse_answered=True) == []
    assert p.needs == {"kids"}
    assert service.apply_intent(p, None, parse_answered=False) == []


# --- fit ---------------------------------------------------------------------------------------------

def run_fit(monkeypatch, probs, cands, keep_ids=frozenset(), keep_order=False):
    async def fake_fit(query, situation, cards):
        assert [c["id"] for c in cards] == [f"c{i + 1}" for i in range(len(cards))]
        return probs
    monkeypatch.setattr(decisions, "fit", fake_fit)
    monkeypatch.setattr(service, "context_block", lambda *a: "TARGET LANGUAGE\nlocal_time: Tue 15:00")
    monkeypatch.setattr(service, "card", lambda c, cid, lang: {"id": cid, "name": c.poi["name"]})
    return asyncio.run(service.check_fit(cands, "с ребёнком, холодно", None, None, None, "ru",
                                         keep_ids=set(keep_ids), keep_order=keep_order))


def test_fit_drops_clear_misfits_and_moves_strong_fits_up(monkeypatch):
    cs = [cand("a"), cand("b"), cand("c"), cand("d"), cand("e")]
    kept, info = run_fit(monkeypatch, {"c1": 0.5, "c2": 0.02, "c3": 0.95, "c4": 0.0, "c5": 0.8}, cs)
    assert [c.poi["id"] for c in kept] == ["c", "e", "a"]  # strong first in their own order, then the rest
    assert [c.poi["id"] for c in info["dropped"]] == ["d", "b"] and info["checked"] == 5
    assert kept[0].match == 0.95


def test_fit_keeps_three_places_and_the_named_one(monkeypatch):
    cs = [cand("a"), cand("b"), cand("c"), cand("t")]
    kept, info = run_fit(monkeypatch, {"c1": 0.0, "c2": 0.05, "c3": 0.01, "c4": 0.0}, cs, keep_ids={"t"})
    assert len(kept) == 3 and "t" in [c.poi["id"] for c in kept]
    assert [c.poi["id"] for c in info["dropped"]] == ["a"]


def test_fit_keeps_a_mixed_order_and_survives_no_answer(monkeypatch):
    cs = [cand("food1"), cand("walk1"), cand("walk2"), cand("food2")]
    kept, _ = run_fit(monkeypatch, {"c1": 0.4, "c2": 0.9, "c3": 0.9, "c4": 0.05}, cs, keep_order=True)
    assert [c.poi["id"] for c in kept] == ["food1", "walk1", "walk2"]
    cs = [cand("a"), cand("b")]
    kept, info = run_fit(monkeypatch, None, cs)
    assert kept == cs and info["checked"] == 0 and all(c.match is None for c in cs)


# --- the API call itself -----------------------------------------------------------------------------

class FakeDecisions:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.result


def fake_client(monkeypatch, dec):
    monkeypatch.setattr(decisions, "client", lambda: types.SimpleNamespace(decisions=dec))


def test_ask_returns_answers_and_bills_input_tokens_only(monkeypatch):
    result = types.SimpleNamespace(
        answers=[{"type": "predicate", "name": "c1", "probability": 0.91}, {"type": "refusal", "name": "c2"}],
        usage=types.SimpleNamespace(input_tokens=1000, output_tokens=0))
    result.model_dump = lambda: {"answers": result.answers}
    dec = FakeDecisions(result)
    fake_client(monkeypatch, dec)
    meter, mark = llm.usage_begin()
    ans = asyncio.run(decisions.ask("x", [{"type": "predicate", "name": "c1", "instructions": "?"}], name="t"))
    assert ans == {"c1": {"type": "predicate", "name": "c1", "probability": 0.91}}
    assert dec.calls[0]["model"] == "gpt-6-luna"
    assert llm.usage_summary(meter[mark:]) == {"input_tokens": 1000, "output_tokens": 0, "cost_usd": 0.0001}


@pytest.mark.parametrize("error", [asyncio.TimeoutError(), RuntimeError("403 forbidden")])
def test_ask_failure_means_answer_without_the_judge(monkeypatch, error):
    fake_client(monkeypatch, FakeDecisions(error=error))
    assert asyncio.run(decisions.ask("x", [{"type": "predicate", "name": "q", "instructions": "?"}], name="t")) is None


def test_no_key_no_call(monkeypatch):
    monkeypatch.setattr(decisions, "client", lambda: None)
    assert not decisions.enabled()
    assert asyncio.run(decisions.intent("кофе рядом")) is None


def test_photo_choice_reads_the_chosen_place_and_none(monkeypatch):
    places = {"baiterek": {"name": "Байтерек"}, "expo": {"name": "ЭКСПО"}}
    async def ask(inp, questions, **kw):
        assert [c["value"] for c in questions[0]["choices"]] == ["baiterek", "expo", "none"]
        return {"place": {"type": "choice", "name": "place", "choice": choice,
                          "probabilities": [{"value": "baiterek", "probability": 0.9}, {"value": "none", "probability": 0.7}]}}
    monkeypatch.setattr(decisions, "ask", ask)
    choice = "baiterek"
    assert asyncio.run(decisions.photo_place("data:image/jpeg;base64,", places)) == ("baiterek", 0.9)
    choice = "none"
    assert asyncio.run(decisions.photo_place("data:image/jpeg;base64,", places)) == (None, 0.7)


# --- photo: two looks at one picture -------------------------------------------------------------------

def guess(pid, conf="medium"):
    return photo.PhotoGuessLLM(place_id=pid, confidence=conf, description="башня")


def test_photo_agreement_is_high_and_a_sure_judge_wins():
    g, p = photo.combine(guess("baiterek", "low"), ("baiterek", 0.6))
    assert g.place_id == "baiterek" and g.confidence == "high" and p == 0.6
    g, p = photo.combine(guess(None, "low"), ("expo", 0.95))
    assert g.place_id == "expo" and g.confidence == "high" and g.description == "башня"
    g, p = photo.combine(None, ("expo", 0.85))
    assert g.place_id == "expo" and g.confidence == "medium"


def test_photo_judge_sure_of_none_distrusts_the_vision_guess_and_unsure_judge_changes_nothing():
    g, p = photo.combine(guess("baiterek", "high"), (None, 0.9))
    assert g.confidence == "low" and p is None
    g, p = photo.combine(guess("baiterek", "medium"), ("expo", 0.5))
    assert g.place_id == "baiterek" and g.confidence == "medium" and p is None
    g, p = photo.combine(guess("baiterek"), None)
    assert g.place_id == "baiterek" and p is None
