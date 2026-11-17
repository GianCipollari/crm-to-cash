# ADR 0004: Matching CRM and billing records

**Status:** accepted · **Date:** 2026-11-17

## Context

Reconciliation needs to know which Stripe customer is which HubSpot company, and which
invoice bills which won deal. The generator planted the usual real-world problems on
purpose: billing records without the CRM id, company names typed differently, invoices
without a deal reference and duplicate deals.

## Decisions

1. **Customers to companies, in three ordered passes** (`int_customers_matched`): the CRM id
   in Stripe metadata, then billing email domain = company domain, then names equal after
   removing accents, punctuation and legal form. Each pass only sees what the previous ones
   left unmatched, and every row records the method that resolved it. Unresolved customers
   stay visible as `unmatched` and raise a dbt warning instead of disappearing.

2. **Invoices to won deals, in two passes** (`int_deals_with_invoices`): the CRM deal id in
   invoice metadata, then, for invoices without it, a won deal of the same company invoiced
   0-15 days after its close date, preferring the closest amount and then the closest date.
   A test guarantees that one invoice bills at most one deal.

3. **Duplicates are flagged, not removed** (`int_deal_duplicates`): same company and amount,
   close dates at most 3 days apart; the later deal is marked as the duplicate. Marts decide
   what to exclude.

4. **Staging keeps every source row.** Filters (for example HubSpot's sample contacts, flagged
   with `has_external_id`) are applied in intermediate or marts, never in staging.

## Consequences

- Every match can be explained in an interview or an audit: the method is a column.
- Pass 2 of the invoice matching is heuristic. If two won deals of the same company and
  amount close within the window, the earlier external id wins.
