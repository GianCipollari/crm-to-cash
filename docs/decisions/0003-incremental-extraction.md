# ADR 0003: Incremental extraction

**Status:** accepted · **Date:** 2026-11-13

## Context

The extractor runs every day. Re-reading every record each time wastes API calls and hides
whether the pipeline can handle change. HubSpot and Stripe expose change differently.

## Decisions

1. **Raw keeps the latest version of each record**, as the API returned it (JSON), with its
   source version (`updated_at`) and load time (`_loaded_at`). History is left to dbt
   snapshots. A record whose version did not change is not written again, so every run is
   idempotent.

2. **One cursor per stream** in `_extract_state`. It moves forward only after the records are
   stored; a failed run is simply repeated.

3. **HubSpot: Search API filtered by modification time** (`hs_lastmodifieddate`, or
   `lastmodifieddate` for contacts) with `GTE` the cursor, sorted ascending. `GTE` re-reads the
   boundary record (it comes back as unchanged) instead of risking a record modified in the
   same millisecond being skipped. Associations are fetched for the extracted records.

4. **Stripe: creation cursor plus a re-check of invoices that can still change.** Stripe
   objects have no modification time. New objects are listed with `created[gte]` the cursor;
   invoices still `draft` or `open` in raw are re-read one by one each run, which catches
   payments and voids. The version is the latest timestamp the object carries (`created` and
   the invoice `status_transitions`).

## Known limitations

- A change that does not move the version is missed: for example an association added in
  HubSpot without touching the record, or a metadata edit on a Stripe object.
- Deleted or archived records are not detected; they stay in raw with their last version.
- Payment intents and refunds are assumed final once created, which holds for this project.
