from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from generator.model import WON, build_dataset, load_config

CONFIG = load_config(Path(__file__).resolve().parent.parent / "generator" / "config.yaml")
AS_OF = date.fromisoformat(CONFIG["as_of_date"])


@pytest.fixture(scope="module")
def ds():
    return build_dataset(CONFIG)


def test_same_seed_same_dataset(ds):
    assert build_dataset(CONFIG) == ds


def test_different_seed_changes_dataset(ds):
    assert build_dataset({**CONFIG, "seed": 7}).deals != ds.deals


def test_volumes(ds):
    vol = CONFIG["volumes"]
    assert len(ds.companies) == vol["companies"]
    assert len(ds.contacts) == vol["contacts"]
    originals = [d for d in ds.deals if not d.duplicate_of]
    assert len(originals) == vol["deals"]


def test_ids_are_unique(ds):
    for rows in (ds.companies, ds.contacts, ds.deals, ds.invoices, ds.payments):
        ids = [r.external_id for r in rows]
        assert len(ids) == len(set(ids))
    assert len({c.email for c in ds.contacts}) == len(ds.contacts)


def test_every_company_has_a_contact(ds):
    assert {c.company_id for c in ds.contacts} == {c.external_id for c in ds.companies}


def test_dates_never_in_the_future(ds):
    assert all(i.invoice_date <= AS_OF for i in ds.invoices)
    assert all(p.paid_at <= AS_OF for p in ds.payments)
    assert all(d.close_date is None or d.close_date <= AS_OF for d in ds.deals)


def test_payments_never_exceed_invoice(ds):
    invoices = {i.external_id: i for i in ds.invoices}
    for p in ds.payments:
        assert p.amount <= invoices[p.invoice_id].amount + 0.01


def test_missing_invoices_match_manifest(ds):
    """Ground truth check: won deals without invoice are exactly the planted ones."""
    invoiced = {i.true_deal_id for i in ds.invoices}
    won_no_invoice = {d.external_id for d in ds.deals
                      if d.stage == WON and not d.duplicate_of and d.external_id not in invoiced}
    planted = {a.external_id for a in ds.anomalies if a.anomaly_type == "missing_invoice"}
    assert won_no_invoice == planted


def test_overdue_unpaid_match_manifest(ds):
    paid = {p.invoice_id for p in ds.payments}
    overdue_unpaid = {i.true_deal_id for i in ds.invoices
                      if i.due_date <= AS_OF and i.external_id not in paid}
    planted = {a.external_id for a in ds.anomalies if a.anomaly_type == "unpaid_invoice"}
    assert overdue_unpaid == planted


def test_deal_level_anomalies_do_not_overlap(ds):
    deal_level = {"missing_invoice", "unpaid_invoice", "partial_payment",
                  "amount_mismatch", "late_stage_update", "refund"}
    ids = [a.external_id for a in ds.anomalies if a.anomaly_type in deal_level]
    assert len(ids) == len(set(ids))


def test_anomaly_counts_follow_rates(ds):
    n_won = sum(1 for d in ds.deals if d.stage == WON and not d.duplicate_of)
    counts = Counter(a.anomaly_type for a in ds.anomalies)
    for name in ("missing_invoice", "amount_mismatch", "duplicate_deal"):
        assert counts[name] == round(CONFIG["anomalies"][name] * n_won)


def test_duplicates_point_to_won_deals(ds):
    deals = {d.external_id: d for d in ds.deals}
    for d in ds.deals:
        if d.duplicate_of:
            original = deals[d.duplicate_of]
            assert original.stage == WON
            assert (d.company_id, d.amount) == (original.company_id, original.amount)
            assert d.owner != original.owner


def test_missing_external_id_hides_deal_reference(ds):
    missing = {c.crm_company_id for c in ds.customers if c.external_id is None}
    assert missing, "expected at least one customer without CRM id"
    for inv in ds.invoices:
        assert (inv.deal_ref is None) == (inv.crm_company_id in missing)


def test_late_stage_update_close_after_payment(ds):
    pays = {p.invoice_id: p for p in ds.payments}
    inv_by_deal = {i.true_deal_id: i for i in ds.invoices}
    deals = {d.external_id: d for d in ds.deals}
    for a in ds.anomalies:
        if a.anomaly_type == "late_stage_update":
            pay = pays[inv_by_deal[a.external_id].external_id]
            assert deals[a.external_id].close_date > pay.paid_at
