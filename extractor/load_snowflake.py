"""Copies the raw tables from the DuckDB warehouse to Snowflake.

    python -m extractor.load_snowflake

The extractor keeps writing to DuckDB; this step publishes the same raw tables
to CRM_TO_CASH.RAW so dbt can build the identical project with --target snowflake.
The raw tables are small (a few thousand rows), so each run replaces them fully.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_COLUMNS = "id, updated_at, payload, _loaded_at"


def read_raw_tables(conn) -> dict[str, list[tuple]]:
    """All raw_* tables from a DB-API connection (DuckDB in practice, SQLite in tests)."""
    try:
        names = [r[0] for r in conn.execute(
            "select table_name from information_schema.tables where table_name like 'raw_%'").fetchall()]
    except Exception:  # SQLite has no information_schema
        names = [r[0] for r in conn.execute(
            "select name from sqlite_master where type = 'table' and name like 'raw_%'").fetchall()]
    return {n: conn.execute(f"select {RAW_COLUMNS} from {n}").fetchall() for n in sorted(names)}


def snowflake_connection():
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ.get("SNOWFLAKE_ACCOUNT", "MHBLMHG-FC64741"),
        user=os.environ.get("SNOWFLAKE_USER", "DBT_SERVICE"),
        private_key_file=os.environ.get(
            "SNOWFLAKE_PRIVATE_KEY_PATH", str(ROOT / "out" / "keys" / "snowflake_dbt_key.p8")),
        role=os.environ.get("SNOWFLAKE_ROLE", "CRM_TO_CASH_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CRM_TO_CASH_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "CRM_TO_CASH"),
        paramstyle="qmark",
    )


def load(tables: dict[str, list[tuple]], sf) -> dict[str, int]:
    cur = sf.cursor()
    cur.execute("create schema if not exists raw")
    counts = {}
    for name, rows in tables.items():
        cur.execute(f"create or replace table raw.{name} "
                    "(id varchar, updated_at varchar, payload varchar, _loaded_at varchar)")
        if rows:
            cur.executemany(f"insert into raw.{name} ({RAW_COLUMNS}) values (?, ?, ?, ?)", rows)
        counts[name] = len(rows)
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="load_snowflake")
    parser.add_argument("--db", default=os.environ.get("WAREHOUSE_PATH", str(ROOT / "out" / "warehouse.duckdb")))
    args = parser.parse_args(argv)

    import duckdb

    src = duckdb.connect(args.db, read_only=True)
    try:
        tables = read_raw_tables(src)
    finally:
        src.close()
    sf = snowflake_connection()
    try:
        counts = load(tables, sf)
    finally:
        sf.close()
    for name, n in counts.items():
        print(f"{name:<32}{n:>8} rows")


if __name__ == "__main__":
    main()
