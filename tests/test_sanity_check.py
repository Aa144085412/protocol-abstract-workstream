"""
Tests for the domain plausibility checker (Provenance 'check these' flags).
Run: cd lab_agent_prototype && python -m pytest tests/test_sanity_check.py -q
"""

from tools import sanity_check as sc


def _proto(slots):
    return {"uncertainty": {sid: {"slot_id": sid, "status": st, "field_name": fn,
                                  "current_value": v} for sid, fn, st, v in slots}}


def test_flags_impossible_temperature():
    p = _proto([("step:1:cond:temperature", "temperature", "user_confirmed", "9999 °C")])
    flags = sc.flag(p)
    assert len(flags) == 1 and "°C" in flags[0]["reason"]


def test_flags_absurd_centrifuge_speed():
    p = _proto([("step:1:cond:speed", "speed", "user_confirmed", "5,000,000 x g")])
    flags = sc.flag(p)
    assert flags and "centrifuge" in flags[0]["reason"]


def test_flags_negative_and_ph():
    p = _proto([("step:1:reag:0:amount", "amount", "user_confirmed", "-5 µL"),
                ("step:2:pH", "pH", "user_confirmed", "17")])
    reasons = {f["slot_id"]: f["reason"] for f in sc.flag(p)}
    assert "negative" in reasons["step:1:reag:0:amount"]
    assert "0–14" in reasons["step:2:pH"]


def test_normal_values_not_flagged():
    p = _proto([("step:1:cond:temperature", "temperature", "user_confirmed", "37 °C"),
                ("step:1:cond:speed", "speed", "user_confirmed", "12,000 x g"),
                ("step:1:reag:0:amount", "amount", "user_confirmed", "250 µL"),
                ("step:2:conc", "concentration", "ai_suggested", "10 ng/µL")])
    assert sc.flag(p) == []


def test_pcr_denaturation_temp_is_ok():
    # 98 °C is a real PCR denaturation temperature — must NOT be flagged
    p = _proto([("step:1:cond:temperature", "temperature", "user_confirmed", "98 °C")])
    assert sc.flag(p) == []


def test_flags_dna_amount_in_enzyme_units():
    p = {"materials": [{"item": "WT Skip dsDNA (synthesized)"}],
         "uncertainty": {"mat:0:amount": {"slot_id": "mat:0:amount", "status": "user_confirmed",
                                          "field_name": "amount", "current_value": "1 U"}}}
    flags = sc.flag(p)
    assert flags and "mass" in flags[0]["reason"].lower()


def test_polybrene_bare_volume_not_flagged_when_resolvable():
    # polybrene is in the known-reagent table -> auto-resolvable, so NO redundant flag
    p = {"materials": [{"item": "Polybrene (TR-1003-G)"}],
         "uncertainty": {"mat:0:amount": {"slot_id": "mat:0:amount", "status": "ai_suggested",
                                          "field_name": "amount", "recommended_candidate": "30 µL"}}}
    assert sc.flag(p) == []


def test_unknown_transfection_reagent_bare_volume_flagged():
    # an unknown transfection reagent as a bare volume is still flagged (not resolvable)
    p = {"materials": [{"item": "MysteryFect transfection reagent"}],
         "uncertainty": {"mat:0:amount": {"slot_id": "mat:0:amount", "status": "ai_suggested",
                                          "field_name": "amount", "recommended_candidate": "30 µL"}}}
    flags = sc.flag(p)
    assert flags and "concentration" in flags[0]["reason"].lower()


def test_enzyme_in_units_ok():
    p = {"materials": [{"item": "T4 DNA ligase"}],
         "uncertainty": {"mat:0:amount": {"slot_id": "mat:0:amount", "status": "user_confirmed",
                                          "field_name": "amount", "current_value": "2000 U"}}}
    assert sc.flag(p) == []


def test_skips_not_applicable_and_empty():
    p = {"uncertainty": {
        "a": {"slot_id": "a", "status": "not_applicable", "field_name": "x", "current_value": "-9"},
        "b": {"slot_id": "b", "status": "unresolved", "field_name": "x", "current_value": ""},
    }}
    assert sc.flag(p) == []
