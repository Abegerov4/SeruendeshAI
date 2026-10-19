"""All tests run offline: no LLM, no embeddings model, no live weather (set before `app` is imported)."""
import os

os.environ["LLM_ENABLED"] = "false"
os.environ.setdefault("EMBED_MODEL", "off")
os.environ["WEATHER_ENABLED"] = "false"
os.environ.setdefault("RATE_LIMIT_PER_MIN", "1000")  # one test client makes many requests per minute
os.environ.setdefault("PHOTO_RATE_LIMIT_PER_MIN", "1000")
os.environ.setdefault("MCP_RATE_LIMIT_PER_MIN", "1000")
