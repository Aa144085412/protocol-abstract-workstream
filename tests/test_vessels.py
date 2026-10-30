"""
Tests for vessel geometry + context-aware scaling (tools/vessels).
Run: cd lab_agent_prototype && python -m pytest tests/test_vessels.py -q
"""

import math
from tools import vessels as ve


def _close(a, b, rel=1e-3):
    return a is not None and math.isclose(a, b, rel_tol=rel)


# ------------------------------- resolution ------------------------------- #
def test_resolve_flasks():
    assert ve.resolve("T75") == "t75"
    assert ve.resolve("t-75") == "t75"
    assert ve.resolve("75 cm2 flask") == "t75"
    assert ve.resolve("T175") == "t175"


def test_resolve_dishes():
    assert ve.resolve("10 cm dish") == "dish_10cm"
    assert ve.resolve("100 mm dish") == "dish_10cm"
    assert ve.resolve("6cm") == "dish_6cm"


def test_resolve_plates():
    assert ve.resolve("6-well") == "plate_6"
    assert ve.resolve("6 well plate") == "plate_6"
    assert ve.resolve("96-well plate") == "plate_96"
    assert ve.resolve("24w") == "plate_24"


def test_resolve_unknown():
    assert ve.resolve("petri thing") is None
    assert ve.get_vessel("nonsense") is None


# -------------------------------- scaling --------------------------------- #
def test_area_ratio_t75_to_6well():
    # T75 = 75 cm2, 6-well = 9.6 cm2/well
    r = ve.ratio("T75", "6-well", kind="area")
    assert _close(r, 9.6 / 75.0)


def test_scale_cell_number_down():
    # 7.5e6 cells in T75 -> seeding one 6-well well
    scaled = ve.scale(7.5e6, "T75", "6-well", kind="area")
    assert _close(scaled, 7.5e6 * (9.6 / 75.0))


def test_scale_media_volume_uses_working_volume():
    # media scales with working volume, not area
    scaled = ve.scale(12.0, "T75", "6-well", kind="volume")
    assert _close(scaled, 2.0)            # 6-well working volume is 2 mL


def test_scale_value_str_preserves_unit():
    out = ve.scale_value_str("12 mL", "T75", "6-well", kind="volume")
    assert out and "mL" in out and out.startswith("2")
    out2 = ve.scale_value_str("2.5×10^5 cells", "6-well", "T75", kind="area")
    assert out2 and "cells" in out2


def test_scale_unknown_vessel_returns_none():
    assert ve.scale(100, "T75", "nonsense", kind="area") is None
    assert ve.ratio("nope", "6-well") is None


# ----------------------------- recommendations ---------------------------- #
def test_recommend_seeding():
    r = ve.recommend_seeding("6-well", 5e4)     # 5e4 cells/cm2
    assert r and _close(r["cells"], 5e4 * 9.6)
    assert "6-well" in r["explanation"]


def test_recommend_media():
    r = ve.recommend_media("10 cm dish")
    assert r and _close(r["working_volume_mL"], 10.0)
