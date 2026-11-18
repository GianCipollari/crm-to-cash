# ADR 0006: Snowflake as a second target and Evidence for the dashboard

**Status:** accepted · **Date:** 2026-11-18

## Context

DuckDB is ideal for development and the daily pipeline, but most companies run dbt on a
cloud warehouse, and Snowflake is one of the most requested in job postings. The project
also needed a public dashboard that stays current without manual work. Snowflake is used
through its free 30-day trial, so whatever it proves must be recorded before it expires.

## Decisions

1. **One dbt project, two targets.** `dev` (DuckDB, default) and `snowflake`
   (`dbt build --target snowflake`). The models are identical: every function that differs
   between the two engines (JSON access, timestamps, regular expressions, month labels,
   day-of-week, the calendar generator) lives in a macro with `adapter.dispatch`, which
   picks `snowflake__<macro>` or `default__<macro>` by target. Other differences were
   removed with portable SQL (quoted intervals, `translate` instead of `strip_accents`,
   `min_by` instead of `arg_min`).

2. **Raw data reaches Snowflake through a small loader**, `extractor.load_snowflake`, which
   copies the raw tables from DuckDB to `CRM_TO_CASH.RAW`. The extractor stays unchanged
   and the two warehouses read exactly the same raw records. Sources point to `RAW` or
   `main` depending on the target.

3. **Key-pair authentication for a service user** (`dbt_service`), no password. The private
   key never leaves the developer's machine (`out/keys/`, ignored by Git).

4. **Cost guardrails:** an XS warehouse that suspends after 60 seconds idle and a resource
   monitor that suspends it at 20 credits.

5. **Results are verified across warehouses.** `extractor.compare_warehouses` runs the same
   summary queries on both and fails on any difference.

6. **Evidence for the dashboard.** Pages are Markdown with SQL over the marts; the build
   produces a static site. It is rebuilt by the daily pipeline from that day's warehouse
   and published to GitHub Pages together with the dbt docs (dashboard at the root, docs at
   `/docs`). One workflow publishes the whole site, because two workflows deploying to
   GitHub Pages would overwrite each other; `docs.yml` was retired. CI builds the dashboard
   on the fixtures in every pull request, so a broken page fails the PR, not the daily run.
   Streamlit was discarded because it would need the data exported to its own host;
   Tableau Public because refreshing it is manual.

## Results (2026-11-18)

| Measure | Value |
| --- | --- |
| `dbt build --target snowflake` | 91 of 91 nodes passed, 36 s |
| Snowflake credits used (setup, load and builds) | 0.1079 credits |
| DuckDB vs Snowflake comparison | 23 of 23 figures match |

## Consequences

- The daily pipeline keeps running on DuckDB for free; Snowflake runs on demand. When the
  trial ends, the `snowflake` target simply stops being used: nothing else depends on it.
- New SQL must avoid engine-specific functions or wrap them in a dispatched macro; the
  Snowflake build is the check.
- The Evidence project is not committed in full: CI and the daily pipeline start from the
  official template and add `dashboard/pages`, `dashboard/sources` and the config. This
  keeps the repository small, at the cost of depending on that template being available.
