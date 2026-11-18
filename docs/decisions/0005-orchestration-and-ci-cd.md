# ADR 0005: Orchestration and CI/CD with GitHub Actions

**Status:** accepted · **Date:** 2026-11-18

## Context

The pipeline must run every day without anyone's computer, every change must be checked
before it reaches `main`, and a recruiter should be able to see the models without
installing anything. Airflow was left for a later project (it does not run well on the
development machine), and the project must stay free.

## Decisions

1. **GitHub Actions is the orchestrator.** `daily_pipeline.yml` runs once a day (06:17
   Buenos Aires, off the hour to avoid queue peaks) and on demand: simulate the day, extract
   incrementally, `dbt build`, `dbt source freshness`. The steps are sequential and the whole
   run takes a few minutes, which a scheduler with retries and dependencies (Airflow) would
   not improve at this size. A `concurrency` group prevents two runs writing the same data.

2. **The DuckDB warehouse is carried between runs with the Actions cache.** Each run restores
   the latest saved file and saves a new one, even when a dbt test fails, so extracted data
   is never lost. The first run, with no cache, does a full extraction.

3. **CI runs the whole dbt project on fixtures, never on real data.** `generator.cli fixtures`
   writes raw tables with the same JSON shape the extractor stores, built from the seed. Pull
   requests need no secrets, the build is reproducible (`as_of_date` fixed to 2026-11-01) and
   the ground-truth tests check the full chain from raw to marts on every change.

4. **Delivery on every merge to `main`.** `cd.yml` publishes the Docker image to GitHub
   Container Registry (`latest` and the commit SHA). `docs.yml` builds the dbt docs on the
   fixtures and publishes them to GitHub Pages.

5. **Secrets live only in GitHub Secrets** (`HUBSPOT_TOKEN`, `STRIPE_TEST_KEY`) and in a local
   `.env` excluded from Git. Workflows read them as environment variables; logs mask them.

## Consequences

- The project runs daily at no cost, and the HubSpot test account stays active.
- The Actions cache expires after 7 days without use; if the pipeline stops for longer, the
  next run simply does a full extraction again.
- A secret pasted with a trailing space or line break breaks the API calls (seen during
  setup: "Invalid leading whitespace ... in header value"). Paste only the value.
- Moving to Airflow later means wrapping the same commands in tasks: the steps are already
  separate, idempotent commands.
