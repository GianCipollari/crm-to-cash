PY ?= python

.PHONY: install test preview seed seed-hubspot seed-stripe daily clean

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

clean:        ## delete local outputs and load state (does NOT delete remote data)
	rm -rf out
