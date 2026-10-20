"""Langfuse tracing stays off without keys and never carries the photo or the user's position."""
from app import llm, tracing
from app.schemas import RecommendRequest
from app.service import _trace_request


def test_tracing_is_a_noop_without_keys():
    assert not tracing.is_enabled()
    with tracing.request("recommend", input={"query": "кофе"}) as root, \
            tracing.observe("rank-candidates", as_type="retriever") as step:
        root.update(output={"ok": True})
        step.update(output=[])
    tracing.update_current(metadata={"cache": "hit"})
    tracing.flush()


def test_photo_is_not_sent_to_tracing():
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": [{"type": "input_text", "text": "PLACES"},
                                         {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA", "detail": "low"}]}]
    out = llm._trace_input(msgs)
    assert "base64" not in str(out)
    assert out[1]["content"][0] == {"type": "input_text", "text": "PLACES"}
    assert msgs[1]["content"][1]["image_url"].startswith("data:")  # the model still gets the photo


def test_trace_request_has_no_position_or_pii():
    req = RecommendRequest(query="кофе, звоните +77011234567", location={"lat": 51.128, "lon": 71.43}, lang="ru",
                           home={"lat": 51.1, "lon": 71.4, "label": "дом"})
    inp, meta, tags = _trace_request(req)
    text = str((inp, meta, tags))
    assert "77011234567" not in text and "51.128" not in text and "71.4" not in text
    assert meta["origin"] == "gps" and "channel:web" in tags
