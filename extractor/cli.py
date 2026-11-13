"""Command line entry point for the extractor.

Examples:
    python -m extractor.cli                    # incremental, HubSpot and Stripe
    python -m extractor.cli --source stripe    # one source only
    python -m extractor.cli --full             # re-read everything (still skips unchanged records)
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def print_table(results: dict[str, dict[str, int]]) -> None:
    cols = ["fetched", "rechecked", "inserted", "updated", "unchanged", "total_in_raw"]
    print(f"{'stream':<24}" + "".join(f"{c:>13}" for c in cols))
    for stream, c in results.items():
        print(f"{stream:<24}" + "".join(f"{c.get(col, 0):>13}" for col in cols))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="extractor")
    parser.add_argument("--source", choices=["all", "hubspot", "stripe"], default="all")
    parser.add_argument("--full", action="store_true", help="Ignore cursors and re-read everything")
    parser.add_argument("--db", default=os.environ.get("WAREHOUSE_PATH", str(ROOT / "out" / "warehouse.duckdb")))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")

    import duckdb  # imported here so the tests can run without it

    from extractor.hubspot import HubSpotExtractor
    from extractor.storage import RawStore
    from extractor.stripe import StripeExtractor

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(args.db)
    results: dict[str, dict[str, int]] = {}
    try:
        store = RawStore(conn)
        if args.source in ("all", "hubspot"):
            ex = HubSpotExtractor.from_token(os.environ["HUBSPOT_TOKEN"], store)
            results.update({f"hubspot.{k}": v for k, v in ex.extract_all(full=args.full).items()})
        if args.source in ("all", "stripe"):
            ex = StripeExtractor.from_key(os.environ["STRIPE_TEST_KEY"], store)
            results.update({f"stripe.{k}": v for k, v in ex.extract_all(full=args.full).items()})
    finally:
        conn.close()
    print_table(results)


if __name__ == "__main__":
    main()
