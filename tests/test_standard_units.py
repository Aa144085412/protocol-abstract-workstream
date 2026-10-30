"""
Tests for the standardization core (tools/standard_units).
Run: cd lab_agent_prototype && python -m pytest tests/test_standard_units.py -q
"""

import math
from tools import standard_units as su


def _close(a, b, rel=1e-6):
    return a is not None and b is not None and math.isclose(a, b, rel_tol=rel)


# ----------------------------- number parsing ----------------------------- #
def test_parse_plain_and_scientific():
    assert _close(su.parse_number("250"), 250)
    assert _close(su.parse_number("1.5"), 1.5)
    assert _close(su.parse_number("2.5e5"), 250000)
    assert _close(su.parse_number("1,000"), 1000)


def test_parse_times_ten_notation():
    assert _close(su.parse_number("2.5 × 10^5"), 250000)
    assert _close(su.parse_number("2.5x10^5"), 250000)
    assert _close(su.parse_number("1 × 10^6"), 1_000_000)


def test_parse_superscript_notation():
    assert _close(su.parse_number("2.5×10⁵"), 250000)
    assert _close(su.parse_number("1×10⁶"), 1_000_000)


# ------------------------------- quantities ------------------------------- #
def test_mass_to_canonical_ng():
    assert _close(su.to_canonical("1.5 µg"), 1500)         # 1.5 µg = 1500 ng
    assert _close(su.to_canonical("5 mg"), 5e6)
    q = su.parse_quantity("250 ng")
    assert q.dimension == "mass" and q.canonical_unit == "ng" and _close(q.canonical_value, 250)


def test_volume_to_canonical_uL():
    assert _close(su.to_canonical("2 mL"), 2000)
    assert _close(su.to_canonical("250 µL"), 250)
    assert _close(su.to_canonical("0.5 L"), 500000)


def test_molarity():
    assert _close(su.to_canonical("2 µM"), 2e-6)
    assert _close(su.convert(1, "M", "mM"), 1000)


def test_count_cells_scientific():
    q = su.parse_quantity("2.5 × 10^5 cells")
    assert q and q.dimension == "count"
    assert _close(q.canonical_value, 250000)
    assert _close(su.to_canonical("1×10⁶ cells"), 1_000_000)


def test_temperature():
    q = su.parse_quantity("37 °C")
    assert q and q.dimension == "temperature" and _close(q.canonical_value, 37)


def test_enzyme_units():
    q = su.parse_quantity("20 U")
    assert q and q.dimension == "enzyme" and _close(q.canonical_value, 20)


# ----------------------------- concentration ------------------------------ #
def test_concentration_canonical_ng_per_uL():
    assert _close(su.to_canonical("10 ng/µL"), 10)
    assert _close(su.to_canonical("1 µg/µL"), 1000)        # 1 µg/µL = 1000 ng/µL
    assert _close(su.to_canonical("1 µg/mL"), 1)           # 1 µg/mL = 1 ng/µL
    assert _close(su.to_canonical("500 ng/mL"), 0.5)       # 500 ng/mL = 0.5 ng/µL


def test_convert_within_dimension():
    assert _close(su.convert(1500, "ng", "µg"), 1.5)
    assert _close(su.convert(2, "mL", "µL"), 2000)
    assert su.convert(1, "ng", "µL") is None               # cross-dimension -> None


def test_same_dimension():
    assert su.same_dimension("ng", "mg") is True
    assert su.same_dimension("µL", "mL") is True
    assert su.same_dimension("ng/µL", "µg/mL") is True
    assert su.same_dimension("ng", "µL") is False


def test_unparseable_returns_none():
    assert su.parse_quantity("overnight") is None
    assert su.to_canonical("room temperature") is None
