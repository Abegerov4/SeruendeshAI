"""Place names in Russian, Kazakh and English (`python -m pipeline.place_names`).

Open data names a place in one language (OSM `name` is Kazakh, Russian or a Latin brand) and only about a
quarter of the places carry name:ru / name:kk / name:en. The model translates the missing ones in batches;
names the map already has always win. Brands keep their spelling, landmarks get their official names.
Every answer is checked before it is kept: the right script for the language, a sane length, the id it
was asked about. Output: data/processed/place_names.json {poi_id: {ru, kk, en}}; the API applies it at load
(app/store.py) and shows the card in the language the user picked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys

os.environ.setdefault("LLM_TIMEOUT_S", "120")  # a batch of names takes longer than one chat answer

from pydantic import BaseModel  # noqa: E402

from app.categories import label  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm import parse  # noqa: E402
from app.paths import PROCESSED_DIR  # noqa: E402

log = logging.getLogger("pipeline.place_names")
OUT_FILE = PROCESSED_DIR / "place_names.json"
DESC_FILE = PROCESSED_DIR / "place_descriptions_kk.json"  # researched descriptions (place_facts) in Kazakh
LANGS = ("ru", "kk", "en")
BATCH = 60
CYR = re.compile(r"[а-яёәғқңөұүһі]", re.I)
KK_ONLY = re.compile(r"[әғқңөұүһі]", re.I)

SYSTEM = """You translate names of places in Astana, Kazakhstan, for a city guide. For every place give its name
in Russian (ru), Kazakh in Cyrillic (kk) and English (en).
- Brands, chains and names written in Latin letters keep their exact spelling in every language
  (Starbucks, Coffee BOOM, Line Brew, walk.cafe, Mega Silk Way); translate only the generic words around them
  («Кофейня «София»» -> en "Sofia coffee house", kk "«София» кофеханасы").
- Landmarks get their official names: Байтерек / Бәйтерек / Baiterek; Хан Шатыр / Хан Шатыр / Khan Shatyr;
  Мечеть Хазрет Султан / Әзірет Сұлтан мешіті / Hazrat Sultan Mosque; Дворец мира и согласия /
  Бейбітшілік және келісім сарайы / Palace of Peace and Reconciliation.
- Names of cafés, restaurants, bars and shops are brands even in Cyrillic: keep them as written in ru and kk and
  transliterate them in en (Дракон -> Drakon, Тануки -> Tanuki).
- Descriptive names are translated fully: a Kazakh name gets a real Russian translation in ru
  (Олимпиада сақиналары -> Олимпийские кольца), a Russian one a real Kazakh translation in kk.
- Personal names are transliterated, not translated (Абу Насыр аль-Фараби / Әбу Насыр әл-Фараби / Abu Nasr al-Farabi).
- Kazakh uses Kazakh letters (ә ғ қ ң ө ұ ү һ і) where the language needs them.
- Never add facts, addresses or quotes that are not in the name. If you are not sure, repeat the original name.
Return every id you were given, once."""


class Name(BaseModel):
    id: str
    ru: str
    kk: str
    en: str


class Names(BaseModel):
    items: list[Name]


def valid(lang: str, text: str, original: str) -> bool:
    """The right script for the language, about the right length (a brand kept as written is always fine)."""
    text = text.strip()
    if not text or len(text) > len(original) * 2.5 + 25:
        return False
    if text == original.strip():
        return True
    if lang == "en":
        return not CYR.search(text)
    if lang == "ru" and KK_ONLY.search(text) and not KK_ONLY.search(original):
        return False  # «Нур Әлем» is Kazakh spelling, not Russian
    if not CYR.search(original):  # a Latin brand may stay Latin in ru/kk
        return True
    return bool(CYR.search(text))


async def translate(batch: list[dict], models: list[str]) -> dict[str, dict]:
    prompt = json.dumps([{"id": p["id"], "name": p["name"], "kind": label(p["category"], "en"),
                          "known": {k: v for k, v in (p.get("names") or {}).items() if k in LANGS and v}} for p in batch],
                        ensure_ascii=False)
    out, _, _ = await parse(Names, SYSTEM, prompt, models=models, timeout_s=240, max_output_tokens=12000)
    by_id = {p["id"]: p for p in batch}
    kept: dict[str, dict] = {}
    for item in (out.items if out else []):
        p = by_id.get(item.id)
        if p is None:
            continue
        names = {lang: getattr(item, lang).strip() for lang in LANGS if valid(lang, getattr(item, lang), p["name"])}
        if names:
            kept[p["id"]] = names
    return kept


DESC_SYSTEM = """Translate short descriptions of places in Astana from Russian into Kazakh (Cyrillic, with Kazakh
letters). Keep every fact exactly as given: names, numbers, years. Add nothing. Return every id once."""


class Text(BaseModel):
    id: str
    kk: str


class Texts(BaseModel):
    items: list[Text]


async def translate_descriptions(models: list[str]) -> None:
    """The researched descriptions exist in Russian and English; the Kazakh card gets its own text too."""
    facts = json.loads((PROCESSED_DIR / "place_facts.json").read_text())
    done = json.loads(DESC_FILE.read_text()) if DESC_FILE.exists() else {}
    todo = [{"id": k, "ru": f["description_ru"]} for k, f in facts.items() if f.get("description_ru") and k not in done]
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        out, _, _ = await parse(Texts, DESC_SYSTEM, json.dumps(batch, ensure_ascii=False), models=models, timeout_s=240,
                                max_output_tokens=12000)
        src = {b["id"]: b["ru"] for b in batch}
        for item in (out.items if out else []):
            text = item.kk.strip()
            # Kazakh script, about the same length, the same numbers as the Russian text
            if item.id in src and KK_ONLY.search(text) and 0.5 <= len(text) / len(src[item.id]) <= 1.8 \
                    and set(re.findall(r"\d+", text)) == set(re.findall(r"\d+", src[item.id])):
                done[item.id] = text
    DESC_FILE.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    log.info("kazakh descriptions: %d of %d", len(done), len(todo) + len(done) - len([1 for t in todo if t["id"] in done]))


async def run(limit: int | None) -> None:
    s = get_settings()
    pois = [json.loads(line) for line in (PROCESSED_DIR / "pois.jsonl").open(encoding="utf-8") if line.strip()]
    done = json.loads(OUT_FILE.read_text()) if OUT_FILE.exists() else {}
    # auto-labelled squares and playgrounds keep the labels pipeline.build gave them in all three languages
    todo = [p for p in pois if not p.get("name_auto") and p["id"] not in done
            and any(not (p.get("names") or {}).get(lang) for lang in LANGS)][:limit]
    log.info("%d places need names (%d already translated)", len(todo), len(done))
    sem = asyncio.Semaphore(4)

    async def one(batch):
        async with sem:
            return await translate(batch, [s.llm_parse_model])

    for res in await asyncio.gather(*(one(todo[i:i + BATCH]) for i in range(0, len(todo), BATCH))):
        done.update(res)
    # the curated landmarks («Старт: Байтерек», «Считаю от …», a photo guess) are named in all three languages too
    gaz = json.loads((PROCESSED_DIR / "gazetteer.json").read_text())
    marks = [{"id": f"landmark:{g['landmark_key']}", "name": g["name"], "category": "landmark", "names": {}}
             for g in gaz if g.get("landmark_key") and f"landmark:{g['landmark_key']}" not in done]
    if marks:
        done.update(await translate(marks, [s.llm_parse_model]))
    OUT_FILE.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    log.info("place names: %d places in file", len(done))
    await translate_descriptions([s.llm_parse_model])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else None))
