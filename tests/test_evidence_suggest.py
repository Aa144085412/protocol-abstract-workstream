"""
Tests for evidence_resolver (tiers 1-3,5) and suggest_value (tiers 6-7).

Run:  cd lab_agent_prototype && python -m pytest tests/test_evidence_suggest.py -q
"""

import pytest

from tools import uncertainty_slots as us
from tools import evidence_resolver as er
from tools import suggest_value as sv
from tools import value_promoter as vp
from tools import readiness

CONFIRM = us.CONFIRM


def _proto():
    return {
        "protocol_title": "Bacterial pellet", "assay_type": "prep",
        "materials": [{"item": "LB medium", "amount": CONFIRM, "vendor": CONFIRM,
                       "catalog_number": CONFIRM}],
        "workflow": [{
            "step_id": "s1", "step_number": 1, "title": "Pellet bacteria",
            "instructions": ["Centrifuge the culture to pellet the cells."],
            "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM, "temperature": CONFIRM},
            "reagents": [],
        }],
    }


SRC = ("Grow the culture overnight. Centrifuge at 4000 x g for 5 minutes to "
       "pellet the bacteria, then discard the supernatant.")


def _obj(p, sid):
    us.enumerate_slots(p)
    return us.get(p, sid)


# --------------------------- evidence_resolver ----------------------------- #
def test_source_quote_found():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    props = er.from_source(p, o, SRC)
    assert props and props[0]["proposed_status"] == "source_confirmed"
    assert "4000 x g" in props[0]["value"]
    assert "centrifuge" in props[0]["evidence"]["source_quote"].lower()
    assert props[0]["evidence"]["source_location"]["char"] >= 0


def test_source_no_context_match():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    # a speed value in unrelated text (no step context nearby) is NOT claimed
    props = er.from_source(p, o, "The elevator descends at 1500 rpm in the lobby.")
    assert props == []


def test_resolve_orders_source_before_reference():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    props = er.resolve_slot(o, p, {"source_text": SRC, "reference_text": SRC})
    assert props[0]["proposed_status"] == "source_confirmed"
    assert any(pr["proposed_status"] == "literature_supported" for pr in props)


def test_best_proposal_none_when_empty():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    assert er.best_proposal(o, p, {"source_text": "", "reference_text": ""}) is None


def test_vendor_not_resolvable():
    p = _proto()
    o = _obj(p, "mat:0:vendor")
    assert er.resolve_slot(o, p, {"source_text": "QIAGEN sells LB medium"}) == []


def test_evidence_feeds_promoter_to_source_confirmed():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    prop = er.best_proposal(o, p, {"source_text": SRC})
    vp.auto_resolve(p, "step:s1:cond:speed", prop)
    obj = us.get(p, "step:s1:cond:speed")
    assert obj["status"] == "source_confirmed"
    assert obj["source_quote"]
    # confirmed evidence -> written into the tree
    assert "4000 x g" in p["workflow"][0]["conditions"]["speed"]


# ----------------------------- suggest_value ------------------------------- #
def test_typical_candidates_dimension_matched():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    cands = sv.typical_candidates(p, o)
    assert cands and cands[0]["proposed_status"] == "typical_range"
    assert us.dimension_ok("speed", cands[0]["value"]) is True


def test_typical_not_for_vendor():
    p = _proto()
    o = _obj(p, "mat:0:vendor")
    assert sv.typical_candidates(p, o) == []


class _FakeFill:
    name = "Fake Fill"

    def __init__(self, value):
        self._value = value

    def suggest(self, proto, slots, context="", source_text=""):
        return {"suggestions": {slots[0]["id"]: self._value}}


def test_ai_candidate_tagged_unconfirmed():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")
    prop = sv.ai_candidate(p, o, _FakeFill("3500 x g"))
    assert prop["proposed_status"] == "ai_suggested"
    assert prop["evidence"]["confidence"] <= 0.4


def test_ai_candidate_wrong_dimension_dropped():
    p = _proto()
    o = _obj(p, "step:s1:cond:speed")          # speed slot
    assert sv.ai_candidate(p, o, _FakeFill("5 minutes")) is None   # a time, not a speed


def test_ai_candidate_now_suggests_vendor():
    # policy update: vendor/catalog ARE suggestable (labeled ai_suggested, to verify);
    # only reagent_identity is never invented.
    p = _proto()
    o = _obj(p, "mat:0:vendor")
    prop = sv.ai_candidate(p, o, _FakeFill("QIAGEN"))
    assert prop and prop["proposed_status"] == "ai_suggested" and prop["value"] == "QIAGEN"


def test_ai_suggestion_earns_almost_no_readiness():
    p = _proto()
    us.enumerate_slots(p)
    # promote every unresolved slot to ai_suggested
    for sid, ob in list(us.registry(p).items()):
        if ob["status"] == "unresolved":
            prop = sv.ai_candidate(p, ob, _FakeFill("x")) or {
                "value": "x", "proposed_status": "ai_suggested",
                "evidence": {"evidence_class": "ai_suggested", "source_name": "agent:Fake", "confidence": 0.3}}
            try:
                vp.auto_resolve(p, sid, prop)
            except vp.PromotionError:
                pass
    rd = readiness.compute_readiness(p)
    assert rd["level"] != "high"
