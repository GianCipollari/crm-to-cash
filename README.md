# CRM-to-Cash

> Sales says a deal is closed-won. Finance says the money never arrived. This pipeline finds
> where the gap comes from.

**Status: week 2 of 6.** The synthetic data generator and its daily activity simulator are
done; the incremental extractor reads HubSpot into DuckDB, Stripe is next (see the roadmap below).

## The business problem

In most B2B companies the CRM (what sales reports) and the billing system (what finance
collects) never fully agree. CRM-to-Cash joins HubSpot and Stripe data to answer:

1. What share of closed-won revenue is actually invoiced and collected, by month and by rep?
2. Where is the gap: deals never invoiced, unpaid or partial invoices, unrecorded discounts,
   duplicate deals, refunds?
3. Which lead sources bring customers who actually pay?
4. How reliable is the CRM data?

## Planned architecture

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

## Repository layout

```
generator/     config.yaml, model.py (dataset build), anomalies.py, daily.py (daily activity),
               hubspot_loader.py, stripe_loader.py, http.py (rate-limited client), state.py
extractor/     hubspot.py (incremental extraction), storage.py (raw tables + cursors), cli.py
tests/         unit tests, no network needed
docs/          account setup and architecture decisions (ADRs)
.github/       CI: tests + generator smoke test on every pull request
```

## Roadmap

- [x] Week 1: repo, synthetic data generator, loaders, tests
- [ ] Week 2: daily activity simulator (done), HubSpot extractor (done), Stripe extractor, Docker
- [ ] Week 3: dbt staging and intermediate models, customer matching
- [ ] Week 4: dbt marts, tests and CI/CD
- [ ] Week 5: Snowflake and dashboard
- [ ] Week 6: documentation and polish
