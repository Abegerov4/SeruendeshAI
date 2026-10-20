"""Opening hours from the places' own websites (`python -m pipeline.site_hours`).

For every place without hours that has its own website (map and review services are excluded, see
place_facts.BANNED), the home page and up to three «contacts / about / branches» pages are read, honouring
robots.txt. Hours come from schema.org markup when the site has it, otherwise the model reads the page text.
Nothing is taken on trust:
- the model must return a verbatim quote, and the quote must be found in the page text;
- the hours must parse with the API's own opening_hours parser;
- when a chain's site lists branches with different hours and ours cannot be identified by its address, the
  answer is «not found»; hours for another city are rejected;
- the result goes through pipeline.place_facts like every researched fact (source URL, date).
Output: data/sources/place_research/site_hours_<date>_output.json, then
    python -m pipeline.place_facts data/sources/place_research/*_output.json
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.hours import _parse
from app.llm import parse
from app.paths import DATA_DIR, PROCESSED_DIR
from pipeline.place_facts import BANNED

log = logging.getLogger("pipeline.site_hours")
TODAY = dt.date.today().isoformat()
OUT = DATA_DIR / "sources" / "place_research" / f"site_hours_{TODAY}_output.json"
UA = "SeruendeshAI/0.1 (hackathon walking assistant; opening hours from venues' own sites; https://seruendesh.site)"
SKIP_HOSTS = re.compile(r"wa\.me|whatsapp|t\.me|telegram|linktr\.ee", re.I)
LINK_HINT = re.compile(r"контакт|contact|about|о-нас|о нас|адрес|филиал|branch|filial|restoran|ресторан|режим|time|hours|location|where", re.I)
TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b|круглосуточно|24/7|24 часа|тәулік бойы", re.I)
CHAIN_PAGES, SITE_LIMIT, LLM_LIMIT = 3, 8, 6


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.links, self.ld, self._skip, self._ld = [], [], [], 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
            self._ld = tag == "script" and (a.get("type") or "").lower() == "application/ld+json"
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
            self._ld = False

    def handle_data(self, data):
        if self._ld:
            self.ld.append(data)
        elif not self._skip:
            self.parts.append(data)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-").replace("\xa0", " ")).strip().lower()


def _snippets(text: str, limit: int = 5000) -> str:
    """Only the parts of the page around times and «режим работы»-like words go to the model."""
    out, used = [], 0
    for m in TIME.finditer(text):
        a, b = max(0, m.start() - 260), min(len(text), m.end() + 260)
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    chunks = []
    for a, b in out:
        chunk = re.sub(r"\s+", " ", text[a:b]).strip()
        if used + len(chunk) > limit:
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n…\n".join(chunks)


def _ld_hours(blobs: list[str]) -> str | None:
    for raw in blobs:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict) and isinstance(obj.get("openingHours"), (str, list)):
                v = obj["openingHours"]
                return "; ".join(v) if isinstance(v, list) else v
    return None


class SiteHours(BaseModel):
    found: bool = Field(description="true only if the page states this venue's (or the whole chain's) regular opening hours")
    opening_hours: str | None = Field(description="OSM opening_hours syntax, e.g. 'Mo-Fr 10:00-22:00; Sa-Su 11:00-23:00' or '24/7'")
    quote: str | None = Field(description="the exact words from the page the hours come from, copied verbatim")
    page_url: str | None = Field(description="the URL (from the list) of the page with the quote")
    scope: str | None = Field(description="'venue' (this address), 'chain' (one schedule for all branches), or 'unclear'")


SYSTEM = """You extract a venue's regular opening hours from its own website, for a walking assistant in Astana.
Return found=false unless the page clearly states regular opening hours for this venue in Astana.
- Copy `quote` verbatim from the page text (the days and times as written). Never invent or normalise the quote.
- If the site lists several branches with different hours, use only the branch whose address matches the given
  address in Astana; if none matches, found=false. One schedule for all branches → scope='chain'.
- Ignore hours of delivery, kitchen, box office, phone/call centre, breakfast or business lunch, and other cities.
- «до последнего гостя», «по записи», seasonal or holiday-only hours → found=false.
- Write opening_hours in OSM syntax: Mo Tu We Th Fr Sa Su, 24-hour times, a range past midnight like 10:00-02:00,
  '24/7' only for «круглосуточно / 24 часа» every day."""


_INSECURE: httpx.AsyncClient | None = None  # many small .kz sites serve broken certificate chains; we only read public pages


async def _get(http: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    for client in (http, _INSECURE):
        if client is None:
            continue
        try:
            r = await client.get(url, timeout=12, follow_redirects=True)
        except httpx.ConnectError:
            continue  # retry once without certificate verification
        except Exception:
            return None
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
            return None
        return str(r.url), r.text[:1_500_000]
    return None


async def _allowed(http: httpx.AsyncClient, url: str, cache: dict) -> bool:
    root = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if root not in cache:
        rp = RobotFileParser()
        try:
            r = await http.get(root + "/robots.txt", timeout=8, follow_redirects=True)
            rp.parse(r.text.splitlines() if r.status_code == 200 and "html" not in r.headers.get("content-type", "") else [])
        except Exception:
            rp.parse([])
        cache[root] = rp
    return cache[root].can_fetch(UA, url)


async def _pages(http, site: str, robots: dict) -> list[tuple[str, str, list[str]]]:
    """[(url, text, json-ld blobs)] for the home page and a few hours-likely internal pages."""
    if not await _allowed(http, site, robots):
        return []
    home = await _get(http, site)
    if not home:
        return []
    url, html = home
    p = _Text(); p.feed(html)
    out = [(url, "".join(p.parts), p.ld)]
    host = urlparse(url).netloc
    seen = {url}
    for href in p.links:
        link = urljoin(url, href.split("#")[0])
        if urlparse(link).netloc != host or link in seen or not LINK_HINT.search(link):
            continue
        seen.add(link)
        if len(out) > CHAIN_PAGES or not await _allowed(http, link, robots):
            break
        if got := await _get(http, link):
            q = _Text(); q.feed(got[1])
            out.append((got[0], "".join(q.parts), q.ld))
    return out


async def research(poi: dict, http, robots, llm_sem, site_sem) -> dict | None:
    async with site_sem:
        pages = await _pages(http, poi["website"], robots)
    if not pages:
        return None
    for url, _, ld in pages:  # structured data first: no model needed
        if (v := _ld_hours(ld)) and _parse(v) is not None:
            return {"poi_id": poi["id"], "name": poi["name"], "opening_hours": v, "hours_source": [url],
                    "hours_note": "schema.org openingHours на сайте места", "confidence": "high", "checked": TODAY}
    corpus = {url: text for url, text, _ in pages}
    body = "\n\n".join(f"PAGE {url}\n{_snippets(text)}" for url, text in corpus.items() if TIME.search(text))
    if not body:
        return None
    user = (f"Venue: {poi['name']} ({poi['category']}), Astana. Address: {poi.get('address') or 'unknown'}.\n"
            f"Pages:\n{body[:9000]}")
    async with llm_sem:
        out, _, _ = await parse(SiteHours, SYSTEM, user, models=get_settings().llm_chain, timeout_s=60, max_output_tokens=400)
    if not out or not out.found or not out.opening_hours or not out.quote or out.scope not in ("venue", "chain"):
        return None
    page = out.page_url if out.page_url in corpus else next((u for u, t in corpus.items() if _norm(out.quote) in _norm(t)), None)
    if not page or len(_norm(out.quote)) < 6 or _norm(out.quote) not in _norm(corpus[page]) or not TIME.search(out.quote):
        log.info("rejected %s: quote not on the page", poi["name"])
        return None
    if _parse(out.opening_hours) is None:
        return None
    return {"poi_id": poi["id"], "name": poi["name"], "opening_hours": out.opening_hours.strip(), "hours_source": [page],
            "hours_note": ("часы сети: " if out.scope == "chain" else "") + out.quote.strip()[:100],
            "confidence": "high" if out.scope == "venue" else "medium", "checked": TODAY}


def _page_key(url: str) -> str:
    u = urlparse(url)
    return u.netloc.lower().removeprefix("www.") + u.path.rstrip("/")


async def main() -> None:
    pois = [json.loads(line) for line in (PROCESSED_DIR / "pois.jsonl").open(encoding="utf-8") if line.strip()]
    facts = json.loads((PROCESSED_DIR / "place_facts.json").read_text()) if (PROCESSED_DIR / "place_facts.json").exists() else {}
    todo = [p for p in pois if not p.get("opening_hours") and not facts.get(p["id"], {}).get("opening_hours")
            and p.get("website") and not BANNED.search(p["website"]) and not SKIP_HOSTS.search(p["website"])]
    log.info("%d places to check on their own sites", len(todo))
    llm_sem, site_sem, robots = asyncio.Semaphore(LLM_LIMIT), asyncio.Semaphore(SITE_LIMIT), {}
    global _INSECURE
    headers = {"User-Agent": UA, "Accept-Language": "ru,kk;q=0.8,en;q=0.5"}
    async with httpx.AsyncClient(headers=headers) as http, httpx.AsyncClient(headers=headers, verify=False) as insecure:
        _INSECURE = insecure
        results = await asyncio.gather(*(research(p, http, robots, llm_sem, site_sem) for p in todo), return_exceptions=True)
    found = [r for r in results if isinstance(r, dict)]
    # one page giving hours to places more than 150 m apart is a group's site listing several venues (or a chain
    # page read as one branch): we cannot tell whose hours they are, so they are dropped
    by_id = {p["id"]: p for p in todo}
    by_page: dict[str, list] = {}
    for r in found:
        by_page.setdefault(_page_key(r["hours_source"][0]), []).append(by_id[r["poi_id"]])
    def one_place(ps):
        return all(abs(a["lat"] - b["lat"]) * 111_000 < 150 and abs(a["lon"] - b["lon"]) * 70_000 < 150 for a in ps for b in ps)
    found = [r for r in found if one_place(by_page[_page_key(r["hours_source"][0])]) or r["confidence"] == "medium"]
    errors = sum(isinstance(r, Exception) for r in results)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1))
    log.info("hours found on own sites: %d of %d (errors %d) -> %s", len(found), len(todo), errors, OUT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
