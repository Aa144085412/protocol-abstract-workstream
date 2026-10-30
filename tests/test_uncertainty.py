"""
Safety-invariant tests for the active-uncertainty layer.

Run:  cd lab_agent_prototype && python -m pytest tests/test_uncertainty.py -q
"""

import copy
import pytest

from tools import uncertainty_slots as us
from tools import value_promoter as vp
from tools import provenance_tracker as prov
from tools import readiness

CONFIRM = us.CONFIRM


def _proto():
    """Minimal protocol: one filled value (temp), one missing (speed), one missing
    material amount."""
    return {
        "protocol_title": "Bacterial pellet test",
        "protocol_version": "v1",
        "materials": [
            {"item": "LB medium", "amount": CONFIRM, "vendor": "", "catalog_number": ""},
        ],
        "workflow": [
            {
                "step_id": "step_01", "step_number": 1, "title": "Grow culture",
                "instructions": ["Inoculate and grow overnight."],
                "time_estimate": "overnight",
                "conditions": {"temperature": "37C", "speed": "", "other": ""},
                "reagents": [],
            },
            {
                "step_id": "step_02", "step_number": 2, "title": "Pellet bacteria",
                "instructions": ["Spin to pellet cells."],
                "time_estimate": CONFIRM,
                "conditions": {"temperature": "4C", "speed": CONFIRM, "other": ""},
                "reagents": [{"item": "culture", "amount": CONFIRM}],
            },
        ],
        "qc_checkpoints": [], "decision_points": [], "failure_branches": [],
        "open_questions_for_human": [],
    }


# --------------------------------------------------------------------------- #
def test_enumerate_creates_objects_and_statuses():
    p = _proto()
    reg = us.enumerate_slots(p)
    # a filled temp -> bootstrapped user_confirmed + legacy_imported
    temp = reg["step:step_01:cond:temperature"]
    assert temp["status"] == "user_confirmed"
    assert temp["legacy_imported"] is True
    # a missing speed -> unresolved
    spd = reg["step:step_02:cond:speed"]
    assert spd["status"] == "unresolved"
    assert spd["expected_type"] == "speed"
    assert spd["legacy_imported"] is False


def test_migration_idempotent():
    p = _proto()
    us.migrate_protocol(p)
    snap = copy.deepcopy(p["uncertainty"])
    us.migrate_protocol(p)            # second pass must not change statuses
    after = p["uncertainty"]
    for sid, obj in snap.items():
        assert after[sid]["status"] == obj["status"]
        assert after[sid]["legacy_imported"] == obj["legacy_imported"]


def test_migration_three_way_classification():
    p = _proto()
    us.migrate_protocol(p)
    reg = p["uncertainty"]
    assert reg["step:step_01:cond:temperature"]["status"] == "user_confirmed"   # filled, no quote
    assert reg["step:step_01:cond:temperature"]["legacy_imported"] is True
    assert reg["step:step_02:cond:speed"]["status"] == "unresolved"             # CONFIRM
    assert us.legacy_imported_count(p) >= 1


# --------------------------------------------------------------------------- #
def test_ai_suggestion_cannot_become_source_confirmed():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    vp.apply(p, sid, "ai_suggested", "3500 xg",
             {"evidence_class": "ai_suggested", "source_name": "agent:Fill Assistant"},
             "agent:Fill Assistant")
    # a model actor may NOT promote a guess to source_confirmed
    with pytest.raises(vp.PromotionError):
        vp.apply(p, sid, "source_confirmed", "3500 xg",
                 {"evidence_class": "source_confirmed", "source_name": "agent:Fill Assistant"},
                 "agent:Fill Assistant")


def test_typical_range_requires_user_actor_to_confirm():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    vp.apply(p, sid, "typical_range", "3000-4000 xg",
             {"evidence_class": "typical_range", "source_name": "tools/typical_values"},
             "system:tools/typical_values")
    # system actor cannot user_confirm
    with pytest.raises(vp.PromotionError):
        vp.apply(p, sid, "user_confirmed", "3000-4000 xg", None, "system:whatever")
    # explicit user can
    obj = vp.user_confirm(p, sid, "4000 xg", "tester@x.edu")
    assert obj["status"] == "user_confirmed"
    assert obj["current_value"] == "4000 xg"


def test_conflict_guard_no_silent_overwrite():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    vp.user_confirm(p, sid, "4000 xg", "tester@x.edu")
    # a later source proposing a DIFFERENT value must NOT overwrite -> conflict
    obj = vp.apply(p, sid, "source_confirmed", "5000 xg",
                   {"evidence_class": "source_confirmed", "source_name": "uploaded:newdoc.pdf",
                    "source_quote": "centrifuge at 5000 x g"},
                   "system:uploaded:newdoc.pdf")
    assert obj["status"] == "conflict"
    assert obj["current_value"] == "4000 xg"          # original preserved
    assert obj["recommended_candidate"] == "5000 xg"  # contested value visible


def test_same_value_evidence_does_not_conflict():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    vp.user_confirm(p, sid, "4000 xg", "tester@x.edu")
    obj = vp.apply(p, sid, "source_confirmed", "4000 xg",
                   {"evidence_class": "source_confirmed", "source_name": "uploaded:newdoc.pdf",
                    "source_quote": "4000 x g"}, "system:uploaded:newdoc.pdf")
    assert obj["status"] == "source_confirmed"


def test_illegal_transition_rejected():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    vp.user_confirm(p, sid, "4000 xg", "tester@x.edu")
    # a confirmed value cannot be downgraded to a suggestion tier
    with pytest.raises(vp.PromotionError):
        vp.apply(p, sid, "typical_range", "3000 xg", None, "system:x")
    with pytest.raises(vp.PromotionError):
        vp.apply(p, sid, "ai_suggested", "3000 xg", None, "system:x")


def test_audit_trail_grows_monotonically():
    p = _proto(); us.enumerate_slots(p)
    sid = "step:step_02:cond:speed"
    n0 = len(us.get(p, sid)["audit_trail"])
    vp.apply(p, sid, "typical_range", "3000-4000 xg",
             {"source_name": "tools/typical_values"}, "system:tools/typical_values")
    vp.user_confirm(p, sid, "4000 xg", "tester@x.edu")
    assert len(us.get(p, sid)["audit_trail"]) >= n0 + 2


# --------------------------------------------------------------------------- #
def test_readiness_ai_only_stays_low():
    p = _proto(); us.enumerate_slots(p)
    # make every unresolved slot only ai_suggested
    for sid, o in us.registry(p).items():
        if o["status"] == "unresolved":
            vp.apply(p, sid, "ai_suggested", "guess",
                     {"source_name": "agent:Fill Assistant"}, "agent:Fill Assistant")
    rd = readiness.compute_readiness(p)
    assert rd["level"] != "high"
    f1 = next(f for f in rd["factors"] if f["label"] == "Exact values filled")
    assert f1["points"] < 40 and f1["ok"] is False


def test_readiness_confirmed_earns_full_factor1():
    p = _proto(); us.enumerate_slots(p)
    for sid, o in list(us.registry(p).items()):
        if o["status"] != "user_confirmed":
            vp.user_confirm(p, sid, "x", "tester@x.edu")
    f1 = readiness._factor1_evidence(p)
    assert f1["ok"] is True
    assert f1["points"] == 40


def test_readiness_legacy_fallback_when_no_registry():
    p = _proto()  # no enumerate -> no "uncertainty" key
    rd = readiness.compute_readiness(p)
    f1 = next(f for f in rd["factors"] if f["label"] == "Exact values filled")
    assert 0 <= f1["points"] <= 40   # legacy formula still works


def test_conflict_penalizes_readiness():
    p = _proto(); us.enumerate_slots(p)
    # confirm everything, then force one high-risk conflict
    for sid, o in list(us.registry(p).items()):
        if o["status"] != "user_confirmed":
            vp.user_confirm(p, sid, "x", "tester@x.edu")
    clean = readiness._factor1_evidence(p)["points"]
    sid = "step:step_02:cond:speed"
    us.get(p, sid)["risk_level"] = "high"
    vp.apply(p, sid, "source_confirmed", "DIFFERENT",
             {"source_name": "uploaded:x", "source_quote": "q"}, "system:uploaded:x")
    assert us.get(p, sid)["status"] == "conflict"
    penalized = readiness._factor1_evidence(p)["points"]
    assert penalized < clean


# --------------------------------------------------------------------------- #
def test_carry_over_preserves_confirmed_and_history():
    old = _proto(); us.enumerate_slots(old)
    sid = "step:step_02:cond:speed"
    vp.user_confirm(old, sid, "4000 xg", "tester@x.edu")
    # simulate a revision: fresh protocol, same step ids, speed reset to CONFIRM
    new = _proto(); us.enumerate_slots(new)
    prov.carry_over(old, new)
    o = us.get(new, sid)
    assert o["status"] == "user_confirmed"     # confirmed value preserved
    assert o["current_value"] == "4000 xg"
    assert len(o["audit_trail"]) >= 2          # old history carried over


def test_carry_over_conflict_on_changed_confirmed():
    old = _proto(); us.enumerate_slots(old)
    sid = "step:step_01:cond:temperature"      # was user_confirmed 37C
    new = _proto(); us.enumerate_slots(new)
    # revision changed the confirmed temperature
    new["workflow"][0]["conditions"]["temperature"] = "42C"
    us.enumerate_slots(new)
    us.get(new, sid)["current_value"] = "42C"
    prov.carry_over(old, new)
    assert us.get(new, sid)["status"] == "conflict"
