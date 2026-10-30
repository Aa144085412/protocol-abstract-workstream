"""
Tests for the slot applicability decision tree + SlotTriageAgent.

Run: cd lab_agent_prototype && python -m pytest tests/test_slot_triage.py -q
"""

from tools import uncertainty_slots as us
from tools import slot_triage
from tools import value_promoter as vp
from agents.slot_triage_agent import SlotTriageAgent

CONFIRM = us.CONFIRM


def _proto():
    return {
        "protocol_title": "t", "materials": [],
        "workflow": [
            {"step_id": "plate", "step_number": 1, "title": "Plate cells",
             "instructions": ["Plate 2 million cells in a 10 cm dish."],
             "time_estimate": CONFIRM,
             "conditions": {"speed": CONFIRM, "temperature": CONFIRM}, "reagents": []},
            {"step_id": "spin", "step_number": 2, "title": "Pellet bacteria",
             "instructions": ["Centrifuge the culture to pellet the cells."],
             "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM}, "reagents": []},
            {"step_id": "inc", "step_number": 3, "title": "Incubate",
             "instructions": ["Incubate overnight."],
             "time_estimate": CONFIRM, "conditions": {"temperature": CONFIRM}, "reagents": []},
        ],
    }


def test_speed_on_plating_step_is_not_applicable():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:plate:cond:speed")
    t = slot_triage.triage_slot(p, o)
    assert t["decision"] == "not_applicable"
    assert t["auto_safe"] is True


def test_speed_on_spin_step_is_applicable():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:spin:cond:speed")
    assert slot_triage.triage_slot(p, o)["decision"] == "applicable"


def test_temperature_on_incubate_is_applicable():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:inc:cond:temperature")
    assert slot_triage.triage_slot(p, o)["decision"] == "applicable"


def test_temperature_on_plating_is_not_applicable():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:plate:cond:temperature")
    assert slot_triage.triage_slot(p, o)["decision"] == "not_applicable"


def test_auto_not_applicable_lists_clear_cases():
    p = _proto(); us.enumerate_slots(p)
    na = {t["slot_id"] for t in slot_triage.auto_not_applicable(p)}
    assert "step:plate:cond:speed" in na
    assert "step:plate:cond:temperature" in na
    assert "step:spin:cond:speed" not in na  # applicable
    assert "step:inc:cond:temperature" not in na


def test_agent_demo_matches_tree():
    p = _proto(); us.enumerate_slots(p)
    res = SlotTriageAgent().triage(p)   # DEMO -> deterministic
    dec = res["decisions"]
    assert dec["step:plate:cond:speed"]["decision"] == "not_applicable"
    assert dec["step:spin:cond:speed"]["decision"] == "applicable"


def test_triage_only_marks_na_safely_via_promoter():
    # simulate the bulk action: auto-mark not-applicable, must be reversible + audited
    p = _proto(); us.enumerate_slots(p)
    res = SlotTriageAgent().triage(p)
    for sid, d in res["decisions"].items():
        if d["decision"] == "not_applicable" and d["auto_safe"]:
            vp.mark_not_applicable(p, sid, "u@x.edu")
    o = us.get(p, "step:plate:cond:speed")
    assert o["status"] == "not_applicable"
    assert any(e["to_status"] == "not_applicable" for e in o["audit_trail"])
    # reversible
    vp.keep_unresolved(p, "step:plate:cond:speed", "u@x.edu")
    assert us.get(p, "step:plate:cond:speed")["status"] == "unresolved"
