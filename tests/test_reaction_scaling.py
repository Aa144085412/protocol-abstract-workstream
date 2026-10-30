"""
Tests for per-reaction -> per-assay (master mix) scaling.
Run: cd lab_agent_prototype && python -m pytest tests/test_reaction_scaling.py -q
"""

from tools import reaction_scaling as rs


def test_scale_per_reaction_with_overage():
    # 10 µL/rxn × 8 × 1.1 = 88 µL
    assert rs.scale_per_reaction("10 µL", 8, 0.1) == "88 µL"


def test_scale_no_overage():
    assert rs.scale_per_reaction("5 µL", 4, 0.0) == "20 µL"


def test_scale_tidies_large_uL_to_mL():
    # 200 µL/rxn × 10 × 1.1 = 2200 µL -> 2.20 mL
    out = rs.scale_per_reaction("200 µL", 10, 0.1)
    assert out == "2.20 mL"


def test_scale_handles_non_numeric():
    assert rs.scale_per_reaction("overnight", 8) is None
    assert rs.scale_per_reaction("10 µL", 0) is None


def test_master_mix_table():
    comps = [{"name": "buffer", "per_rxn": "5 µL"}, {"name": "enzyme", "per_rxn": "1 µL"}]
    mm = rs.master_mix(comps, 6, 0.1)
    assert mm["n_reactions"] == 6 and mm["reactions_with_overage"] == 6.6
    buf = next(r for r in mm["rows"] if r["name"] == "buffer")
    assert buf["total"] == "33 µL"                 # 5 × 6 × 1.1
    enz = next(r for r in mm["rows"] if r["name"] == "enzyme")
    assert enz["total"] == "6.6 µL"                # 1 × 6 × 1.1
    assert "overage" in mm["note"]
