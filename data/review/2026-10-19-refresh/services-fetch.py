"""Public, unauthenticated, no-LLM evidence capture used for this refresh."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import httpx

OUT = Path(__file__).resolve().parent
SOURCES = {
    "redbus-routes": "https://redbus.kz/ru/marshruty/",
    "redbus-faq": "https://redbus.kz/ru/faq/",
    "visit-redbus": "https://www.visitastana.kz/ru/exkursion/redbus/",
    "river-parks": "https://www.visitastana.kz/ru/exkursion/teplokhod/",
    "river-necklace": "https://www.visitastana.kz/ru/exkursion/goluboe-ozherele-stolitsy-/",
    "gold-museum": "https://www.visitastana.kz/ru/exkursion/ekskursiya-po-zalam-zoloto/",
    "mosque": "https://www.visitastana.kz/ru/exkursion/ekskursiya-po-mecheti-n-rs-ltan-/",
    "opera": "https://www.visitastana.kz/ru/exkursion/teatralnyy-urok-v-teatre-astana-opera/",
    "tamyr": "https://www.visitastana.kz/ru/exkursion/chaynaya-tseremoniya-v-etnotsentre-tamyr/",
    "murals": "https://www.visitastana.kz/ru/exkursion/ekskursiya-po-muralam/",
    "walk-nurzhol": "https://www.visitastana.kz/ru/exkursion/ob-astane-s-interesom-i-lyubovyu/",
}


def fetch(item):
    key, url = item
    checked_at = datetime.now(timezone.utc).isoformat()
    result = {"key": key, "source_url": url, "checked_at": checked_at}
    try:
        response = httpx.get(url, timeout=40, follow_redirects=True, headers={"User-Agent": "AstanaCatalogEvidence/1.0 (public source verification)"})
        result.update(status=response.status_code, final_url=str(response.url),
                      response_sha256=hashlib.sha256(response.content).hexdigest())
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        result["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        main = soup.find("main") or soup
        for node in main.select("script,style,nav,header,footer"):
            node.decompose()
        text = " ".join(main.get_text(" ", strip=True).split())
        if "visitastana.kz" in url:
            text = text.split("Рекомендуем вам")[0]
        else:
            # The dated schedule is a footer modal; preserve whole page text too.
            full_soup = BeautifulSoup(response.text, "html.parser")
            for node in full_soup.select("script,style"):
                node.decompose()
            result["full_text"] = " ".join(full_soup.get_text(" ", strip=True).split())
        result["text"] = text
        result["links"] = [{"text": a.get_text(" ", strip=True), "url": a.get("href")}
                           for a in soup.select("a[href]") if any(x in a.get("href", "")
                           for x in ["2gis", "instagram", "tel:", "mailto:", "astanaopera", "nmrk", "hazretsultan"])]
    except Exception as exc:
        result["error"] = str(exc)
    path = OUT / f"services-source-{key}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key not in {"text", "full_text", "links"}}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifest = list(pool.map(fetch, SOURCES.items()))
    (OUT / "services-source-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
