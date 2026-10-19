"""Small real HTTP/model regression run using the pre-existing shared USD0.10 guard."""
import asyncio
import json
import os
from pathlib import Path
import socket
from datetime import datetime, timezone

import httpx

ROOT=Path.cwd()
OUT=ROOT/"eval/runs/2026-10-19-catalog-refresh"


async def main():
    key=Path("/Users/muratovaslan/l.env").read_text().strip()
    if not key.startswith("sk-") or "\n" in key:
        raise ValueError("Expected one bare key in the authorized file")
    os.environ.update(OPENAI_API_KEY=key,LLM_ENABLED="true",LLM_WARMUP_ENABLED="false",
        LLM_MODELS="gpt-4.1-mini",LLM_PARSE_MODEL="gpt-4.1-mini",LLM_SERVICE_TIER="",
        LLM_TIMEOUT_S="18",PARSE_TIMEOUT_S="12",EMBED_MODEL="e5-small",WEATHER_ENABLED="false",
        HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",READINESS_PROFILE="llm",RATE_LIMIT_PER_MIN="300",
        DATABASE_URL="sqlite:///"+str(OUT/"probe-accounts.db"))
    from scripts.live_model_probe import BudgetTransport
    from openai import AsyncOpenAI
    from ayat_backend.app import llm
    from ayat_backend.app.main import app
    import uvicorn
    guard=BudgetTransport(ROOT/"eval/runs/2026-10-19-remediation/provider-cost.json")
    sdk=AsyncOpenAI(api_key=key,max_retries=0,http_client=httpx.AsyncClient(transport=guard,timeout=22))
    llm._client=sdk
    llm._client_configuration=llm._configuration()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="warning"))
    task=asyncio.create_task(server.serve())
    cases=[("meal-unconfirmed",{"query":"Я рядом с экспо хочу домашней еды пюре с котлетой очень дешево"}),
           ("nearer-preserves-meal",{"query":"Поближе пожалуйста","food_context":[
               {"kind":"menu","text":"пюре"},{"kind":"menu","text":"котлетой"},
               {"kind":"price","text":"до2000тенге"}],"refine":["closer"]}),
           ("generic-food-model",{"query":"Где поесть рядом с экспо?"}),
           ("redbus-route",{"query":"Какой маршрут у RedBus?"})]
    rows=[]
    try:
        for _ in range(400):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.1)
        if not server.started:
            raise RuntimeError("Probe server startup timed out")
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",timeout=45) as client:
            before=(await client.get("/api/health")).json()
            for ident,req in cases:
                request={"lang":"ru","landmark":"expo","now":"2026-10-19T13:00:00+05:00",**req}
                response=await client.post("/api/recommend",json=request)
                body=response.json()
                checks={"http":response.status_code==200}
                if ident in {"meal-unconfirmed","nearer-preserves-meal"}:
                    checks["no_unproved_places"] = body.get("recommendations")==[]
                    checks["honest_unknown"] = "нет подтверждения" in body.get("summary","").lower()
                    checks["requirements_retained"] = bool(body.get("used_context",{}).get("parsed_from_query",{}).get("food_requirements"))
                elif ident=="generic-food-model":
                    checks["places"] = bool(body.get("recommendations"))
                    checks["model_used"] = body.get("llm",{}).get("mode")=="llm"
                else:
                    checks["route_roles"] = "проезд мимо" in body.get("summary","") and "посадка" in body.get("summary","")
                rows.append({"id":ident,"request":request,"response":body,"checks":checks})
            after=(await client.get("/api/health")).json()
        report={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"execution_kind":"live_http_external_provider",
            "snapshot_version":after.get("snapshot_version"),"health_before":before,"health_after":after,
            "results":rows,"cost":guard.data,"passed":all(all(r["checks"].values()) for r in rows)}
        (OUT/"live-food.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({"passed":report["passed"],"cases":len(rows),"actual_usd_total":guard.data["actual_usd"],
                          "reserved_usd_total":guard.data["reserved_usd"]}))
        return 0 if report["passed"] else 1
    finally:
        server.should_exit=True
        await task
        await sdk.close()


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
