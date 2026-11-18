"""The Snowflake loader copies every raw table as is (fake connection, no account needed)."""

import sqlite3

from extractor.load_snowflake import load, read_raw_tables
from extractor.storage import RawStore


class FakeCursor:
    def __init__(self):
        self.statements, self.rows = [], {}

    def execute(self, sql):
        self.statements.append(sql)

    def executemany(self, sql, rows):
        table = sql.split()[2]
        self.rows[table] = list(rows)


class FakeSnowflake:
    def __init__(self):
        self.cur = FakeCursor()

    def cursor(self):
        return self.cur


def test_reads_raw_tables_and_loads_them_unchanged():
    store = RawStore(sqlite3.connect(":memory:"))
    store.upsert("raw_hubspot_deals", [{"id": "1", "updated_at": "t", "payload": {"a": 1}}])
    store.upsert("raw_stripe_invoices", [{"id": "in_1", "updated_at": "t", "payload": {"b": 2}}])
    tables = read_raw_tables(store.conn)
    assert set(tables) == {"raw_hubspot_deals", "raw_stripe_invoices"}  # _extract_state is not copied

    sf = FakeSnowflake()
    counts = load(tables, sf)
    assert counts == {"raw_hubspot_deals": 1, "raw_stripe_invoices": 1}
    assert sf.cur.rows["raw.raw_hubspot_deals"][0][:2] == ("1", "t")
    assert any(s.startswith("create or replace table raw.raw_stripe_invoices") for s in sf.cur.statements)
