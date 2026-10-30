"""
Tests for the bench-ready completeness score (distinct from evidence-confidence).
Run: cd lab_agent_prototype && python -m pytest tests/test_completeness.py -q
"""

from tools import uncertainty_slots as us
from tools import value_promoter as vp
from tools import readiness

CONFIRM = us.CONFIRM


def _proto():
    return {"protocol_title": "t", "materials": [], "workflow": [
        {"step_id": "s1", "step_number": 1, "title": "x", "instructions": ["x"],
         "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM, "temperature": CONFIRM},
         "reagents": [{"item": "buffer", "amount": CONFIRM}]}]}


def test_empty_is_zero_not_ready():
    p = _proto(); us.migrate_protocol(p)
    c = readiness.completeness(p)
    assert c["score"] == 0 and c["ready"] is False and c["total"] == 4


def test_filling_with_suggestions_reaches_ready():
    p = _proto(); us.migrate_protocol(p)
    for sid, o in list(us.registry(p).items()):
        if o["status"] == "unresolved":
            vp.apply(p, sid, "ai_suggested", "x", {"source_name": "agent"}, "system:agent")
    c = readiness.completeness(p)
    assert c["score"] == 100 and c["ready"] is True
    assert c["confirmed"] == 0 and c["to_confirm"] == 4   # filled but all still to verify


def test_evidence_confidence_stays_strict_while_complete():
    # completeness high, but evidence-weighted readiness Factor 1 stays low for AI-only
    p = _proto(); us.migrate_protocol(p)
    for sid, o in list(us.registry(p).items()):
        if o["status"] == "unresolved":
            vp.apply(p, sid, "ai_suggested", "x", {"source_name": "agent"}, "system:agent")
    f1 = readiness._factor1_evidence(p)
    assert f1["points"] < 10                      # AI-only earns almost no evidence credit
    assert readiness.completeness(p)["ready"] is True


def test_conflict_blocks_ready():
    p = _proto(); us.migrate_protocol(p)
    for sid, o in list(us.registry(p).items()):
        if o["status"] == "unresolved":
            vp.apply(p, sid, "ai_suggested", "x", {"source_name": "agent"}, "system:agent")
    sid0 = next(iter(us.registry(p)))
    vp.user_confirm(p, sid0, "v", "u@x.edu")
    vp.apply(p, sid0, "source_confirmed", "DIFFERENT",
             {"source_name": "uploaded", "source_quote": "q"}, "system:uploaded")  # -> conflict
    assert us.get(p, sid0)["status"] == "conflict"
    assert readiness.completeness(p)["ready"] is False
