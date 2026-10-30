"""
Tests for the consistency pass + vendor/catalog being suggestable.
Run: cd lab_agent_prototype && python -m pytest tests/test_consistency.py -q
"""

from tools import uncertainty_slots as us
from tools import value_promoter as vp
from tools import consistency

CONFIRM = us.CONFIRM


def _proto_two_media_steps():
    return {"protocol_title": "x", "materials": [], "workflow": [
        {"step_id": "a", "step_number": 1, "title": "Step A",
         "instructions": ["Add medium."], "time_estimate": CONFIRM, "conditions": {},
         "reagents": [{"item": "complete medium", "amount": CONFIRM}]},
        {"step_id": "b", "step_number": 2, "title": "Step B",
         "instructions": ["Add medium."], "time_estimate": CONFIRM, "conditions": {},
         "reagents": [{"item": "complete medium", "amount": CONFIRM}]}]}


def test_vendor_now_suggestable():
    # the only hard non-suggestable type is reagent_identity
    assert "vendor" not in us.NON_SUGGESTABLE_TYPES
    assert "catalog_number" not in us.NON_SUGGESTABLE_TYPES
    assert "reagent_identity" in us.NON_SUGGESTABLE_TYPES


def test_consistency_aligns_divergent_suggestions():
    p = _proto_two_media_steps(); us.enumerate_slots(p)
    # two different AI suggestions for the SAME reagent
    vp.apply(p, "step:a:reag:0:amount", "ai_suggested", "10 mL",
             {"source_name": "agent:Fill"}, "system:agent:Fill")
    vp.apply(p, "step:b:reag:0:amount", "ai_suggested", "2 mL",
             {"source_name": "agent:Fill"}, "system:agent:Fill")
    changes = consistency.normalize(p)
    a = us.get(p, "step:a:reag:0:amount")["recommended_candidate"]
    b = us.get(p, "step:b:reag:0:amount")["recommended_candidate"]
    assert a == b                                   # same reagent -> same suggested value
    assert changes                                  # at least one slot realigned


def test_consistency_propagates_confirmed_value():
    p = _proto_two_media_steps(); us.enumerate_slots(p)
    vp.user_confirm(p, "step:a:reag:0:amount", "5 mL", "u@x.edu")   # user pinned A
    vp.apply(p, "step:b:reag:0:amount", "ai_suggested", "12 mL",
             {"source_name": "agent:Fill"}, "system:agent:Fill")
    consistency.normalize(p)
    # A stays user-confirmed and untouched; B is aligned to A's value as a suggestion
    assert us.get(p, "step:a:reag:0:amount")["status"] == "user_confirmed"
    assert p["workflow"][0]["reagents"][0]["amount"] == "5 mL"
    assert us.get(p, "step:b:reag:0:amount")["recommended_candidate"] == "5 mL"
    assert us.get(p, "step:b:reag:0:amount")["status"] not in us.CONFIRMED


def test_consistency_skips_singletons():
    p = {"protocol_title": "x", "materials": [], "workflow": [
        {"step_id": "a", "step_number": 1, "title": "A", "instructions": ["x"],
         "time_estimate": CONFIRM, "conditions": {},
         "reagents": [{"item": "buffer EB", "amount": CONFIRM}]}]}
    us.enumerate_slots(p)
    vp.apply(p, "step:a:reag:0:amount", "ai_suggested", "30 µL",
             {"source_name": "agent:Fill"}, "system:agent:Fill")
    assert consistency.normalize(p) == []           # single occurrence -> nothing to align
