"""Checks that DuckDB and Snowflake produce the same results from the same raw data.

    python -m extractor.compare_warehouses

Runs the same summary queries on both warehouses (counts and amounts per status,
issue type and match method) and prints a side-by-side table. Exits with code 1
if any figure differs, so it can also run in a script or a workflow.
Run it right after building both targets on the same day (statuses depend on
the current date) and after `extractor.load_snowflake`, so both read the same raw data.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

from extractor.load_snowflake import snowflake_connection

ROOT = Path(__file__).resolve().parent.parent

CHECKS = {
    "deals by reconciliation status":
        "select reconciliation_status, count(*), sum(gap_amount) from fct_deal_reconciliation group by 1",
    "data quality issues by type":
        "select issue_type, count(*), sum(coalesce(amount_at_risk, 0)) from mart_data_quality_issues group by 1",
    "customers by match method":
        "select match_method, count(*), 0 from int_customers_matched group by 1",
    "lead funnel totals":
        "select 'all contacts', count(*), sum(collected_amount) from fct_lead_funnel",
}


def summarize(cursor_execute) -> dict[tuple[str, str], tuple[int, Decimal]]:
    """{(check, key): (count, amount)} using any function that runs SQL and returns rows."""
    out = {}
    for check, sql in CHECKS.items():
        for key, n, amount in cursor_execute(sql):
            out[(check, str(key))] = (int(n), Decimal(str(amount or 0)).quantize(Decimal("0.01")))
    return out


def compare(left: dict, right: dict) -> list[tuple]:
    rows = []
    for k in sorted(set(left) | set(right)):
        a, b = left.get(k), right.get(k)
        rows.append((k[0], k[1], a, b, a == b))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="compare_warehouses")
    parser.add_argument("--db", default=os.environ.get("WAREHOUSE_PATH", str(ROOT / "out" / "warehouse.duckdb")))
    args = parser.parse_args(argv)

    import duckdb

    duck = duckdb.connect(args.db, read_only=True)
    try:
        left = summarize(lambda sql: duck.execute(sql).fetchall())
    finally:
        duck.close()

    sf = snowflake_connection()
    try:
        cur = sf.cursor()
        cur.execute("use schema analytics")
        right = summarize(lambda sql: cur.execute(sql).fetchall())
    finally:
        sf.close()

    rows = compare(left, right)
    print(f"{'check':<34}{'key':<30}{'duckdb':>24}{'snowflake':>24}  ")
    for check, key, a, b, same in rows:
        fmt = lambda v: "-" if v is None else f"{v[0]} | {v[1]}"
        print(f"{check:<34}{key:<30}{fmt(a):>24}{fmt(b):>24}  {'ok' if same else 'DIFFERENT'}")
    differences = sum(1 for r in rows if not r[4])
    print(f"\n{len(rows) - differences} of {len(rows)} figures match")
    sys.exit(1 if differences else 0)


if __name__ == "__main__":
    main()
