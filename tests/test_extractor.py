"""Extractor tests: a fake HubSpot Search API and an SQLite database stand in
for the real API and DuckDB (the SQL is the same)."""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from extractor.hubspot import STREAMS, HubSpotExtractor, iso_to_ms
from extractor.storage import RawStore

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakeSearchApi:
    """Stores records per object with an updatedAt, answers Search and v4 associations."""
    def __init__(self):
        self.data = {obj: {} for obj in STREAMS}
        self.links = {}  # (obj, id, to_obj) -> [ids]
        self.calls = []
        self.clock = T0

    def put(self, obj, rid, **props):
        self.clock += timedelta(seconds=1)
        self.data[obj][rid] = {"id": rid, "properties": props, "updatedAt": iso(self.clock)}

    def request(self, method, path, json=None, **kw):
        self.calls.append(path)
        m = re.match(r"/crm/v3/objects/(\w+)/search$", path)
        if m:
            rows = sorted(self.data[m.group(1)].values(), key=lambda r: r["updatedAt"])
            for f in (json.get("filterGroups") or [{"filters": []}])[0]["filters"]:
                assert f["operator"] == "GTE" and f["propertyName"] == STREAMS[m.group(1)][0]
                rows = [r for r in rows if iso_to_ms(r["updatedAt"]) >= int(f["value"])]
            start = int(json.get("after") or 0)
            page = rows[start:start + json["limit"]]
            resp = {"results": [dict(r) for r in page]}
            if start + json["limit"] < len(rows):
                resp["paging"] = {"next": {"after": str(start + json["limit"])}}
            return resp
        m = re.match(r"/crm/v4/associations/(\w+)/(\w+)/batch/read$", path)
        if m:
            obj, to = m.groups()
            return {"results": [{"from": {"id": i["id"]},
                                 "to": [{"toObjectId": int(t)} for t in self.links.get((obj, i["id"], to), [])]}
                                for i in json["inputs"] if self.links.get((obj, i["id"], to))]}
        raise NotImplementedError(path)


def world(n_companies=3, n_contacts=5, n_deals=4):
    api = FakeSearchApi()
    for i in range(n_companies):
        api.put("companies", str(100 + i), external_id=f"CMP-{i}")
    for i in range(n_contacts):
        api.put("contacts", str(200 + i), external_id=f"CON-{i}")
        api.links[("contacts", str(200 + i), "companies")] = [str(100 + i % n_companies)]
    for i in range(n_deals):
        api.put("deals", str(300 + i), external_id=f"DEAL-{i}", dealstage="appointmentscheduled")
        api.links[("deals", str(300 + i), "companies")] = [str(100 + i % n_companies)]
        api.links[("deals", str(300 + i), "contacts")] = [str(200 + i % n_contacts)]
    return api


def extractor_for(api, conn=None):
    return HubSpotExtractor(api, RawStore(conn or sqlite3.connect(":memory:")))


def test_first_run_loads_everything_with_associations():
    api = world()
    ex = extractor_for(api)
    res = ex.extract_all()
    assert {o: r["inserted"] for o, r in res.items()} == {"companies": 3, "contacts": 5, "deals": 4}
    payload = json.loads(ex.store.conn.execute(
        "SELECT payload FROM raw_hubspot_deals WHERE id = '300'").fetchone()[0])
    assert payload["associations"] == {"companies": ["100"], "contacts": ["200"]}
    assert payload["properties"]["external_id"] == "DEAL-0"


def test_second_run_writes_nothing():
    api = world()
    ex = extractor_for(api)
    ex.extract_all()
    res = ex.extract_all()
    for r in res.values():
        assert r["inserted"] == 0 and r["updated"] == 0
        assert r["fetched"] <= 1  # only the boundary record is re-read (GTE cursor)


def test_incremental_run_picks_up_only_changes():
    api = world()
    ex = extractor_for(api)
    ex.extract_all()
    api.put("deals", "301", external_id="DEAL-1", dealstage="closedwon")   # modified
    api.put("deals", "399", external_id="DEAL-NEW", dealstage="appointmentscheduled")  # new
    res = ex.extract("deals")
    assert (res["inserted"], res["updated"]) == (1, 1)
    assert res["fetched"] <= 3 and res["total_in_raw"] == 5
    stage = json.loads(ex.store.conn.execute(
        "SELECT payload FROM raw_hubspot_deals WHERE id = '301'").fetchone()[0])["properties"]["dealstage"]
    assert stage == "closedwon"


def test_pagination_reads_every_page():
    api = world(n_companies=250, n_contacts=1, n_deals=1)
    res = extractor_for(api).extract("companies")
    assert res["inserted"] == 250
    assert sum(1 for c in api.calls if c.endswith("/companies/search")) == 3


def test_full_refresh_rereads_but_stays_idempotent():
    api = world()
    ex = extractor_for(api)
    ex.extract_all()
    res = ex.extract("contacts", full=True)
    assert res["fetched"] == 5 and res["unchanged"] == 5 and res["inserted"] == res["updated"] == 0


def test_cursor_survives_a_new_connection(tmp_path):
    db = tmp_path / "w.db"
    api = world()
    extractor_for(api, sqlite3.connect(db)).extract_all()
    second = extractor_for(api, sqlite3.connect(db))
    assert second.store.get_cursor("hubspot.deals") is not None
    assert all(r["inserted"] == 0 for r in second.extract_all().values())


def test_store_keeps_newest_version_when_an_id_repeats():
    store = RawStore(sqlite3.connect(":memory:"))
    counts = store.upsert("raw_t", [
        {"id": "1", "updated_at": "2026-11-06T10:00:00.000Z", "payload": {"v": 1}},
        {"id": "1", "updated_at": "2026-11-06T11:00:00.000Z", "payload": {"v": 2}},
    ])
    assert counts["inserted"] == 1
    assert json.loads(store.conn.execute("SELECT payload FROM raw_t").fetchone()[0]) == {"v": 2}
