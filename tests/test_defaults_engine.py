"""
Tests for the defaults engine (tools/defaults_engine): priority ladder, catalog
prefill with provenance, and that proposals stay labeled suggestions off the tree.

Run: cd lab_agent_prototype && python -m pytest tests/test_defaults_engine.py -q
"""

from tools import uncertainty_slots as us
from tools import defaults_engine as de
from tools import value_promoter as vp

CONFIRM = us.CONFIRM


def _digest_proto():
    return {"protocol_title": "clone", "assay_type": "cloning", "materials": [],
            "workflow": [{"step_id": "d1", "step_number": 1, "title": "Restriction digestion",
                          "instructions": ["Digest the plasmid with EcoRI in a 50 µL reaction."],
                          "time_estimate": CONFIRM, "conditions": {"temperature": CONFIRM},
                          "reagents": [{"item": "plasmid DNA", "amount": CONFIRM}]}]}


def _spin_proto():
    # empty title/assay => no kit-library match, so the typical tier is exercised
    return {"protocol_title": "", "assay_type": "", "materials": [],
            "workflow": [{"step_id": "s1", "step_number": 1, "title": "Pellet bacteria",
                          "instructions": ["Centrifuge to pellet the cells."],
                          "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM},
                          "reagents": []}]}


# ------------------------------- priority ladder -------------------------- #
def test_evidence_wins_over_catalog():
    p = _digest_proto(); us.enumerate_slots(p)
    o = us.get(p, "step:d1:reag:0:amount")
    src = {"source_text": "Use 800 ng of plasmid DNA for the digest."}
    rec = de.recommend(p, o, src)
    assert rec and rec["tier"] == "evidence"
    assert rec["proposed_status"] == "source_confirmed"
    assert "800 ng" in rec["value"]


def test_catalog_default_when_no_source():
    p = _digest_proto(); us.enumerate_slots(p)
    o = us.get(p, "step:d1:reag:0:amount")
    rec = de.recommend(p, o, {"source_text": ""})
    assert rec and rec["tier"] == "catalog"
    assert rec["proposed_status"] == "typical_range"          # suggested, not confirmed
    assert rec["inference_basis"] and rec["citation"]["company"] == "NEB"


def test_typical_when_no_catalog():
    p = _spin_proto(); us.enumerate_slots(p)
    o = us.get(p, "step:s1:cond:speed")
    rec = de.recommend(p, o, {"source_text": ""})
    assert rec and rec["tier"] == "typical"
    assert rec["proposed_status"] == "typical_range"


def test_none_when_nothing_applies():
    p = {"protocol_title": "x", "materials": [],
         "workflow": [{"step_id": "z", "step_number": 1, "title": "Label tubes",
                       "instructions": ["Label the tubes."], "time_estimate": CONFIRM,
                       "conditions": {"speed": CONFIRM}, "reagents": []}]}
    us.enumerate_slots(p)
    assert de.recommend(p, us.get(p, "step:z:cond:speed"), {"source_text": ""}) is None


# --------------------- prefill applies + stays tree-safe ------------------ #
def test_prefill_unresolved_applies_with_provenance():
    p = _digest_proto(); us.enumerate_slots(p)
    counts = de.prefill_unresolved(p, {"source_text": ""})
    assert counts["catalog"] >= 1
    o = us.get(p, "step:d1:reag:0:amount")
    assert o["status"] == "typical_range"                     # suggestion
    assert o.get("inference_basis")
    # tree-safety: the suggestion is NOT written as the protocol's value
    assert p["workflow"][0]["reagents"][0]["amount"] == CONFIRM
    # only a confirmation reaches the tree
    vp.user_confirm(p, "step:d1:reag:0:amount", "1 µg", "u@x.edu")
    assert p["workflow"][0]["reagents"][0]["amount"] == "1 µg"


def test_catalog_default_is_not_confirmed_status():
    p = _digest_proto(); us.enumerate_slots(p)
    de.prefill_unresolved(p, {"source_text": ""})
    o = us.get(p, "step:d1:reag:0:amount")
    assert o["status"] not in us.CONFIRMED                    # never auto-confirmed
