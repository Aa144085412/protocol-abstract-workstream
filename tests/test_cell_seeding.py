"""Cell-seeding feasibility (infeasible when required density exceeds stock)."""
from tools.mol_tools import cell_seeding


def test_infeasible_when_stock_too_dilute():
    # need 1e6/mL but stock only 5e5/mL -> infeasible
    r = cell_seeding(200000, 200, 12, 500000)
    assert r.get("warning") and "infeasible" in r["warning"].lower()


def test_undiluted_when_equal():
    # density 1e6/mL == stock 1e6/mL -> undiluted, 0 medium, info note
    r = cell_seeding(200000, 200, 12, 1000000)
    assert abs(r["medium_to_add_uL"]) < 1 and "undiluted" in r["warning"].lower()


def test_normal_dilution_ok():
    r = cell_seeding(100000, 200, 12, 2000000)   # need 5e5/mL, stock 2e6/mL -> fine
    assert not r["warning"] and r["medium_to_add_uL"] > 0
