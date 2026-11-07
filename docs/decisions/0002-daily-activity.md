# ADR 0002: Daily activity after the seed

**Status:** accepted · **Date:** 2026-11-07

## Context

The seed is a static snapshot that ends on 2026-10-31. An incremental extractor needs data
that keeps changing, otherwise there is nothing new to pick up and incremental logic cannot
be demonstrated or tested.

## Decisions

1. **A `daily` command simulates one day, or a range of days, after the seed.** Each day it
   adds 2-5 contacts and 1-3 deals, moves about 3% of open deals one stage forward (closing
   them from "contract sent"), invoices deals won after the seed, and pays open invoices
   around their due date.

2. **Stateless: it reads what it needs from the APIs.** It does not depend on the local state
   files from the seed, so it can run on a fresh GitHub Actions runner. HubSpot records are
   found by the unique `external_id` property, Stripe records with the Search API.

3. **Deterministic and idempotent per day.** New records use day-based ids (`CON-D20261107-01`,
   `DEAL-D20261107-01`, `INV-DEAL-...`). Every decision comes from a seeded RNG or a stable
   hash of (record id, day). A deal moved today is stamped in `sim_last_moved` and is not moved
   again on a re-run. Stripe calls also send idempotency keys, which covers the short delay of
   Stripe's search index.

4. **Clean activity: no new anomalies.** The seed's manifest stays the single ground truth.
   The planted unpaid and partial invoices are recomputed from the seed (the build is
   deterministic) and are never paid by the daily job.

5. **Business dates are simulated, not the run time.** A payment due on a day the job did not
   run is recorded with its simulated date in metadata (`paid_at`), so the result does not
   depend on how often the job runs. That also produces late-arriving data, which the
   incremental extractor must handle.

## Consequences

- One day costs roughly 10-15 HubSpot calls and a handful of Stripe calls.
- Running the job keeps the HubSpot developer test account active (it expires after 90 days
  without API calls).
- The extractor must use modification timestamps, not creation dates, to catch stage moves
  and invoice payments.
