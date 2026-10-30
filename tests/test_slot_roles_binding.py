"""
Tests for semantic-role tagging + live vessel binding.
Run: cd lab_agent_prototype && python -m pytest tests/test_slot_roles_binding.py -q
"""

from tools import uncertainty_slots as us
from tools import slot_roles
from tools import protocol_binding as pb

CONFIRM = us.CONFIRM


def _proto():
    return {"protocol_title": "culture", "materials": [], "workflow": [
        {"step_id": "s1", "step_number": 1, "title": "Seed cells",
         "instructions": ["Add growth medium and seed cells; wash with PBS."],
         "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM, "temperature": CONFIRM},
         "reagents": [{"item": "complete growth medium", "amount": CONFIRM},
                      {"item": "PBS", "amount": CONFIRM}]}]}


# ------------------------------- role tagging ----------------------------- #
def test_roles_detected():
    p = _proto(); us.enumerate_slots(p); slot_roles.tag_roles(p)
    assert us.get(p, "step:s1:reag:0:amount")["role"] == "media_volume"
    assert us.get(p, "step:s1:reag:1:amount")["role"] == "wash_volume"
    assert us.get(p, "step:s1:cond:speed")["role"] == "spin_speed"
    assert us.get(p, "step:s1:cond:temperature")["role"] == "incubation_temp"
    assert us.get(p, "step:s1:time")["role"] == "duration"


def test_slots_with_role_helper():
    p = _proto(); us.enumerate_slots(p); slot_roles.tag_roles(p)
    assert len(slot_roles.slots_with_role(p, "media_volume")) == 1


# ----------------------------- vessel binding ----------------------------- #
def test_plan_rescale_proposes_media_volume():
    p = _proto(); us.enumerate_slots(p)
    plan = pb.plan_rescale_to_vessel(p, "6-well")
    media = [c for c in plan if c["role"] == "media_volume"]
    assert media and media[0]["new"].startswith("2")        # 6-well working volume 2 mL
    assert "6-well" in media[0]["explanation"]


def test_apply_rescale_writes_recomputed_suggestions():
    p = _proto(); us.enumerate_slots(p)
    pb.apply_rescale_to_vessel(p, "6-well", "tester@x.edu")
    o = us.get(p, "step:s1:reag:0:amount")
    assert o["status"] == "typical_range"                   # recomputed suggestion, not confirmed
    assert o["recommended_candidate"].startswith("2")
    # tree-safety: the auto-scaled suggestion is NOT written into the protocol
    assert p["workflow"][0]["reagents"][0]["amount"] == CONFIRM


def test_apply_rescale_skips_user_confirmed():
    from tools import value_promoter as vp
    p = _proto(); us.enumerate_slots(p)
    vp.user_confirm(p, "step:s1:reag:0:amount", "10 mL", "tester@x.edu")   # user pinned it
    changes = pb.apply_rescale_to_vessel(p, "6-well", "tester@x.edu")
    media = next(c for c in changes if c["slot_id"] == "step:s1:reag:0:amount")
    assert media.get("skipped")                              # confirmed value left unchanged
    assert p["workflow"][0]["reagents"][0]["amount"] == "10 mL"


def test_apply_rescale_does_not_crash_on_legacy_confirmed():
    """A legacy-imported confirmed value (concrete tree value, no source) must be
    skipped gracefully, not raise PromotionError (user_confirmed -> typical_range)."""
    p = _proto()
    p["workflow"][0]["reagents"][0]["amount"] = "12 mL"      # concrete value already in tree
    us.enumerate_slots(p)                                    # -> user_confirmed, legacy_imported
    o = us.get(p, "step:s1:reag:0:amount")
    assert o["status"] == "user_confirmed" and o.get("legacy_imported")
    changes = pb.apply_rescale_to_vessel(p, "6-well", "tester@x.edu")   # must not raise
    media = next(c for c in changes if c["slot_id"] == "step:s1:reag:0:amount")
    assert media.get("skipped")
    assert p["workflow"][0]["reagents"][0]["amount"] == "12 mL"   # value preserved


# -------------------- cell-number cascade (lysis / RNA) -------------------- #
def _lysis_proto():
    return {"protocol_title": "rna", "materials": [], "workflow": [
        {"step_id": "L", "step_number": 1, "title": "Lyse cells",
         "instructions": ["Add lysis buffer to the pelleted cells."],
         "time_estimate": CONFIRM, "conditions": {},
         "reagents": [{"item": "lysis buffer", "amount": CONFIRM}]}]}


def test_lysis_role_detected():
    p = _lysis_proto(); us.enumerate_slots(p); slot_roles.tag_roles(p)
    assert us.get(p, "step:L:reag:0:amount")["role"] == "lysis_volume"


def test_cell_number_cascade_sets_lysis_volume():
    p = _lysis_proto(); us.enumerate_slots(p)
    changes = pb.apply_rescale_to_cells(p, "1e6", "tester@x.edu")
    assert changes and changes[0]["role"] == "lysis_volume"
    o = us.get(p, "step:L:reag:0:amount")
    assert o["status"] == "typical_range" and o["recommended_candidate"].startswith("100")
    assert p["workflow"][0]["reagents"][0]["amount"] == CONFIRM   # tree-safe


def test_rna_yield_estimate():
    est = pb.estimate_rna_yield("1e6")
    assert est and "µg" in est["display"]                  # 1e6 * 0.015 ng = 15 µg
    assert "estimate" in est["explanation"]
    assert pb.estimate_rna_yield("not a number") is None
