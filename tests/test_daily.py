from datetime import date, timedelta
from pathlib import Path

import pytest

from generator.daily import (
    DailyRunner, invoice_date_for, next_stage, plan_new_records, planted_open_invoices,
    stable_fraction, stable_int,
)
from generator.model import LOST, OPEN_STAGES, WON, build_dataset, load_config
from generator.state import LoadState
from generator.stripe_loader import StripeLoader
from tests.fakes import FakeHubSpot, FakeStripe, ms

CONFIG = load_config(Path(__file__).resolve().parent.parent / "generator" / "config.yaml")
SEED = build_dataset(CONFIG)
AS_OF = date.fromisoformat(CONFIG["as_of_date"])
DAY1 = AS_OF + timedelta(days=1)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_stable_helpers_are_deterministic_and_in_range():
    assert stable_fraction("DEAL-1", DAY1) == stable_fraction("DEAL-1", DAY1)
    assert stable_fraction("DEAL-1", DAY1) != stable_fraction("DEAL-2", DAY1)
    values = [stable_int(0, 10, "x", i) for i in range(500)]
    assert min(values) == 0 and max(values) == 10


def test_plan_is_deterministic_and_uses_daily_ids():
    a = plan_new_records(CONFIG, DAY1, SEED.companies)
    assert a == plan_new_records(CONFIG, DAY1, SEED.companies)
    contacts, deals = a
    assert 2 <= len(contacts) <= 5 and 1 <= len(deals) <= 3
    assert all(c.external_id.startswith("CON-D20261101-") for c in contacts)
    assert {d.contact_id for d in deals} <= {c.external_id for c in contacts}


def test_next_stage_moves_forward_and_closes_from_contract_sent():
    assert next_stage("D", OPEN_STAGES[0], DAY1) == OPEN_STAGES[1]
    outcomes = {next_stage(f"D{i}", OPEN_STAGES[-1], DAY1) for i in range(50)}
    assert outcomes == {WON, LOST}


def test_planted_open_invoices_are_the_unpaid_and_partial_ones():
    keep = planted_open_invoices(CONFIG)
    expected = sum(1 for a in SEED.anomalies if a.anomaly_type in ("unpaid_invoice", "partial_payment"))
    assert len(keep) == expected


# --------------------------------------------------------------------------- #
# End to end with fake APIs
# --------------------------------------------------------------------------- #
def make_world(tmp_path):
    hs, st = FakeHubSpot(), FakeStripe()
    company_hs = {c.external_id: hs.add("companies", {"external_id": c.external_id, "name": c.name,
                                                      "domain": c.domain}) for c in SEED.companies}
    for d in SEED.deals:
        if d.stage in OPEN_STAGES:
            hs.add("deals", {"external_id": d.external_id, "dealstage": d.stage, "amount": d.amount,
                             "dealname": f"{d.product} - {d.company_id}"}, company=company_hs[d.company_id])

    paid = {p.invoice_id for p in SEED.payments}
    keep = planted_open_invoices(CONFIG)
    planted = next(i for i in SEED.invoices if i.external_id in keep)
    not_due = next(i for i in SEED.invoices if i.external_id not in paid and i.due_date > AS_OF)
    for inv in (planted, not_due):
        comp = next(c for c in SEED.companies if c.external_id == inv.crm_company_id)
        cus = st._handle("POST", "/v1/customers", {"email": f"billing@{comp.domain}",
                                                   "metadata[crm_company_id]": comp.external_id}, {})
        st.add_invoice(cus["id"], {"invoice_external_id": inv.external_id,
                                   "invoice_date": inv.invoice_date.isoformat(),
                                   "due_date": inv.due_date.isoformat()})
    loader = StripeLoader("sk_test_x", LoadState(tmp_path / "s.json"), CONFIG, client=st)
    return DailyRunner(CONFIG, hs, st, loader), hs, st, planted, not_due


def snapshot(hs, st):
    return (
        {k: {i: dict(p) for i, p in v.items()} for k, v in hs.objects.items()},
        {i: (v["status"], dict(v["metadata"])) for i, v in st.invoices.items()},
    )


def test_refuses_days_inside_the_seed_period(tmp_path):
    runner, *_ = make_world(tmp_path)
    with pytest.raises(ValueError):
        runner.run_day(AS_OF)


def test_same_day_twice_changes_nothing_the_second_time(tmp_path):
    runner, hs, st, *_ = make_world(tmp_path)
    first = runner.run_day(DAY1)
    assert first.get("contacts_created", 0) >= 2
    before = snapshot(hs, st)
    assert runner.run_day(DAY1) == {}
    assert snapshot(hs, st) == before


def test_sixty_days_of_activity_keep_the_invariants(tmp_path):
    runner, hs, st, planted, not_due = make_world(tmp_path)
    for i in range(60):
        runner.run_day(DAY1 + timedelta(days=i))
    last_day = DAY1 + timedelta(days=59)

    # Planted unpaid invoices are never paid; a normal open invoice gets paid.
    status = {v["metadata"].get("invoice_external_id"): v["status"] for v in st.invoices.values()}
    assert status[planted.external_id] == "open"
    assert status[not_due.external_id] == "paid"

    # Every deal won during the simulation is invoiced exactly once, after its lag.
    deals = hs.by_external("deals")
    won = [d for d in deals.values() if d["dealstage"] == WON]
    assert won, "expected some deals to close as won in 60 days"
    per_deal = {}
    for inv in st.invoices.values():
        ref = inv["metadata"].get("crm_deal_id")
        if ref:
            per_deal[ref] = per_deal.get(ref, 0) + 1
            assert date.fromisoformat(inv["metadata"]["invoice_date"]) >= AS_OF
    assert all(n == 1 for n in per_deal.values())
    from generator.daily import from_ms
    for d in won:
        close = from_ms(d["closedate"])
        if invoice_date_for(d["external_id"], close, CONFIG) <= last_day:
            assert per_deal.get(d["external_id"]) == 1, d["external_id"]
        else:
            assert d["external_id"] not in per_deal

    # New deals start at the first stage and are linked to a company and a contact.
    for d in deals.values():
        if d["external_id"].startswith("DEAL-D"):
            links = hs.assoc[("deals", d["id"])]
            assert set(links) == {"companies", "contacts"}


def test_stale_search_result_for_a_closed_deal_is_skipped(tmp_path):
    """HubSpot's search index can lag: a just-closed deal may still match the open filter."""
    runner, hs, *_ = make_world(tmp_path)
    original = hs.request

    def stale_search(method, path, json=None, **kw):
        resp = original(method, path, json=json, **kw)
        if path == "/crm/v3/objects/deals/search" and resp.get("results"):
            resp["results"].append({"id": "stale", "properties": {
                "external_id": "DEAL-STALE", "dealstage": WON, "sim_last_moved": None}})
        return resp

    hs.request = stale_search
    from generator import daily
    old = daily.MOVE_PROBABILITY
    daily.MOVE_PROBABILITY = 1.0  # force every deal to be considered
    try:
        runner.move_deals(DAY1)   # must not raise
    finally:
        daily.MOVE_PROBABILITY = old
