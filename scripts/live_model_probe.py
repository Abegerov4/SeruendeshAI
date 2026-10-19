"""Opt-in real-provider HTTP smoke, with a persistent conservative USD ceiling.

python -m scripts.live_model_probe --key-file /path/to/key --out eval/runs/...
Never writes headers, credentials, full provider prompts or account cookies.
Prices are fixed to the tested gpt-4.1-mini standard tier (2026-10-19).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import fcntl
import uuid
import os
from pathlib import Path
import socket
import time

import httpx


class BudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self, ledger: Path, *, cap_usd=0.10, transport=None):
        self.path, self.cap = Path(ledger), min(float(cap_usd), 0.10)
        self.transport = transport or httpx.AsyncHTTPTransport(retries=0)
        self.lock = asyncio.Lock()
        self.initial = {
            "model": "gpt-4.1-mini", "cap_usd": self.cap, "reserved_usd": 0.0,
            "actual_usd": 0.0, "attempts": [], "pricing_url": "https://developers.openai.com/api/docs/models/gpt-4.1-mini"}
        self.data = json.loads(self.path.read_text()) if self.path.exists() else dict(self.initial)

    def change(self, mutate):
        # OS lock + reload prevent separate instances/processes from overwriting
        # another reservation. The cap can only become more restrictive.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else json.loads(json.dumps(self.initial))
            data["cap_usd"] = min(self.cap, data["cap_usd"])
            self.reconcile(data)
            mutate(data)
            self.reconcile(data)
            temporary = self.path.with_suffix(".pending")
            temporary.write_text(json.dumps(data, indent=2) + "\n")
            os.replace(temporary, self.path)
            self.data = data

    @staticmethod
    def reconcile(data):
        """Keep paid cost plus every uncertain/in-flight maximum under the cap.

        Release unused reservation only after a successful provider response
        reports integer token usage. Timeouts/errors retain their full maximum.
        Historical reservations and usage stay in the append-only attempt list.
        """
        upper, actual = 0.0, 0.0
        for row in data["attempts"]:
            usage = row.get("usage") or {}
            valid = row.get("status") == 200 and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
            if valid:
                charge = (usage["input_tokens"] * 0.40 + usage["output_tokens"] * 1.60) / 1_000_000
                upper += charge
                actual += charge
                row["settled"] = True
            else:
                upper += row["reserved_usd"]
        data["reserved_usd"], data["actual_usd"] = upper, actual

    async def handle_async_request(self, request):
        if request.url.host != "api.openai.com" or request.method != "POST" or request.url.path != "/v1/responses":
            raise RuntimeError("probe permits only OpenAI Responses requests")
        payload = json.loads(request.content)
        if (payload.get("model") != "gpt-4.1-mini" or payload.get("service_tier", "default") != "default"
                or payload.get("tools") or payload.get("previous_response_id") or payload.get("background")):
            raise RuntimeError("probe model/tier/tools do not match fixed pricing")
        output = payload.get("max_output_tokens")
        if type(output) is not int or not 1 <= output <= 1800:
            raise RuntimeError("probe requires bounded output")
        # UTF-8 bytes exceed ordinary BPE token counts; 4096 further covers
        # message/schema framing. Reserve maximum output even for failed calls.
        reserve = ((len(request.content) + 4096) * 0.40 + output * 1.60) / 1_000_000
        attempt_id = uuid.uuid4().hex
        def reserve_cost(data):
            if data["reserved_usd"] + reserve > data["cap_usd"]:
                raise RuntimeError("probe budget would be exceeded; no request sent")
            data["attempts"].append({"id": attempt_id, "number": len(data["attempts"]) + 1,
                                     "max_output_tokens": output, "reserved_usd": reserve, "status": "reserved"})
            data["reserved_usd"] += reserve
        self.change(reserve_cost)
        try:
            response = await self.transport.handle_async_request(request)
            raw = await response.aread()
            usage = json.loads(raw).get("usage") or {}
            actual = (usage.get("input_tokens", 0) * 0.40 + usage.get("output_tokens", 0) * 1.60) / 1_000_000
            def finish(data):
                item = next(row for row in data["attempts"] if row["id"] == attempt_id)
                item.update(status=response.status_code, usage=usage, actual_usd=actual)
                data["actual_usd"] += actual
            self.change(finish)
            return response
        except BaseException:
            def fail(data):
                item = next(row for row in data["attempts"] if row["id"] == attempt_id)
                item["status"] = "failed_or_cancelled_reserved_cost_retained"
            self.change(fail)
            raise

    async def aclose(self):
        await self.transport.aclose()


async def probe(args):
    # Read only here, never echo the file or insert it into a shell command.
    key = args.key_file.read_text().strip()
    if not key.startswith("sk-") or "\n" in key:
        raise ValueError("key file must contain one bare key")
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ.update(OPENAI_API_KEY=key, LLM_ENABLED="true", LLM_WARMUP_ENABLED="false",
                      LLM_MODELS="gpt-4.1-mini", LLM_PARSE_MODEL="gpt-4.1-mini", LLM_SERVICE_TIER="",
                      LLM_TIMEOUT_S="18", PARSE_TIMEOUT_S="12", EMBED_MODEL=args.embed_model,
                      WEATHER_ENABLED="false", READINESS_PROFILE="llm",
                      DATABASE_URL="sqlite:///" + str((args.out / "probe-accounts.db").resolve()))
    from openai import AsyncOpenAI
    from app import llm
    from app import main as application
    from app.main import app, RT
    from backend_scenario_eval import run_checks
    from eval.run_eval import source_fingerprint, git_state, file_sha256
    import uvicorn

    ui_rows = []
    browser_phase = False
    original_recommend = application.recommend
    async def observe_recommend(rt, request):
        t0 = time.perf_counter()
        result = await original_recommend(rt, request)
        if browser_phase:
            body = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            ui_rows.append({"request": request.model_dump(mode="json"), "response": body,
                            "ms": int((time.perf_counter()-t0)*1000), "transport": "browser_to_live_local_http"})
        return result
    application.recommend = observe_recommend
    source_before = source_fingerprint(Path.cwd())
    guard = BudgetTransport(Path(__file__).resolve().parents[1] / "eval/runs/2026-10-19-remediation/provider-cost.json")
    sdk = AsyncOpenAI(api_key=key, max_retries=0, http_client=httpx.AsyncClient(transport=guard, timeout=22))
    llm._client = sdk
    llm._client_configuration = llm._configuration()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    cases = [
        {"id": "ru-coffee", "request": {"query": "Хочу выпить кофе рядом с Байтереком", "lang": "ru", "time_budget_min": 60}},
        {"id": "kk-tourist", "request": {"query": "Мен туристпін, қаланы көргім келеді", "lang": "kk", "tourist": True, "time_budget_min": 90}},
        {"id": "en-short", "request": {"query": "A short walk with a child", "lang": "en", "with_child": True, "time_budget_min": 45}},
    ]
    rows = []
    try:
        async with httpx.AsyncClient(base_url=base, timeout=45) as client:
            for _ in range(300):
                if server.started:
                    break
                if task.done():
                    await task
                await asyncio.sleep(0.1)
            if not server.started:
                raise RuntimeError("local server startup timed out")
            before = (await client.get("/api/health")).json()
            known = set(RT["rt"].store.by_id)
            for case in cases:
                request = {**case["request"], "location": {"lat": 51.128, "lon": 71.430}, "want_route": True,
                           "now": "2026-10-19T14:00:00+05:00",
                           "weather": {"temperature_c": 15, "feels_like_c": 15, "wind_ms": 2}}
                t0 = time.perf_counter()
                response = await client.post("/api/recommend", json=request)
                body = response.json()
                elapsed = int((time.perf_counter() - t0) * 1000)
                checks = run_checks({**case, "expect": {"lang": request["lang"]}}, body, elapsed, known) if response.status_code == 200 else {"http": False}
                # Latency is reported separately; a slow provider cannot pass a
                # claimed <8s performance target by relaxing the evaluator.
                checks["real_llm_mode"] = body.get("llm", {}).get("mode") == "llm"
                rows.append({"id": case["id"], "request": request, "http_status": response.status_code,
                             "ms": elapsed, "checks": checks, "response": body})
            if args.browser_seconds:
                browser_phase = True
                print("BROWSER_URL=" + base, flush=True)
                await asyncio.sleep(args.browser_seconds)
            after = (await client.get("/api/health")).json()
            report = {"runtime_id": "ayat", "execution_kind": "live_http_external_provider", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                      "source_sha256": source_fingerprint(Path.cwd()), **git_state(Path.cwd()),
                      "dataset_sha256": file_sha256(Path("data/processed/pois.json")),
                      "snapshot_version": after.get("snapshot_version"), "health_before": before, "health_after": after,
                      "planned": len(cases), "executed": len(rows), "results": rows,
                      "human_text_review": "NOT_EVALUATED", "ui_browser": ui_rows,
                      "source_sha256_before": source_before, "source_stable": source_before == source_fingerprint(Path.cwd()),
                      "cost": guard.data, "passed": (source_before == source_fingerprint(Path.cwd()) and
                          all(all(v is not False for v in row["checks"].values()) for row in rows) and
                          (not args.browser_seconds or bool(ui_rows) and all(row["response"].get("llm", {}).get("mode") == "llm" for row in ui_rows)))}
            (args.out / "live-model.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"planned": len(cases), "executed": len(rows), "passed": report["passed"],
                              "actual_usd": guard.data["actual_usd"], "reserved_usd": guard.data["reserved_usd"]}))
            return 0 if report["passed"] else 1
    finally:
        server.should_exit = True
        await task
        await sdk.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser-seconds", type=int, choices=range(0, 61), default=0)
    parser.add_argument("--embed-model", choices=["off", "e5-small"], default="e5-small")
    return asyncio.run(probe(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
