"""Telegram channel: its own voice on top of the shared system prompt, same facts and rules."""
import asyncio

import pytest
from pydantic import ValidationError

from app import generate as gen_mod
from app import service
from app.generate import SYSTEM, SYSTEM_BY_CHANNEL, TELEGRAM_STYLE, GenOut, GenPick
from app.schemas import RecommendRequest
from .test_temporal_safety import cand, ctx, poi, store


def test_telegram_prompt_extends_the_shared_rules():
    tg = SYSTEM_BY_CHANNEL["telegram"]
    assert tg.startswith(SYSTEM) and tg.endswith(TELEGRAM_STYLE)
    assert "Hard rules" in tg and "Seru" in TELEGRAM_STYLE


def test_channel_is_validated():
    assert RecommendRequest(query="кофе", channel="telegram").channel == "telegram"
    assert RecommendRequest(query="кофе").channel is None
    with pytest.raises(ValidationError):
        RecommendRequest(query="кофе", channel="whatsapp")


@pytest.mark.parametrize("channel,expected", [("telegram", SYSTEM + TELEGRAM_STYLE), (None, SYSTEM), ("web", SYSTEM)])
def test_generate_picks_the_system_prompt_by_channel(monkeypatch, channel, expected):
    seen = {}

    async def fake_parse(schema, system, user, **kw):
        seen["system"] = system
        return None, None, 0
    monkeypatch.setattr(gen_mod, "parse", fake_parse)
    from app.query import parse_rules
    from app.retrieval import Plan
    plan = Plan(origin=(51.128, 71.43), mode="walk", m_per_min=75, budget=60, t_max=30, radius_m=1500)
    asyncio.run(gen_mod.generate([cand()], None, ctx(), plan, parse_rules("coffee"), "coffee", "en", channel))
    assert seen["system"] == expected


def test_service_forwards_the_channel(monkeypatch):
    rt = service.Runtime(store([poi(1)]), None, None, None, None, None, {})
    monkeypatch.setattr(service, "llm_client", lambda: object())

    async def no_parse(*args, **kwargs): return None, None, 0
    monkeypatch.setattr(service, "llm_parse", no_parse)
    seen = {}

    async def model(cands, *args):
        seen["channel"] = args[-1]
        cmap = {f"c{i + 1}": c for i, c in enumerate(cands)}
        return GenOut(summary="Вот кофе рядом:", picks=[GenPick(cand=k, why="Рядом", what_to_do="Возьмите кофе", visit_min=30)
                                                        for k in cmap], idea=None), "fake", 0, cmap
    monkeypatch.setattr(service, "generate", model)
    asyncio.run(service.recommend(rt, RecommendRequest(query="кофе", location={"lat": 51.128, "lon": 71.43}, channel="telegram",
                                                       now="2026-10-19T11:00:00+05:00", lang="ru")))
    assert seen["channel"] == "telegram"
