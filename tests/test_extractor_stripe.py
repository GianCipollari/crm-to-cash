"""Stripe extractor tests with a fake list API and SQLite."""

import json
import re
import sqlite3
from itertools import count

from extractor.storage import RawStore
from extractor.stripe import STREAMS, StripeExtractor, version_of

T0 = 1_793_000_000  # a November 2026 unix timestamp


class FakeStripeLists:
    def __init__(self):
        self.data = {r: {} for r in STREAMS}
        self.clock = count(T0, 60)
        self.calls = []

    def add(self, resource, **fields):
        prefix = {"customers": "cus", "invoices": "in", "payment_intents": "pi", "refunds": "re"}[resource]
        oid = f"{prefix}_{len(self.data[resource]) + 1}"
        self.data[resource][oid] = {"id": oid, "created": next(self.clock), **fields}
        return oid

    def request(self, method, path, params=None, **kw):
        self.calls.append((path, dict(params or {})))
        m = re.match(r"/v1/invoices/(in_\d+)$", path)
        if m:
            return dict(self.data["invoices"][m.group(1)])
        resource = path.removeprefix("/v1/")
        rows = sorted(self.data[resource].values(), key=lambda o: (-o["created"], o["id"]))  # newest first
        if "created[gte]" in params:
            rows = [o for o in rows if o["created"] >= params["created[gte]"]]
        if "starting_after" in params:
            rows = rows[[o["id"] for o in rows].index(params["starting_after"]) + 1:]
        page = rows[: params["limit"]]
        return {"data": [dict(o) for o in page], "has_more": len(rows) > len(page)}


def world(n_invoices=5):
    api = FakeStripeLists()
    cus = api.add("customers", email="billing@x.com")
    for i in range(n_invoices):
        status = "open" if i % 2 else "paid"
        transitions = {"finalized_at": T0, "paid_at": T0 + 30 if status == "paid" else None}
        api.add("invoices", customer=cus, status=status, status_transitions=transitions)
    api.add("payment_intents", status="succeeded")
    return api


def raw(store, table, rid):
    return json.loads(store.conn.execute(f"SELECT payload FROM {table} WHERE id = ?", [rid]).fetchone()[0])


def test_version_uses_latest_status_transition():
    inv = {"created": T0, "status_transitions": {"finalized_at": T0 + 5, "paid_at": T0 + 99, "voided_at": None}}
    assert version_of(inv) > version_of({"created": T0})


def test_first_run_loads_all_and_second_writes_nothing():
    api = world()
    ex = StripeExtractor(api, RawStore(sqlite3.connect(":memory:")))
    first = ex.extract_all()
    assert first["invoices"]["inserted"] == 5 and first["customers"]["inserted"] == 1
    second = ex.extract_all()
    assert all(r["inserted"] == 0 and r["updated"] == 0 for r in second.values())


def test_paid_invoice_is_caught_by_the_recheck():
    api = world()
    ex = StripeExtractor(api, RawStore(sqlite3.connect(":memory:")))
    ex.extract_all()
    api.data["invoices"]["in_2"]["status"] = "paid"
    api.data["invoices"]["in_2"]["status_transitions"]["paid_at"] = T0 + 10_000
    res = ex.extract("invoices")
    assert res["updated"] == 1
    assert res["rechecked"] == 2  # both open invoices (in_2, in_4) are re-read
    assert raw(ex.store, "raw_stripe_invoices", "in_2")["status"] == "paid"


def test_new_objects_are_picked_up_incrementally():
    api = world()
    ex = StripeExtractor(api, RawStore(sqlite3.connect(":memory:")))
    ex.extract_all()
    api.add("refunds", payment_intent="pi_1", status="succeeded")
    api.add("invoices", customer="cus_1", status="open", status_transitions={"finalized_at": T0})
    res = ex.extract_all()
    assert res["refunds"]["inserted"] == 1 and res["invoices"]["inserted"] == 1
    assert res["refunds"]["fetched"] <= 2  # new record plus at most the boundary one


def test_pagination():
    api = world(n_invoices=230)
    res = StripeExtractor(api, RawStore(sqlite3.connect(":memory:"))).extract("invoices")
    assert res["inserted"] == 230
    assert sum(1 for p, _ in api.calls if p == "/v1/invoices") == 3
