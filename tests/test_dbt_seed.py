"""The dbt seed must stay identical to what the generator plants."""

import csv
from dataclasses import asdict
from pathlib import Path

from generator.model import build_dataset, load_config

ROOT = Path(__file__).resolve().parent.parent


def test_anomaly_seed_matches_generator():
    ds = build_dataset(load_config(ROOT / "generator" / "config.yaml"))
    expected = [{k: ("" if v is None else str(v)) for k, v in asdict(a).items()} for a in ds.anomalies]
    with open(ROOT / "dbt" / "seeds" / "anomalies_manifest.csv", encoding="utf-8", newline="") as fh:
        actual = list(csv.DictReader(fh))
    assert actual == expected, "Regenerate with: python -m generator.cli seed --dry-run, then copy out/dataset/anomalies.csv"
