"""
Tests for the route-discovery layer: route_library detection (semantic, no
over-trigger), route_questions state machine + generation gating, and the
ContextDigestAgent demo. Includes the canonical 'plate MCF10A cells' example.

Run: cd lab_agent_prototype && python -m pytest tests/test_route_discovery.py -q
"""

from tools import route_library as rl
from tools import route_questions as rq
from agents.context_digest_agent import ContextDigestAgent


# ------------------------------- detection -------------------------------- #
def test_detect_plate_cells():
    hits = rl.detect_in_text("plate MCF10A cells for experiment tomorrow")
    fams = {h["route_family"] for h in hits}
    assert "cell_preparation_for_seeding" in fams
    h = next(h for h in hits if h["route_family"] == "cell_preparation_for_seeding")
    assert h["blocking_level"] == "must_ask_before_generation"
    assert len(h["routes"]) >= 3


def test_detect_is_semantic_not_keyword():
    # the exact word "plate" never appears, but meaning maps to cell prep
    hits = rl.detect_in_text("make cells ready for transfection tomorrow")
    assert any(h["route_family"] == "cell_preparation_for_seeding" for h in hits)


def test_detect_cleanup_and_extraction():
    assert any(h["route_family"] == "reaction_purification"
               for h in rl.detect_in_text("clean up the PCR"))
    assert any(h["route_family"] == "nucleic_acid_extraction"
               for h in rl.detect_in_text("extract RNA from the cells"))


def test_no_overtrigger_on_executable_step():
    assert rl.detect_in_text("Incubate at 37 C for 5 minutes.") == []
    assert rl.detect_in_text("Vortex briefly and spin down.") == []


def test_detect_in_protocol_attaches_step_id():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Plate cells", "instructions": ["Plate the cells into a 6-well."]},
        {"step_id": "s2", "title": "Incubate", "instructions": ["Incubate at 37 C overnight."]},
    ]}
    hits = rl.detect_in_protocol(proto)
    assert any(h["route_family"] == "cell_preparation_for_seeding" and h["step_id"] == "s1"
               for h in hits)


# ----------------------------- route_questions ---------------------------- #
def _proto_with_question():
    proto = {"workflow": [{"step_id": "s1", "title": "Plate cells",
                           "instructions": ["Plate the cells."]}]}
    hits = rl.detect_in_protocol(proto)
    rq.build_from_hits(proto, hits)
    return proto


def test_build_from_hits_idempotent():
    proto = _proto_with_question()
    n1 = len(rq.registry(proto))
    rq.build_from_hits(proto, rl.detect_in_protocol(proto))  # again
    assert len(rq.registry(proto)) == n1  # no duplicate family


def test_blocking_gate_then_unblock():
    proto = _proto_with_question()
    assert rq.safe_to_generate(proto) is False        # must-ask question open
    assert rq.blocking_unanswered(proto)
    qid = next(iter(rq.registry(proto)))
    opt = rq.registry(proto)[qid]["options"][1]["option_id"]
    rq.select_option(proto, qid, opt, "tester@x.edu")
    assert rq.get(proto, qid)["status"] == "selected"
    assert rq.get(proto, qid)["selected_option"] == opt
    assert rq.safe_to_generate(proto) is True         # unblocked after choice


def test_select_invalid_option_rejected():
    proto = _proto_with_question()
    qid = next(iter(rq.registry(proto)))
    try:
        rq.select_option(proto, qid, "not_a_real_route", "tester@x.edu")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_selected_route_resolves_option():
    proto = _proto_with_question()
    qid = next(iter(rq.registry(proto)))
    obj = rq.registry(proto)[qid]
    opt = obj["options"][0]["option_id"]
    rq.select_option(proto, qid, opt, "tester@x.edu")
    chosen = rq.selected_route(rq.get(proto, qid))
    assert chosen and chosen["option_id"] == opt
    assert "route_summary" in chosen


def test_audit_trail_records_creation_and_selection():
    proto = _proto_with_question()
    qid = next(iter(rq.registry(proto)))
    rq.select_option(proto, qid, rq.registry(proto)[qid]["options"][0]["option_id"], "u@x.edu")
    trail = rq.get(proto, qid)["audit_trail"]
    assert trail[0]["to_status"] == "needs_user_choice"
    assert any(e["to_status"] == "selected" for e in trail)


# --------------------------- ContextDigestAgent --------------------------- #
def test_digest_agent_demo_blocks_on_ambiguity():
    res = ContextDigestAgent().digest("plate MCF10A cells for experiment tomorrow")
    assert res["status"] == "success"
    assert res["safe_to_generate_protocol_now"] is False
    assert res["minimal_user_questions"]
    fams = {q["route_family"] for q in res["route_questions"]}
    assert "cell_preparation_for_seeding" in fams


def test_digest_agent_demo_executable_is_safe():
    res = ContextDigestAgent().digest("Incubate the plate at 37 C for 10 minutes.")
    assert res["route_questions"] == []
    assert res["safe_to_generate_protocol_now"] is True


def test_digest_to_route_questions_end_to_end():
    # the canonical example: digest -> store questions -> gate -> choose -> unblock
    proto = {"protocol_title": "Plate MCF10A", "workflow": [
        {"step_id": "s1", "title": "Plate cells", "instructions": ["Plate MCF10A cells."]}]}
    res = ContextDigestAgent().digest(protocol=proto)
    assert res["safe_to_generate_protocol_now"] is False
    rq.build_from_hits(proto, rl.detect_in_protocol(proto))
    assert not rq.safe_to_generate(proto)
    qid = next(iter(rq.registry(proto)))
    # user picks "existing adherent culture"
    rq.select_option(proto, qid, "passage_adherent_cells", "miao@ucsd.edu")
    assert rq.safe_to_generate(proto) is True
    chosen = rq.selected_route(rq.get(proto, qid))
    assert "trypsinize" in " ".join(chosen["route_summary"]).lower()
