"""Actual local HTTP scenarios with every external provider disabled."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket

import httpx

ROOT = Path.cwd()
OUT = ROOT / "eval/runs/2026-10-19-food-service"


async def main():
    os.environ.update(OPENAI_API_KEY="", LLM_API_KEY="", LLM_ENABLED="false", EMBED_MODEL="off",
        WEATHER_ENABLED="false", SMTP_HOST="", SMTP_USER="", SMTP_PASSWORD="", SMTP_FROM="",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", RATE_LIMIT_PER_MIN="300",
        DATABASE_URL="sqlite:///" + str(OUT / "food-service-probe.db"))
    from ayat_backend.app.main import app
    from ayat_backend.app.store import load_store
    import uvicorn

    store = load_store("off")
    blocked = {"citypass:119", "citypass:142", "citypass:94", "osm:node/13448013130",
        "overture:3105494a-8102-4450-9d78-12ca652ce768", "overture:5a405c91-d5d6-47ee-9b9b-546134f0505d",
        "overture:a4de9304-82bf-4d82-b811-1a18cc29a44e", "overture:dc97b064-be10-46d8-9168-76343e2e115d"}
    assert not blocked & set(store.by_id)
    origins = {g.get("id") for g in store.gazetteer}
    assert "osm:node/13448013130" in origins
    assert not (blocked - {"osm:node/13448013130"}) & origins
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    cases = [
        ("unproved-cutlet-meal", {"query": "Я рядом с экспо хочу домашней еды пюре с котлетой очень дешево"}),
        ("budget-followup-keeps-meal", {"query": "А можно до 1000 тенге?", "food_context": [
            {"kind": "menu", "text": "пюре"}, {"kind": "menu", "text": "котлетой"},
            {"kind": "price", "text": "до 2000 тенге"}]}),
        ("generic-food", {"query": "Где поесть рядом с экспо?"}),
        ("base-price-not-complete-cost", {"query": "Суп с фрикадельками рядом с экспо до 3000 тенге"}),
        ("redbus-route", {"query": "Какой маршрут у RedBus?"}),
        ("redbus-last-departure-unknown", {"query": "Последний рейс RedBus сегодня во сколько?"}),
        ("walk-no-service-offers", {"query": "Хочу погулять рядом с Байтереком"}),
    ]
    for ident, time, query in [
        ("kitchen-before-close", "21:10:00", "Хочу поесть в Coffee Hub на Кенесары 24"),
        ("kitchen-after-close", "21:31:00", "Хочу поесть в Coffee Hub на Кенесары 24"),
        ("coffee-after-meal-kitchen-close", "21:31:00", "Кофе в Coffee Hub на Кенесары 24"),
    ]:
        cases.append((ident, {"query": query, "landmark": None, "location": {"lat":51.164,"lon":71.418},
            "now": "2026-10-19T" + time + "+05:00"}))
    cases.append(("italio-onsite-menu", {"query":"Пицца в Italio Homemade Pizza", "landmark":None,
        "location":{"lat":51.120,"lon":71.460}}))
    results = []
    try:
        for _ in range(400):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.1)
        if not server.started:
            raise RuntimeError("Local provider-off startup timed out")
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=45) as client:
            health = (await client.get("/api/health")).json()
            for ident, values in cases:
                request = {"lang": "ru", "landmark": "expo", "now": "2026-10-19T13:00:00+05:00", **values}
                response = await client.post("/api/recommend", json=request)
                body = response.json()
                ids = {p["poi_id"] for p in body.get("recommendations", [])}
                checks = {"http_ok": response.status_code == 200,
                          "no_excluded_places": not ids & blocked,
                          "no_external_model": body.get("llm", {}).get("mode") != "llm"}
                if ident in {"unproved-cutlet-meal", "budget-followup-keeps-meal"}:
                    checks["unproved_places_withheld"] = body.get("recommendations") == []
                    checks["honest_unknown"] = "нет подтверждения" in body.get("summary", "").lower()
                    checks["meal_preserved"] = sum(r["kind"] == "menu" for r in body.get("used_context", {}).get("parsed_from_query", {}).get("food_requirements", [])) >= 2
                elif ident == "generic-food":
                    checks["actual_places"] = bool(ids)
                elif ident == "base-price-not-complete-cost":
                    checks["unknown_fees_not_zero"] = not ids and "нет подтверждения" in body.get("summary", "").lower()
                elif ident == "italio-onsite-menu":
                    found = next((p for p in body.get("recommendations", []) if p["poi_id"] == "overture:b6f93c10-c613-4dea-bf99-4a468890fbcf"), {})
                    menu = found.get("menu_items", [])
                    checks["real_onsite_menu"] = len(menu) == 102
                    checks["verified_partial_fee"] = bool(menu) and all(m.get("cost", {}).get("service_percent") == 10 for m in menu)
                    checks["no_invented_complete_total"] = bool(menu) and all(m.get("cost_status") == "unknown" and m.get("total_price") is None for m in menu)
                elif ident in {"kitchen-before-close", "kitchen-after-close", "coffee-after-meal-kitchen-close"}:
                    expected = ident != "kitchen-after-close"
                    checks["kitchen_window_or_coffee_distinction"] = ("osm:node/12135856708" in ids) == expected
                elif ident == "redbus-route":
                    checks["route_roles"] = "проезд мимо" in body.get("summary", "") and "посадка" in body.get("summary", "")
                elif ident == "redbus-last-departure-unknown":
                    checks["no_invented_current_departure"] = "не подтвержд" in body.get("summary", "").lower() or "нет подтвержд" in body.get("summary", "").lower()
                elif ident == "walk-no-service-offers":
                    checks["ordinary_walk_has_no_tour_answer"] = not body.get("service_results")
                results.append({"id": ident, "request": request, "checks": checks, "response": body})
        report = {"checked_at": datetime.now(timezone.utc).isoformat(), "execution_kind": "local_http_all_external_providers_off",
                  "snapshot_version": store.manifest["snapshot_version"], "health": health,
                  "external_paid_calls": 0, "excluded_recommendations_verified": sorted(blocked),
                  "classification_conflict_origin_preserved": "osm:node/13448013130",
                  "passed": all(all(r["checks"].values()) for r in results), "results": results}
        (OUT / "offline-runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "cases": len(results), "snapshot_version": report["snapshot_version"],
                          "failed": [{"id": r["id"], "checks": r["checks"]} for r in results if not all(r["checks"].values())]}))
        return 0 if report["passed"] else 1
    finally:
        server.should_exit = True
        await task


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
