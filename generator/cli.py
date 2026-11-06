"""Command line entry point.

Examples:
    python -m generator.cli seed --dry-run            # build + export CSVs, no API calls
    python -m generator.cli seed --target hubspot     # load the CRM side
    python -m generator.cli seed --target stripe      # load the billing side
    python -m generator.cli seed --target all
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
from collections import Counter
from dataclasses import asdict, fields
from pathlib import Path

from dotenv import load_dotenv

from generator.model import WON, build_dataset, load_config

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("generator")


def export_csv(ds, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("companies", "contacts", "deals", "customers", "invoices", "payments", "anomalies"):
        rows = getattr(ds, name)
        if not rows:
            continue
        path = out_dir / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(rows[0])])
            writer.writeheader()
            writer.writerows(asdict(r) for r in rows)
    log.info("CSV files written to %s", out_dir)


def summary(ds) -> str:
    won = [d for d in ds.deals if d.stage == WON and not d.duplicate_of]
    won_amount = sum(d.amount for d in won)
    invoiced = sum(i.amount for i in ds.invoices)
    collected = sum(p.amount for p in ds.payments if not p.refunded_at)
    stages = Counter(d.stage for d in ds.deals)
    lines = [
        f"Companies {len(ds.companies)} | Contacts {len(ds.contacts)} | Deals {len(ds.deals)} "
        f"(incl. {sum(1 for d in ds.deals if d.duplicate_of)} duplicates)",
        "Stages: " + ", ".join(f"{k}={v}" for k, v in sorted(stages.items())),
        f"Customers {len(ds.customers)} | Invoices {len(ds.invoices)} | Payments {len(ds.payments)}",
        f"Closed won (excl. duplicates): USD {won_amount:,.0f}",
        f"Invoiced: USD {invoiced:,.0f} ({invoiced / won_amount:.1%})",
        f"Collected net of refunds: USD {collected:,.0f} ({collected / won_amount:.1%})",
        "Anomalies planted: " + ", ".join(
            f"{k}={v}" for k, v in sorted(Counter(a.anomaly_type for a in ds.anomalies).items())),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="generator")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="Build the synthetic company and load it")
    seed.add_argument("--target", choices=["all", "hubspot", "stripe"], default="all")
    seed.add_argument("--dry-run", action="store_true", help="Only build and export CSVs")
    seed.add_argument("--config", default=str(ROOT / "generator" / "config.yaml"))
    seed.add_argument("--out", default=str(ROOT / "out"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")

    config = load_config(args.config)
    ds = build_dataset(config)
    out = Path(args.out)
    export_csv(ds, out / "dataset")
    print(summary(ds))
    if args.dry_run:
        return

    from generator.state import LoadState  # imported here so --dry-run needs no API setup

    if args.target in ("all", "hubspot"):
        from generator.hubspot_loader import HubSpotLoader
        token = os.environ["HUBSPOT_TOKEN"]
        HubSpotLoader(token, LoadState(out / "state" / "hubspot.json"), config).load(ds)
    if args.target in ("all", "stripe"):
        from generator.stripe_loader import StripeLoader
        key = os.environ["STRIPE_TEST_KEY"]
        StripeLoader(key, LoadState(out / "state" / "stripe.json"), config).load(ds)


if __name__ == "__main__":
    main()
