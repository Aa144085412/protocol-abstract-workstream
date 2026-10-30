"""
Tests for the protocol dependency graph: reactive recompute, multi-level
propagation, vessel scaling, clamping, and locked-node conflicts.
Run: cd lab_agent_prototype && python -m pytest tests/test_protocol_graph.py -q
"""

import math
from tools import protocol_graph as pg


def _close(a, b, rel=1e-6):
    return isinstance(a, (int, float)) and math.isclose(a, b, rel_tol=rel)


# --------------------- cell-number dependency chain ----------------------- #
def _cell_graph():
    g = pg.DependencyGraph()
    g.add("lysis_volume", ["cells"], "linear", {"factor": 1e-4}, label="lysis volume (µL)")
    g.add("rna_yield", ["cells"], "linear", {"factor": 1e-3}, label="expected RNA yield (ng)")
    g.add("rt_input", ["rna_yield"], "clamp", {"lo": 10, "hi": 1000}, label="RT input (ng)")
    return g


def test_change_cells_propagates_multilevel():
    g = _cell_graph()
    values = {"cells": 5e5, "lysis_volume": 50, "rna_yield": 500, "rt_input": 500}
    out = pg.recompute(g, values, {"cells": 2e6})
    v = out["values"]
    assert _close(v["lysis_volume"], 200)        # 2e6 * 1e-4
    assert _close(v["rna_yield"], 2000)          # 2e6 * 1e-3
    assert _close(v["rt_input"], 1000)           # clamp(2000, 10, 1000) -> multilevel + clamp
    # every change explains itself
    slots = {c["slot"] for c in out["changes"]}
    assert {"lysis_volume", "rna_yield", "rt_input"} <= slots
    rt = next(c for c in out["changes"] if c["slot"] == "rt_input")
    assert "because" in rt["explanation"] and rt["trigger"] == "rna_yield"


def test_no_change_when_value_stable():
    g = _cell_graph()
    values = {"cells": 5e5, "lysis_volume": 50, "rna_yield": 500, "rt_input": 500}
    out = pg.recompute(g, values, {"cells": 5e5})   # same value
    assert out["changes"] == []


# ------------------------------ vessel chain ------------------------------ #
def _vessel_graph():
    g = pg.DependencyGraph()
    g.add("seeding", ["vessel"], "vessel_area",
          {"base_value": 7.5e6, "from_vessel": "T75"}, label="seeding number")
    g.add("media_mL", ["vessel"], "vessel_media", {}, label="media volume (mL)")
    return g


def test_vessel_change_rescales_seeding_and_media():
    g = _vessel_graph()
    values = {"vessel": "T75", "seeding": 7.5e6, "media_mL": 12.0}
    out = pg.recompute(g, values, {"vessel": "6-well"})
    v = out["values"]
    assert _close(v["seeding"], 7.5e6 * (9.6 / 75.0))   # area-scaled
    assert _close(v["media_mL"], 2.0)                   # 6-well working volume
    assert len(out["changes"]) == 2


# ------------------------------ locked nodes ------------------------------ #
def test_locked_node_raises_conflict_not_overwrite():
    g = _cell_graph()
    g.lock("rt_input")                              # user pinned RT input
    values = {"cells": 5e5, "lysis_volume": 50, "rna_yield": 500, "rt_input": 250}
    out = pg.recompute(g, values, {"cells": 2e6})
    assert out["values"]["rt_input"] == 250         # NOT overwritten
    assert any(c["slot"] == "rt_input" for c in out["conflicts"])
    conf = next(c for c in out["conflicts"] if c["slot"] == "rt_input")
    assert conf["proposed"] == 1000 and "locked" in conf["explanation"]


def test_dependents_helper():
    g = _cell_graph()
    assert set(pg.dependents(g, "cells")) == {"lysis_volume", "rna_yield"}
    assert pg.dependents(g, "rna_yield") == ["rt_input"]
