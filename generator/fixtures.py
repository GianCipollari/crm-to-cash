"""Raw tables built straight from the seed dataset, without calling any API.

The records have the same JSON shape the extractor stores from HubSpot and
Stripe, so the whole dbt project (including the ground-truth tests) can run in
CI without secrets. Only the fields the dbt models read are included.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from extractor.storage import RawStore
from generator.model import Dataset

LOAD_TIME = "2026-11-01T00:00:00.000Z"  # fixed, so builds are reproducible


def _iso_midnight(d: date) -> str:
    return f"{d.isoformat()}T00:00:00Z"


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _cents(amount: float) -> int:
    return int(round(amount * 100))


def _row(rid: str, payload: dict) -> dict:
    return {"id": rid, "updated_at": LOAD_TIME, "payload": payload}


def build_raw_records(ds: Dataset) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}

    # ---- HubSpot: numeric string ids, properties as strings, associations ---- #
    company_hs = {c.external_id: str(100000 + i) for i, c in enumerate(ds.companies)}
    contact_hs = {c.external_id: str(200000 + i) for i, c in enumerate(ds.contacts)}
    deal_hs = {d.external_id: str(300000 + i) for i, d in enumerate(ds.deals)}

    tables["raw_hubspot_companies"] = [_row(company_hs[c.external_id], {
        "id": company_hs[c.external_id], "createdAt": LOAD_TIME, "updatedAt": LOAD_TIME,
        "properties": {"external_id": c.external_id, "name": c.name, "domain": c.domain,
                       "country": c.country, "tax_id": c.tax_id},
        "associations": {},
    }) for c in ds.companies]

    tables["raw_hubspot_contacts"] = [_row(contact_hs[c.external_id], {
        "id": contact_hs[c.external_id], "createdAt": LOAD_TIME, "updatedAt": LOAD_TIME,
        "properties": {"external_id": c.external_id, "firstname": c.first_name, "lastname": c.last_name,
                       "email": c.email, "lead_source": c.lead_source,
                       "source_created_date": c.created_at.isoformat(), "lifecyclestage": "lead"},
        "associations": {"companies": [company_hs[c.company_id]]},
    }) for c in ds.contacts]

    tables["raw_hubspot_deals"] = [_row(deal_hs[d.external_id], {
        "id": deal_hs[d.external_id], "createdAt": LOAD_TIME, "updatedAt": LOAD_TIME,
        "properties": {"external_id": d.external_id, "dealname": f"{d.product} - {d.company_id}",
                       "amount": f"{d.amount:.2f}", "pipeline": "default", "dealstage": d.stage,
                       "closedate": _iso_midnight(d.close_date) if d.close_date else None,
                       "sales_rep": d.owner.lower().replace(" ", "_"),
                       "deal_created_date": d.created_at.isoformat()},
        "associations": {"companies": [company_hs[d.company_id]], "contacts": [contact_hs[d.contact_id]]},
    }) for d in ds.deals]

    # ---- Stripe: prefixed ids, amounts in cents, business dates in metadata ---- #
    customer_st = {c.crm_company_id: f"cus_{i:05d}" for i, c in enumerate(ds.customers)}
    tables["raw_stripe_customers"] = [_row(customer_st[c.crm_company_id], {
        "id": customer_st[c.crm_company_id], "name": c.name, "email": c.email,
        "metadata": {"crm_company_id": c.external_id} if c.external_id else {},
        "created": _epoch(date(2026, 11, 1)),
    }) for c in ds.customers]

    payments = {p.invoice_id: p for p in ds.payments}
    invoices, intents, refunds = [], [], []
    for i, inv in enumerate(ds.invoices):
        inv_id, pay = f"in_{i:05d}", payments.get(inv.external_id)
        full = pay is not None and pay.kind == "full"
        pi_id = f"pi_{i:05d}" if pay else None
        meta = {"invoice_external_id": inv.external_id, "invoice_date": inv.invoice_date.isoformat(),
                "due_date": inv.due_date.isoformat()}
        if inv.deal_ref:
            meta["crm_deal_id"] = inv.deal_ref
        invoices.append(_row(inv_id, {
            "id": inv_id, "customer": customer_st[inv.crm_company_id],
            "payment_intent": pi_id if full else None,
            "status": "paid" if full else "open", "currency": "usd",
            "amount_due": _cents(inv.amount), "amount_paid": _cents(inv.amount) if full else 0,
            "amount_remaining": 0 if full else _cents(inv.amount),
            "metadata": meta, "created": _epoch(inv.invoice_date),
            "status_transitions": {"finalized_at": _epoch(inv.invoice_date),
                                   "paid_at": _epoch(pay.paid_at) if full else None},
        }))
        if not pay:
            continue
        pi_meta = {"payment_external_id": pay.external_id, "paid_at": pay.paid_at.isoformat()}
        if not full:
            pi_meta["invoice_external_id"] = inv.external_id
        intents.append(_row(pi_id, {
            "id": pi_id, "customer": customer_st[inv.crm_company_id],
            "invoice": inv_id if full else None, "status": "succeeded", "currency": "usd",
            "amount": _cents(pay.amount), "amount_received": _cents(pay.amount),
            "metadata": pi_meta, "created": _epoch(pay.paid_at),
        }))
        if pay.refunded_at:
            re_id = f"re_{i:05d}"
            refunds.append(_row(re_id, {
                "id": re_id, "payment_intent": pi_id, "charge": f"ch_{i:05d}", "status": "succeeded",
                "currency": "usd", "amount": _cents(pay.amount),
                "metadata": {"refunded_at": pay.refunded_at.isoformat(), "payment_external_id": pay.external_id},
                "created": _epoch(pay.refunded_at),
            }))
    tables["raw_stripe_invoices"] = invoices
    tables["raw_stripe_payment_intents"] = intents
    tables["raw_stripe_refunds"] = refunds
    return tables


def write_fixtures(ds: Dataset, store: RawStore) -> dict[str, int]:
    return {table: store.upsert(table, rows)["inserted"] for table, rows in build_raw_records(ds).items()}
