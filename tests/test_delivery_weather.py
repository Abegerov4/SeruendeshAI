"""A weather transport failure must remain explicit unknown weather."""
import asyncio
import datetime as dt

import httpx


def test_weather_connection_failure_keeps_context_weather_unknown(monkeypatch):
    from ayat_backend.app import context
    monkeypatch.setattr(context, "_wx_cache", {})
    def unavailable(request):
        raise httpx.ConnectError("local verification of unavailable weather", request=request)
    async def fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
            return await context.fetch_weather(client)
    weather = asyncio.run(fetch())
    assert weather is None
    ctx = context.build_context(dt.datetime(2026, 10, 19, 11, tzinfo=context.TZ), weather, False)
    assert ctx.weather is None and context.weather_out(ctx, "en") is None
