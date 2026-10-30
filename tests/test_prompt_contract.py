"""
Prompt-contract tests + the end-to-end product-philosophy test.

The contract tests assert each agent prompt carries the uncertainty rules (so a
future edit cannot quietly drop them). The integration test encodes the whole
philosophy on the canonical example:

    Source says: "Spin the cells for 5 min."  (no speed stated)
    => time  -> source_confirmed (with quote)
       speed -> unresolved; a suggestion may be offered but stays unconfirmed
       readiness does NOT give full credit
       MethodsAgent writes the speed as "(specify)" / omits it, never the guess

Run: cd lab_agent_prototype && python -m pytest tests/test_prompt_contract.py -q
"""

import os

from tools import uncertainty_slots as us
from tools import evidence_resolver as er
from tools import suggest_value as sv
from tools import value_promoter as vp
from tools import readiness

CONFIRM = us.CONFIRM
PROMPTS = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _prompt(name):
    with open(os.path.join(PROMPTS, name), encoding="utf-8") as fh:
        return fh.read()


# ----------------------------- contract tests ------------------------------ #
def test_document_agent_prompt_requires_quotes_and_stubs():
    t = _prompt("document_agent.txt").lower()
    assert "source_quote" in t
    assert "uncertain_fields" in t and "expected_type" in t
    assert "not literally present" in t


def test_fill_agent_prompt_is_proposal_based():
    t = _prompt("fill_agent.txt")
    assert "evidence_class" in t
    assert "source_quote" in t
    assert "you propose, you do not confirm" in t.lower()
    assert "ai_suggested" in t and "typical_range" in t


def test_review_agent_prompt_catches_fake_certainty():
    t = _prompt("review_agent.txt").lower()
    assert "over-invention" in t
    assert "provenance" in t
    assert "contamination" in t


def test_revision_prompts_preserve_confirmed():
    for name in ("protocol_revision.txt", "protocol_correction.txt"):
        t = _prompt(name).lower()
        assert "user_confirmed" in t
        assert "overwrite" in t  # the "do not overwrite confirmed" rule


def test_methods_prompt_source_only_values():
    t = _prompt("methods_agent.txt")
    assert "(specify)" in t
    assert "source_confirmed" in t
    assert "evidence-backed" in t.lower()


# --------------------------- the philosophy test --------------------------- #
def _spin_proto():
    return {
        "protocol_title": "Cell spin", "assay_type": "prep",
        "materials": [],
        "workflow": [{
            "step_id": "s1", "step_number": 1, "title": "Spin cells",
            "instructions": ["Spin the cells."],
            "time_estimate": CONFIRM, "conditions": {"speed": CONFIRM},
            "reagents": [],
        }],
        "qc_checkpoints": [],
    }


SOURCE = "Resuspend, then spin the cells for 5 min. Discard the supernatant."


def test_philosophy_spin_5min_no_speed():
    p = _spin_proto()
    us.migrate_protocol(p)
    src = {"source_text": SOURCE}

    # 1) TIME is stated in source -> source_confirmed (with quote)
    t_obj = us.get(p, "step:s1:time")
    t_prop = er.best_proposal(t_obj, p, src)
    assert t_prop and t_prop["proposed_status"] == "source_confirmed"
    assert "5 min" in t_prop["value"]
    vp.auto_resolve(p, "step:s1:time", t_prop)
    t_obj = us.get(p, "step:s1:time")
    assert t_obj["status"] == "source_confirmed"
    assert t_obj["source_quote"] and "5 min" in t_obj["source_quote"]

    # 2) SPEED is NOT in source -> no evidence; stays unresolved
    s_obj = us.get(p, "step:s1:cond:speed")
    assert er.best_proposal(s_obj, p, src) is None
    assert s_obj["status"] == "unresolved"

    # 3) a suggestion MAY be offered, but it is NOT confirmed
    cands = sv.typical_candidates(p, s_obj)
    assert cands, "expected a typical centrifugation range for a spin step"
    vp.auto_resolve(p, "step:s1:cond:speed", cands[0])
    s_obj = us.get(p, "step:s1:cond:speed")
    assert s_obj["status"] == "typical_range"
    assert s_obj["status"] not in us.CONFIRMED

    # 4) tree honesty: confirmed time is written; the speed SUGGESTION is NOT in the tree
    assert CONFIRM not in str(p["workflow"][0]["time_estimate"])
    assert p["workflow"][0]["conditions"]["speed"] == CONFIRM

    # 5) readiness does NOT give full credit (one confirmed, one only-suggested)
    f1 = readiness._factor1_evidence(p)
    assert f1["ok"] is False and f1["points"] < 40
    assert readiness.compute_readiness(p)["level"] != "high"

    # 6) MethodsAgent never writes the guess; the speed value does not appear
    from agents.methods_agent import MethodsAgent
    md = MethodsAgent().write([{"protocol": p, "status": "worked", "title": "Cell spin"}])["markdown"]
    guess_number = cands[0]["value"].split("-")[0].split()[0]  # e.g. "3000"
    assert guess_number not in md, "a typical-range guess leaked into the Methods text"
    assert "5 min" in md  # the confirmed value is fine to report
