"""Helpers that inject data-quality problems on purpose.

Every injected problem is also written to an anomaly manifest (ground truth).
Later, dbt tests can check that the pipeline finds exactly what was planted.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Anomaly:
    anomaly_type: str
    object_type: str   # deal | invoice | payment | customer
    external_id: str   # id of the affected object in its own system
    related_deal_id: str | None
    detail: str


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def name_variant(name: str, rng: random.Random) -> str:
    """Return a messy but recognisable spelling of a company name.

    Mimics what happens when billing staff type the name by hand.
    """
    options = [
        lambda n: n.upper(),
        lambda n: strip_accents(n),
        lambda n: re.sub(r"\.", "", n),                                    # S.A. -> SA
        lambda n: re.sub(r"\s+(S\.A\.|S\.R\.L\.|S\.A\.S\.|S\.A\. de C\.V\.|Ltda\.)$", "", n),
        lambda n: strip_accents(n).lower().title().replace(".", ""),
    ]
    variant = rng.choice(options)(name)
    # Guarantee the variant is actually different from the original.
    return variant if variant != name else name.upper()


def weighted_sample(
    rng: random.Random, items: list, weights: list[float], k: int
) -> list:
    """Weighted sampling without replacement (Efraimidis-Spirakis method)."""
    if k <= 0 or not items:
        return []
    keyed = [
        (math.log(rng.random()) / w if w > 0 else -math.inf, item)
        for item, w in zip(items, weights)
    ]
    keyed.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in keyed[: min(k, len(items))]]
