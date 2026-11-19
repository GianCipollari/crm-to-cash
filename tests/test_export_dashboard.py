import pytest

from extractor.export_dashboard_data import STATUS_LABELS, label_case

duckdb = pytest.importorskip("duckdb")


def _label(code: str, labels=None) -> str:
    return duckdb.sql(f"select {label_case('c', labels)} from (select '{code}' as c)").fetchone()[0]


def test_mapped_status_gets_its_readable_name():
    assert _label("missing_invoice", STATUS_LABELS) == "Never invoiced"


def test_unmapped_code_falls_back_to_sentence_case():
    assert _label("contact_without_external_id") == "Contact without external id"
    assert _label("brand_new_status", STATUS_LABELS) == "Brand new status"
