"""Which places does the system actually recommend? A grid of typical requests × Astana starting points × day/evening,
in-process with dense retrieval (as in production) and template texts (no LLM cost). Writes top_places.json."""
import collections, json, os, sys, tempfile
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "sources", "place_research")
os.environ.update({"LLM_ENABLED": "false", "WEATHER_ENABLED": "false", "OPENAI_API_KEY": "", "SECRET_KEY": "x",
                   "RATE_LIMIT_PER_MIN": "100000", "DATABASE_URL": "sqlite:///" + tempfile.mktemp(suffix=".db")})
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.config import Settings, get_settings
Settings.model_config = {**Settings.model_config, "env_file": None}; get_settings.cache_clear()
from fastapi.testclient import TestClient
from app.main import app

QUERIES = ["Хочу прогуляться 30–60 минут", "Хочу тихое место с кофе и розеткой", "Еду с ребёнком — площадка или музей с интерактивами",
           "Я турист, у меня 2 часа, что посмотреть поблизости?", "Ищу необычную ночную активность", "Хочу что-то необычное на 1–2 часа, пешком",
           "Где поесть рядом?", "Хочу в музей", "Погулять в парке", "Романтическое свидание вечером", "Идёт дождь, что поделать рядом",
           "Хочу провести время бесплатно", "Где лучший вид на город?", "Хочу кофе", "Куда сходить с друзьями вечером", "Что посмотреть за час"]
STARTS = [{"landmark": k} for k in ("baiterek", "khan_shatyr", "mega_silk_way", "expo", "nurly_zhol", "astana_1", "ak_orda", "keruen")] + \
         [{"location": {"lat": 51.169, "lon": 71.436}}, {"location": {"lat": 51.155, "lon": 71.415}}, {"location": {"lat": 51.108, "lon": 71.43}}]
TIMES = ["2026-10-20T14:00:00+05:00", "2026-10-20T19:30:00+05:00"]
seen, where = collections.Counter(), collections.defaultdict(set)
with TestClient(app) as cl:
    for st in STARTS:
        for now in TIMES:
            for q in QUERIES:
                d = cl.post("/api/recommend", json={"query": q, "lang": "ru", "now": now, **st}).json()
                for r in d.get("recommendations", []):
                    seen[r["poi_id"]] += 1; where[r["poi_id"]].add(q[:20])
            ideas = cl.post("/api/routes/ideas", json={"lang": "ru", "now": now, **st}).json().get("ideas", [])
            for i in ideas:
                for r in i["response"]["recommendations"]:
                    seen[r["poi_id"]] += 1
pois = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(OUT, "..", "..", "processed", "pois.jsonl"))}
extra = None
top = []
for pid, n in seen.most_common(170):
    p = pois.get(pid)
    if not p:
        continue
    real_desc = bool(p.get("description")) and p.get("description_source") in ("wikipedia", "wikidata", "osm")
    top.append({"poi_id": pid, "name": p["name"], "names": p.get("names", {}), "category": p["category"], "lat": p["lat"], "lon": p["lon"],
                "address": p.get("address"), "website": p.get("website"), "phone": p.get("phone"), "wikidata": p.get("wikidata"),
                "has_description": real_desc, "description_source": p.get("description_source"), "opening_hours": p.get("opening_hours"),
                "hits": n})
json.dump(top[:150], open(OUT + "/top_places.json", "w"), ensure_ascii=False, indent=1)
print("requests:", len(STARTS) * len(TIMES) * len(QUERIES), "distinct places recommended:", len(seen))
t = top[:150]
print("top150: with real description", sum(x["has_description"] for x in t), "| with hours", sum(bool(x["opening_hours"]) for x in t),
      "| with website", sum(bool(x["website"]) for x in t))
print(collections.Counter(x["category"] for x in t).most_common(12))
print([ (x["name"], x["hits"]) for x in t[:15]])
