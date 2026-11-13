"""Command line entry point for the extractor.

Examples:
    python -m extractor.cli                 # incremental: only what changed since the last run
    python -m extractor.cli --full          # re-read everything (still skips unchanged records)
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="extractor")
    parser.add_argument("--source", choices=["hubspot"], default="hubspot")
    parser.add_argument("--full", action="store_true", help="Ignore cursors and re-read everything")
    parser.add_argument("--db", default=os.environ.get("WAREHOUSE_PATH", str(ROOT / "out" / "warehouse.duckdb")))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")

    import duckdb  # imported here so the tests can run without it

    from extractor.hubspot import HubSpotExtractor
    from extractor.storage import RawStore

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(args.db)
    try:
        store = RawStore(conn)
        results = HubSpotExtractor.from_token(os.environ["HUBSPOT_TOKEN"], store).extract_all(full=args.full)
    finally:
        conn.close()

    print(f"{'stream':<20}{'fetched':>9}{'inserted':>10}{'updated':>9}{'unchanged':>11}{'in raw':>8}")
    for obj, c in results.items():
        print(f"{'hubspot.' + obj:<20}{c['fetched']:>9}{c['inserted']:>10}{c['updated']:>9}"
              f"{c['unchanged']:>11}{c['total_in_raw']:>8}")


if __name__ == "__main__":
    main()
