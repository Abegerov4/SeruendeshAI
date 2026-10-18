.PHONY: setup api test eval eval-llm data data-build embed graph events contract docker

UV := uv run
CAP := systemd-run --user --scope -p MemoryMax=2500M -p MemorySwapMax=0 --quiet

setup:            ## install backend deps (runtime + pipeline + dev)
	uv sync --all-groups

api:              ## run the API on :8000
	$(UV) uvicorn app.main:app --port 8000 --reload

test:             ## unit + contract tests (no API key needed)
	$(UV) pytest -q

eval:             ## scenario evaluation in template mode
	$(UV) python eval/run_eval.py --no-llm

eval-llm:         ## scenario evaluation with the LLM + LLM-as-judge
	$(UV) python eval/run_eval.py --judge

data:             ## full automated collection: fetch -> build -> graph -> embed -> events
	$(UV) python -m pipeline.cli all

data-build:       ## rebuild processed data from cached raw downloads
	$(UV) python -m pipeline.cli build

embed:
	$(UV) python -m pipeline.cli embed --model e5-large

graph:
	$(UV) python -m pipeline.cli graph

events:
	$(UV) python -m pipeline.cli events

contract:         ## export OpenAPI + example responses for the frontend
	$(UV) python scripts/export_contract.py

docker:
	docker compose up --build
