"""
Tests for the experimental-logic flow-gap detector.
Run: cd lab_agent_prototype && python -m pytest tests/test_flow_check.py -q
"""

from tools import flow_check


def _step(sid, title, instr, reagents=None):
    return {"step_id": sid, "title": title, "instructions": instr, "reagents": reagents or []}


def test_flags_missing_vector_digestion():
    proto = {"workflow": [
        _step("s1", "Digest PCR Products", ["Digest the PCR products with NheI and PciI."]),
        _step("s2", "Ligate", ["Ligate 25 ng cut vector with 25 ng insert and T4 ligase."]),
    ]}
    issues = " ".join(i["issue"] for i in flow_check.detect(proto)).lower()
    assert "vector digestion" in issues


def test_no_flag_when_vector_is_digested():
    proto = {"workflow": [
        _step("s1", "Digest vector and inserts",
              ["Digest the vector and PCR products with NheI and PciI; dephosphorylate vector."]),
        _step("s2", "Ligate", ["Ligate cut vector and insert with T4 ligase."]),
    ]}
    issues = " ".join(i["issue"] for i in flow_check.detect(proto)).lower()
    assert "vector digestion" not in issues


def test_flags_transduction_without_virus_production():
    proto = {"workflow": [
        _step("s1", "Miniprep", ["Miniprep plasmid from colonies."]),
        _step("s2", "Transduce K562", ["Add the lentivirus and polybrene to K562 cells."]),
    ]}
    issues = " ".join(i["issue"] for i in flow_check.detect(proto)).lower()
    assert "lentivirus production" in issues


def test_flags_validation_not_designed():
    proto = {"workflow": [
        _step("s1", "Validate Expression", ["Use Western blot to validate protein expression."]),
    ]}
    issues = " ".join(i["issue"] for i in flow_check.detect(proto)).lower()
    assert "isn't designed" in issues or "not designed" in issues


def test_designed_western_not_flagged():
    proto = {"workflow": [
        _step("s1", "Western blot",
              ["Lyse cells; SDS-PAGE; immunoblot with anti-mCherry 1:1000; expect band at 28 kDa."],
              reagents=[{"item": "anti-mCherry antibody"}]),
    ]}
    issues = " ".join(i["issue"] for i in flow_check.detect(proto)).lower()
    assert "designed" not in issues


def test_empty_protocol_no_gaps():
    assert flow_check.detect({"workflow": []}) == []


def test_apply_fixes_inserts_missing_steps():
    proto = {"workflow": [
        _step("s1", "Digest PCR Products", ["Digest the PCR products with NheI and PciI."]),
        _step("s2", "Ligate", ["Ligate 25 ng cut vector with insert and T4 ligase."]),
        _step("s3", "Miniprep", ["Miniprep plasmid from colonies."]),
        _step("s4", "Transduce K562", ["Add the lentivirus and polybrene to K562 cells."]),
    ]}
    changes = flow_check.apply_fixes(proto)
    kinds = {c["kind"] for c in changes}
    assert {"vector_digest", "virus_prod", "seq_verify"} <= kinds
    titles = [s["title"] for s in proto["workflow"]]
    assert "Digest and dephosphorylate the vector" in titles
    assert "Produce and harvest lentivirus" in titles
    assert "Sequence-verify the construct" in titles
    # steps renumbered sequentially and ids unique
    nums = [s["step_number"] for s in proto["workflow"]]
    assert nums == list(range(1, len(nums) + 1))
    assert len({s["step_id"] for s in proto["workflow"]}) == len(proto["workflow"])
    # idempotent: a second pass finds nothing new to insert
    assert flow_check.apply_fixes(proto) == []


def test_apply_fixes_designs_validation_in_place():
    proto = {"workflow": [
        _step("s1", "Validate Expression", ["Use Western blot to validate protein expression."]),
    ]}
    changes = flow_check.apply_fixes(proto)
    assert any(c["kind"] == "validation_undesigned" for c in changes)
    instr = " ".join(proto["workflow"][0]["instructions"]).lower()
    assert "sds-page" in instr and "antibody" in instr
