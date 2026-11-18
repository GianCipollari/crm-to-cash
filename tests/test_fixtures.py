"""The CI fixtures must look like what the extractor stores from the real APIs."""

import json
import sqlite3
from pathlib import Path

from extractor.storage import RawStore
from generator.fixtures import build_raw_records, write_fixtures
from generator.model import build_dataset, load_config

DS = build_dataset(load_config(Path(__file__).resolve().parent.parent / "generator" / "config.yaml"))


def test_one_raw_row_per_record():
    t = build_raw_records(DS)
    assert len(t["raw_hubspot_companies"]) == len(DS.companies)
    assert len(t["raw_hubspot_contacts"]) == len(DS.contacts)
    assert len(t["raw_hubspot_deals"]) == len(DS.deals)
    assert len(t["raw_stripe_customers"]) == len(DS.customers)
    assert len(t["raw_stripe_invoices"]) == len(DS.invoices)
    assert len(t["raw_stripe_payment_intents"]) == len(DS.payments)
    assert len(t["raw_stripe_refunds"]) == sum(1 for p in DS.payments if p.refunded_at)


def test_payload_shape_matches_what_staging_reads():
    t = build_raw_records(DS)
    deal = t["raw_hubspot_deals"][0]["payload"]
    assert {"external_id", "amount", "dealstage", "closedate", "sales_rep"} <= set(deal["properties"])
    assert set(deal["associations"]) == {"companies", "contacts"}
    inv = t["raw_stripe_invoices"][0]["payload"]
    assert {"invoice_external_id", "invoice_date", "due_date"} <= set(inv["metadata"])
    assert isinstance(inv["amount_due"], int)  # cents, like Stripe


def test_partial_payments_reference_the_invoice_in_metadata_only():
    for row in build_raw_records(DS)["raw_stripe_payment_intents"]:
        p = row["payload"]
        assert (p["invoice"] is None) == ("invoice_external_id" in p["metadata"])


def test_written_through_the_same_store_as_the_extractor():
    store = RawStore(sqlite3.connect(":memory:"))
    counts = write_fixtures(DS, store)
    assert counts["raw_hubspot_deals"] == len(DS.deals)
    payload = json.loads(store.conn.execute("SELECT payload FROM raw_stripe_customers LIMIT 1").fetchone()[0])
    assert payload["email"].startswith("billing@")
