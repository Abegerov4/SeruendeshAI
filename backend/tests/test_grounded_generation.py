"""Critical factual prose is composed by code from accepted candidate facts."""
from backend.app import generate
from backend.app.intent import Intent


def test_model_source_and_existing_id_cannot_assert_missing_services(monkeypatch):
    poi = {"id": "audit:1", "name": "Local cafe", "category": "cafe", "tags": [],
           "distance_m": 100, "travel_min": 2, "open_status": "unknown"}
    monkeypatch.setattr(generate.llm, "chat_json", lambda *a, **kw: {"recommendations": [{
        "poi_id": poi["id"], "why": "Есть бесплатный Wi-Fi, розетки и вход без ступеней.",
        "what_to_do": "Посетите бесплатную выставку динозавров.", "visit_min": [5, 10], "source": "poi_data"}]})
    items, notes = generate.llm_generate("кафе", Intent(time_budget_min=30, mode="walk"), [poi], None)
    text = " ".join([items[0]["why"], items[0]["what_to_do"], *notes]).lower()
    assert not any(word in text for word in ["wi-fi", "розетки", "ступен", "динозавр", "бесплат"])
