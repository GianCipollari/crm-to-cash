"""Exports the marts the dashboard needs to CSV files for Evidence.

    python -m extractor.export_dashboard_data

Evidence reads these files instead of the DuckDB file itself, so the dashboard
does not depend on Evidence bundling the same DuckDB version that wrote the warehouse.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dashboard" / "sources" / "marts"

# Readable names for the dashboard; codes stay in the marts and in the tests.
STATUS_LABELS = {
    "reconciled": "Reconciled",
    "duplicate": "Duplicate deal",
    "pending_invoice": "Invoice pending",
    "missing_invoice": "Never invoiced",
    "refunded": "Refunded",
    "partial_payment": "Partially paid",
    "unpaid_overdue": "Unpaid, overdue",
    "not_yet_due": "Unpaid, not yet due",
    "amount_mismatch": "Amount differs",
    "late_stage_update": "Won after payment",
}

# Same wording as the statuses where the problem is the same; kept short so chart labels fit.
ISSUE_LABELS = {
    "duplicate_deal": "Duplicate deal",
    "missing_invoice": "Never invoiced",
    "unpaid_invoice": "Unpaid, overdue",
    "partial_payment": "Partially paid",
    "amount_mismatch": "Amount differs",
    "late_stage_update": "Won after payment",
    "refund": "Refunded",
    "name_variant": "Company name differs",
    "missing_external_id": "Customer without CRM id",
    "unmatched_customer": "Unmatched customer",
    "contact_without_external_id": "Contact without id",
}


def label_case(column: str, labels: dict[str, str] | None = None) -> str:
    """SQL that turns a snake_case code into a readable label: mapped names first,
    otherwise 'missing_invoice' becomes 'Missing invoice'."""
    fallback = f"upper(left({column}, 1)) || replace(substr({column}, 2), '_', ' ')"
    if not labels:
        return fallback
    whens = " ".join(f"when '{code}' then '{text}'" for code, text in labels.items())
    return f"case {column} {whens} else {fallback} end"


QUERIES = {
    "reconciliation": f"""
        select deal_id, external_id, replace(sales_rep, '_', ' ') as sales_rep, product,
               close_date, close_month, deal_amount, invoice_amount, net_collected,
               gap_amount, reconciliation_status,
               {label_case('reconciliation_status', STATUS_LABELS)} as status_label,
               is_duplicate
        from fct_deal_reconciliation""",
    "funnel": f"""
        select contact_id, lead_source, {label_case('lead_source')} as lead_source_label,
               cohort_month, reached_deal, reached_won, reached_paid,
               won_amount, collected_amount, days_lead_to_cash
        from fct_lead_funnel""",
    "issues": f"""
        select issue_type, {label_case('issue_type', ISSUE_LABELS)} as issue_label, object_type,
               external_id, related_deal_id, amount_at_risk, detail, detected_on
        from mart_data_quality_issues""",
}


def export(conn, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, sql in QUERIES.items():
        path = (out_dir / f"{name}.csv").as_posix()
        conn.execute(f"copy ({sql}) to '{path}' (header, delimiter ',')")
        counts[name] = conn.execute(f"select count(*) from ({sql})").fetchone()[0]
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="export_dashboard_data")
    parser.add_argument("--db", default=os.environ.get("WAREHOUSE_PATH", str(ROOT / "out" / "warehouse.duckdb")))
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)

    import duckdb

    conn = duckdb.connect(args.db, read_only=True)
    try:
        counts = export(conn, Path(args.out))
    finally:
        conn.close()
    print("Dashboard data exported: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
