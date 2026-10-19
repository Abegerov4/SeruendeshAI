import asyncio
import json

import httpx
import pytest

from scripts.live_model_probe import BudgetTransport


def test_budget_refuses_before_paid_request_and_persists_reservation(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": {"input_tokens": 10, "output_tokens": 5}})
    ledger = tmp_path / "cost.json"
    async def run():
        guard = BudgetTransport(ledger, cap_usd=0.005, transport=httpx.MockTransport(handle))
        async with httpx.AsyncClient(transport=guard) as client:
            payload = {"model": "gpt-4.1-mini", "input": "hello", "max_output_tokens": 100}
            assert (await client.post("https://api.openai.com/v1/responses", json=payload)).status_code == 200
            with pytest.raises(RuntimeError, match="budget"):
                await client.post("https://api.openai.com/v1/responses", json={**payload, "input": "x" * 100000})
    asyncio.run(run())
    assert len(calls) == 1
    record = json.loads(ledger.read_text())
    assert record["actual_usd"] == pytest.approx(0.000012)
    assert 0 < record["reserved_usd"] <= 0.005


def test_failed_request_retains_upper_cost_across_restart(tmp_path):
    ledger = tmp_path / "cost.json"
    def fail(request):
        raise httpx.ConnectError("local test")
    async def run():
        guard = BudgetTransport(ledger, cap_usd=0.004, transport=httpx.MockTransport(fail))
        async with httpx.AsyncClient(transport=guard) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post("https://api.openai.com/v1/responses", json={"model": "gpt-4.1-mini", "input": "x", "max_output_tokens": 1000})
        restarted = BudgetTransport(ledger, cap_usd=0.004, transport=httpx.MockTransport(fail))
        async with httpx.AsyncClient(transport=restarted) as client:
            with pytest.raises(RuntimeError, match="budget"):
                await client.post("https://api.openai.com/v1/responses", json={"model": "gpt-4.1-mini", "input": "x", "max_output_tokens": 1000})
    asyncio.run(run())
    assert len(json.loads(ledger.read_text())["attempts"]) == 1


def test_two_guard_instances_share_one_reserved_budget_before_sending(tmp_path):
    calls = []
    async def handle(request):
        calls.append(request)
        await asyncio.sleep(0.01)  # keep the first reservation in flight
        return httpx.Response(200, json={"usage": {"input_tokens": 10, "output_tokens": 5}})
    ledger = tmp_path / "shared-cost.json"
    async def run():
        # Both instances exist before the first reservation, as with two probes
        # starting concurrently. Each request alone fits; together they exceed10c.
        first = BudgetTransport(ledger, transport=httpx.MockTransport(handle))
        second = BudgetTransport(ledger, transport=httpx.MockTransport(handle))
        async with httpx.AsyncClient(transport=first) as one, httpx.AsyncClient(transport=second) as two:
            payload = {"model": "gpt-4.1-mini", "input": "x" * 140000, "max_output_tokens": 1800}
            results = await asyncio.gather(one.post("https://api.openai.com/v1/responses", json=payload),
                                           two.post("https://api.openai.com/v1/responses", json=payload),
                                           return_exceptions=True)
            assert sum(isinstance(result, httpx.Response) for result in results) == 1
            errors = [result for result in results if isinstance(result, RuntimeError)]
            assert len(errors) == 1 and "budget" in str(errors[0])
    asyncio.run(run())
    assert len(calls) == 1
    record = json.loads(ledger.read_text())
    assert len(record["attempts"]) == 1
    assert record["reserved_usd"] <= 0.10


def test_known_billed_usage_releases_unused_reservation_but_not_paid_cost(tmp_path):
    async def run():
        guard = BudgetTransport(tmp_path / "cost.json", cap_usd=0.004, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"usage": {"input_tokens": 10, "output_tokens": 5}})))
        async with httpx.AsyncClient(transport=guard) as client:
            for _ in range(3):
                assert (await client.post("https://api.openai.com/v1/responses", json={
                    "model": "gpt-4.1-mini", "input": "hello", "max_output_tokens": 1000})).status_code == 200
        assert guard.data["actual_usd"] == pytest.approx(0.000036)
        assert guard.data["reserved_usd"] == pytest.approx(guard.data["actual_usd"])
    asyncio.run(run())
