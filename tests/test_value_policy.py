"""
Tests for the propose-and-label value policy: risk tiering of high-impact fields,
common-practice default suggestions, and that suggestions stay labeled (never
written into the protocol tree as source values).

Run: cd lab_agent_prototype && python -m pytest tests/test_value_policy.py -q
"""

from tools import uncertainty_slots as us
from tools import suggest_value as sv
from tools import value_promoter as vp
from tools import typical_values

CONFIRM = us.CONFIRM


def _proto(title, instr):
    return {"protocol_title": "t", "materials": [],
            "workflow": [{"step_id": "s1", "step_number": 1, "title": title,
                          "instructions": [instr], "time_estimate": CONFIRM,
                          "conditions": {"temperature": CONFIRM, "speed": CONFIRM},
                          "reagents": [{"item": "x", "amount": CONFIRM}]}]}


# ----------------------------- risk tiering ------------------------------- #
def test_high_impact_step_is_high_risk():
    p = _proto("Tagmentation", "Tagment nuclei with pAG-Tn5 for the tagmentation time.")
    us.enumerate_slots(p)
    # the time field on a tagmentation step is high risk (can ruin the run)
    assert us.get(p, "step:s1:time")["risk_level"] == "high"


def test_moi_step_is_high_risk():
    p = _proto("Transduce", "Add lentivirus at the target MOI to the cells.")
    us.enumerate_slots(p)
    assert us.get(p, "step:s1:reag:0:amount")["risk_level"] == "high"


def test_routine_step_not_forced_high():
    p = _proto("Wash cells", "Wash the cells with PBS.")
    us.enumerate_slots(p)
    # a plain wash temperature is not high-impact -> stays medium (its default)
    assert us.get(p, "step:s1:cond:temperature")["risk_level"] in ("medium", "low")


# ------------------- common-practice default suggestions ------------------ #
def test_mammalian_incubation_default_suggested():
    p = _proto("Recover cells", "Culture the MCF7 cells and incubate to recover.")
    us.enumerate_slots(p)
    cands = sv.typical_candidates(p, us.get(p, "step:s1:cond:temperature"))
    assert cands, "expected a 37 C mammalian incubation default"
    assert "37" in cands[0]["value"]
    assert cands[0]["proposed_status"] == "typical_range"


def test_culture_default_in_typical_values():
    out = typical_values.suggest_for_text("incubate MCF7 mammalian cells to recover")
    assert any("37" in str(s.get("typical")) for s in out)


# ----------------- suggestions stay labeled, off the tree ----------------- #
def test_suggested_default_not_written_to_tree():
    p = _proto("Recover cells", "Culture MCF7 cells and incubate.")
    us.enumerate_slots(p)
    sid = "step:s1:cond:temperature"
    cands = sv.typical_candidates(p, us.get(p, sid))
    vp.auto_resolve(p, sid, cands[0])
    o = us.get(p, sid)
    assert o["status"] == "typical_range"            # labeled as a suggestion
    assert o["recommended_candidate"] and "37" in o["recommended_candidate"]
    # tree-safety: the suggestion is NOT written as the protocol's value
    assert p["workflow"][0]["conditions"]["temperature"] == CONFIRM
    # only a user/source/kit/calc confirmation reaches the tree
    vp.user_confirm(p, sid, "37 C, 5% CO2", "u@x.edu")
    assert p["workflow"][0]["conditions"]["temperature"] == "37 C, 5% CO2"
