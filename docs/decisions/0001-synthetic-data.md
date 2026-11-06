# ADR 0001: Synthetic data and how it is loaded

**Status:** accepted · **Date:** 2026-11-06

## Context

The project needs realistic CRM and billing data with known problems in it, but no real
company data can be used. HubSpot and Stripe also impose constraints on what an API client
can write.

## Decisions

1. **A deterministic generator builds the whole company in memory first.**
   Same config + seed = same dataset. The build is pure Python with no API access, so it can
   be unit tested and previewed (`make preview`) before anything is loaded.

2. **Every planted problem is written to a ground-truth manifest** (`anomalies.csv`).
   Later, dbt tests compare what the pipeline detects against what was planted.

3. **Original business dates travel in custom fields.** HubSpot stamps `createdate` with the
   load time and Stripe stamps every object with its real creation time. The simulated dates
   therefore live in HubSpot custom date properties (`source_created_date`,
   `deal_created_date`, plus the native `closedate`) and in Stripe metadata (`invoice_date`,
   `due_date`, `paid_at`, `refunded_at`). The dbt staging layer uses these fields.

4. **Sales reps are a custom property, not HubSpot owners.** Owners must be real users of
   the portal; a `sales_rep` enumeration keeps the analysis by rep without fake users.

5. **Volumes are sized for the free tiers.** 200 companies, 1,000 contacts and 500 deals load
   in about 25 HubSpot batch calls (100 records each). The client also spaces requests and
   retries on HTTP 429 and 5xx with backoff, honouring `Retry-After`.

6. **Loads are resumable and idempotent.** A local state file maps our ids to remote ids and
   is saved after every batch or invoice. Stripe create calls also send an `Idempotency-Key`
   derived from our id, so a retry never creates or charges twice.

7. **Stripe is called through plain REST with a pinned API version** (`2024-06-20`), so
   behaviour does not change when Stripe ships a new version. A partial payment is a separate
   PaymentIntent that references the invoice in metadata, and the invoice stays open.

## Consequences

- Staging models must read dates from custom fields, not from system timestamps. That is a
  realistic situation worth explaining in interviews.
- Deals closing in the last 10 days of the period stay open, so every won deal has had time
  to be invoiced and a missing invoice is always a real anomaly.
- Open invoices that are not yet due are normal receivables, not anomalies; the
  reconciliation must separate "not yet due" from "overdue".
