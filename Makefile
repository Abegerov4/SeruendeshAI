.PHONY: setup api web test eval eval-llm data data-build embed graph events contract docker deploy

UV := cd backend && uv run
CAP := systemd-run --user --scope -p MemoryMax=2500M -p MemorySwapMax=0 --quiet

setup:            ## install backend deps (runtime + pipeline + dev)
	cd backend && uv sync --all-groups

api:              ## run the API on :8000 (also serves frontend/dist if built)
	$(UV) uvicorn app.main:app --port 8000 --reload

web:              ## frontend dev server on :5173 (proxies /api to :8000)
	cd frontend && npm install && npm run dev

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
	$(UV) python ../scripts/export_contract.py

docker:
	docker compose up --build

deploy:           ## deploy the latest commit of branch ayat to Railway (seruendesh.site)
	bash scripts/deploy_railway.sh
