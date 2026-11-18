# CRM-to-Cash

[![ci](https://github.com/GianCipollari/crm-to-cash/actions/workflows/ci.yml/badge.svg)](https://github.com/GianCipollari/crm-to-cash/actions/workflows/ci.yml)
[![daily-pipeline](https://github.com/GianCipollari/crm-to-cash/actions/workflows/daily_pipeline.yml/badge.svg)](https://github.com/GianCipollari/crm-to-cash/actions/workflows/daily_pipeline.yml)
[![dbt docs](https://img.shields.io/badge/dbt_docs-lineage-orange)](https://giancipollari.github.io/crm-to-cash/)

> Sales says a deal is closed-won. Finance says the money never arrived. This pipeline finds
> where the gap comes from.

**Status: week 4 of 6.** The pipeline runs end to end every day on GitHub Actions: synthetic
activity, incremental extraction from HubSpot and Stripe, dbt models up to the marts, and
tests that check every planted data problem is detected. Next: Snowflake and a dashboard.

## The business problem

In most B2B companies the CRM (what sales reports) and the billing system (what finance
collects) never fully agree. CRM-to-Cash joins HubSpot and Stripe data to answer:

1. What share of closed-won revenue is actually invoiced and collected, by month and by rep?
2. Where is the gap: deals never invoiced, unpaid or partial invoices, unrecorded discounts,
   duplicate deals, refunds?
3. Which lead sources bring customers who actually pay?
4. How reliable is the CRM data?

## How it answers

| Question | dbt mart |
| --- | --- |
| 1. Share of won revenue invoiced and collected | `fct_deal_reconciliation` (one row per won deal, with a `reconciliation_status`) |
| 2. Where the gap comes from | `fct_deal_reconciliation` and `mart_data_quality_issues` |
| 3. Lead sources that bring paying customers | `fct_lead_funnel` (contact -> deal -> won -> paid) |
| 4. How reliable the CRM is | `mart_data_quality_issues` |

Every model, column, test and the lineage graph are browsable in the
[dbt docs](https://giancipollari.github.io/crm-to-cash/).

## Architecture

```
Generator (Python) -> HubSpot + Stripe (test) -> Extractor (Docker) -> raw
   -> dbt: staging -> intermediate -> marts -> dashboard + dbt docs
Orchestrated by GitHub Actions: daily schedule + CI on every pull request
Warehouse: DuckDB for development, Snowflake for production
```

## Week 1: synthetic data generator

A fictional LatAm B2B SaaS company ("Contable Cloud") over 12 months: 200 companies,
1,000 contacts and 500 deals in HubSpot, with matching customers, invoices and payments in
Stripe. Data problems are planted on purpose, and every one of them is recorded in a
ground-truth manifest so the pipeline's detection can be tested later.

| Planted problem | What it simulates |
| --- | --- |
| `missing_invoice` | Won deal that was never invoiced |
| `unpaid_invoice` | Overdue invoice with no payment (more likely for some lead sources) |
| `partial_payment` | Only 30-80% collected |
| `amount_mismatch` | Discount agreed but not recorded in the CRM |
| `duplicate_deal` | Two reps log the same sale |
| `late_stage_update` | CRM close date later than the payment |
| `refund` | Paid, then refunded |
| `name_variant` | "Atlántico Farma Ltda." in the CRM vs "ATLANTICO FARMA LTDA" in billing |
| `missing_external_id` | Billing record without the CRM id, so a fuzzy match is needed |

Engineering choices: deterministic builds (seeded), batch API calls sized for the free tier,
client-side rate limiting with retries on 429/5xx, resumable loads, Stripe idempotency keys,
and a guard that refuses live Stripe keys. Details in
[ADR 0001](docs/decisions/0001-synthetic-data.md).

### Daily activity

`python -m generator.cli daily` keeps the company alive after the seed: new contacts and
deals, stage moves, invoices for newly won deals and payments around their due date. It is
stateless, deterministic and idempotent per day, and plants no new anomalies, so the seed's
manifest stays the ground truth. Use `--from 2026-11-01` to catch up a range of days. Details
in [ADR 0002](docs/decisions/0002-daily-activity.md).

## Quick start

```bash
make install
make test        # offline unit tests
make preview     # builds the company and writes CSVs to out/dataset/ (no accounts needed)
```

To load the data into HubSpot and Stripe, follow [docs/setup_accounts.md](docs/setup_accounts.md).

### Transformations (dbt)

```bash
cd dbt
dbt deps
dbt build      # staging -> intermediate, snapshot, all tests
```
Matching rules are explained in [ADR 0004](docs/decisions/0004-matching-strategy.md).

### Automation (GitHub Actions)

| Workflow | When | What |
| --- | --- | --- |
| `ci` | every pull request and push to `main` | Python tests; dbt build on fixtures built from the seed (no secrets), including the ground-truth tests; Docker build |
| `daily-pipeline` | every day 06:17 Buenos Aires, or on demand | simulate the day, extract, `dbt build`, source freshness; the DuckDB warehouse is kept in the Actions cache |
| `cd` | merge to `main` | publish the Docker image to GitHub Container Registry |
| `docs` | merge to `main` | publish the dbt docs to GitHub Pages |

Design and trade-offs (why not Airflow, why fixtures in CI) in
[ADR 0005](docs/decisions/0005-orchestration-and-ci-cd.md). To reproduce CI locally: `make ci-dbt`.

### With Docker

One image runs every Python module; keys come from `.env` at run time and the DuckDB
warehouse stays in `out/` on the host.

```bash
docker compose build
docker compose run --rm app                                   # incremental extraction
docker compose run --rm app extractor.cli --source stripe     # one source
docker compose run --rm app generator.cli daily               # today's activity
```

## Repository layout

```
generator/     config.yaml, model.py (dataset build), anomalies.py, daily.py (daily activity),
               hubspot_loader.py, stripe_loader.py, http.py (rate-limited client), state.py
extractor/     hubspot.py, stripe.py (incremental extraction), storage.py (raw tables + cursors), cli.py
dbt/           staging, intermediate, marts, snapshots, seeds (anomaly manifest), tests, unit tests
tests/         unit tests, no network needed
docs/          account setup and architecture decisions (ADRs)
.github/       workflows: ci, daily-pipeline, cd (image), docs (GitHub Pages)
```

## Roadmap

- [x] Week 1: repo, synthetic data generator, loaders, tests
- [x] Week 2: daily activity simulator, HubSpot and Stripe extractors, Docker
- [x] Week 3: dbt staging and intermediate models, customer matching, deal snapshot
- [x] Week 4: dbt marts, ground-truth tests, CI/CD, daily pipeline, published docs
- [ ] Week 5: Snowflake and dashboard
- [ ] Week 6: documentation and polish
