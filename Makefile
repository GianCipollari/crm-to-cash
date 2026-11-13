PY ?= python

.PHONY: install test preview seed seed-hubspot seed-stripe daily extract extract-full docker-build docker-extract docker-daily clean

install:        ## install Python dependencies
	$(PY) -m pip install -r requirements.txt

test:           ## run the unit tests (no network needed)
	$(PY) -m pytest -q

preview:        ## build the synthetic company and export CSVs to out/dataset, no API calls
	$(PY) -m generator.cli seed --dry-run

seed:           ## load HubSpot and Stripe (needs .env)
	$(PY) -m generator.cli seed --target all

seed-hubspot:
	$(PY) -m generator.cli seed --target hubspot

seed-stripe:
	$(PY) -m generator.cli seed --target stripe

daily:          ## simulate today's activity in HubSpot and Stripe (needs .env)
	$(PY) -m generator.cli daily

extract:        ## incremental extraction into out/warehouse.duckdb (needs .env)
	$(PY) -m extractor.cli

extract-full:   ## re-read everything from the sources (still idempotent)
	$(PY) -m extractor.cli --full

docker-build:   ## build the Docker image
	docker compose build

docker-extract: ## run the incremental extraction inside Docker
	docker compose run --rm app extractor.cli

docker-daily:   ## simulate today's activity inside Docker
	docker compose run --rm app generator.cli daily

clean:        ## delete local outputs and load state (does NOT delete remote data)
	rm -rf out
