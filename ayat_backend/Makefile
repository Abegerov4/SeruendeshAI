.PHONY: setup api test eval eval-llm data data-build embed graph events contract docker

AYAT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UV := uv run --project $(AYAT_DIR) --directory $(AYAT_DIR)/..
CAP := systemd-run --user --scope -p MemoryMax=2500M -p MemorySwapMax=0 --quiet

setup:            ## install backend deps (runtime + pipeline + dev)
	uv sync --all-groups

api:              ## run the API on :8000
	$(UV) uvicorn ayat_backend.app.main:app --port 8000 --reload

test:             ## unit + contract tests (no API key needed)
	$(UV) pytest -c pytest.ini ayat_backend/tests -q

eval:             ## scenario evaluation in template mode
	$(UV) python -m ayat_backend.eval.run_eval --no-llm

eval-llm:         ## scenario evaluation with the LLM + LLM-as-judge
	$(UV) python -m ayat_backend.eval.run_eval --judge

data:             ## full automated collection: fetch -> build -> graph -> embed -> events
	$(UV) python -m ayat_backend.pipeline.cli all

data-build:       ## rebuild processed data from cached raw downloads
	$(UV) python -m ayat_backend.pipeline.cli build

embed:
	$(UV) python -m ayat_backend.pipeline.cli embed --model e5-large

graph:
	$(UV) python -m ayat_backend.pipeline.cli graph

events:
	$(UV) python -m ayat_backend.pipeline.cli events

contract:         ## export OpenAPI + example responses for the frontend
	$(UV) python -m ayat_backend.scripts.export_contract

docker:
	docker compose up --build
