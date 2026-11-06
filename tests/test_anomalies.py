import random
from collections import Counter

from generator.anomalies import name_variant, strip_accents, weighted_sample


def test_name_variant_is_always_different():
    rng = random.Random(1)
    for name in ["Atlántico Farma Ltda.", "Sur Agro S.A.", "Delta Textil S.R.L."]:
        for _ in range(50):
            assert name_variant(name, rng) != name


def test_strip_accents():
    assert strip_accents("Logística Atlántico") == "Logistica Atlantico"


def test_weighted_sample_no_repeats_and_size():
    rng = random.Random(3)
    items = list(range(20))
    sample = weighted_sample(rng, items, [1.0] * 20, 5)
    assert len(sample) == 5 and len(set(sample)) == 5


def test_weighted_sample_prefers_heavier_items():
    rng = random.Random(5)
    hits = Counter()
    for _ in range(2000):
        hits.update(weighted_sample(rng, ["light", "heavy"], [1.0, 4.0], 1))
    assert hits["heavy"] > 3 * hits["light"]
