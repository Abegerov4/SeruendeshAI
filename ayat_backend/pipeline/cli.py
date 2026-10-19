"""Data pipeline CLI.

    uv run --project ayat_backend python -m ayat_backend.pipeline.cli all
    uv run --project ayat_backend python -m ayat_backend.pipeline.cli build
"""
from __future__ import annotations

import json
import logging

import typer

from ayat_backend.app.paths import RAW_DIR

app = typer.Typer(add_completion=False, help="SeruendeshAI data pipeline (automated POI collection for Astana)")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")


@app.command()
def fetch(overture: bool = True):
    """Download raw data: OSM (Overpass), boundary, river, Wikidata, Wikipedia ru/en, Overture."""
    from ayat_backend.pipeline import osm, wiki
    osm.fetch_boundary()
    osm.fetch_pois()
    osm.fetch_context()
    osm.fetch_river()
    osm.fetch_gazetteer_extra()
    wiki.fetch_wikidata()
    wiki.fetch_wikipedia("ru")
    wiki.fetch_wikipedia("en")
    if overture:
        from ayat_backend.pipeline import overture as ov
        ov.extract()


@app.command()
def build(overture: bool = True):
    """Merge cached raw data into data/processed/{pois.jsonl,gazetteer.json,manifest.json}."""
    from ayat_backend.pipeline import osm, wiki
    from ayat_backend.pipeline.build import build as do_build
    ov = None
    if overture:
        from ayat_backend.pipeline import overture as ovm
        ov = ovm.extract()
    m = do_build(osm.fetch_pois(), osm.fetch_context(), osm.fetch_river(), wiki.fetch_wikidata(),
                 {"ru": wiki.fetch_wikipedia("ru"), "en": wiki.fetch_wikipedia("en")}, ov, osm.fetch_gazetteer_extra())
    typer.echo(json.dumps({k: m[k] for k in ("poi_count", "by_source", "with_opening_hours")}, ensure_ascii=False))


@app.command()
def graph(from_pickle: str = typer.Option(None, help="Use an existing osmnx graph pickle instead of Overpass")):
    """Build the walking graph (osmnx, one-off) and export numpy arrays."""
    from ayat_backend.pipeline.graph import build_graph
    typer.echo(build_graph(from_pickle))


@app.command()
def embed(model: str = "e5-large"):
    """Embed POI documents with a local multilingual-e5 model (ONNX, no torch)."""
    from ayat_backend.pipeline.embed import embed_pois
    typer.echo(embed_pois(model))


@app.command()
def events():
    """Collect upcoming Astana events (Ticketon + Sxodim JSON-LD) and link them to POIs."""
    from ayat_backend.pipeline.events import collect_events
    typer.echo(collect_events())


@app.command(name="all")
def run_all(model: str = "e5-large", overture: bool = True, with_graph: bool = True, with_events: bool = True):
    fetch(overture=overture)
    build(overture=overture)
    if with_graph:
        graph()
    embed(model=model)
    if with_events:
        events()


@app.command()
def overture_categories():
    """Show Overture basic_category counts for Astana (to tune the category mapping)."""
    from ayat_backend.pipeline.overture import category_stats
    for k, n in category_stats():
        typer.echo(f"{n:5d}  {k}")


if __name__ == "__main__":
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    app()
