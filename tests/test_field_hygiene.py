"""Deterministic clean-up of parse artifacts (temp-in-time, leaked storage temp, dup amounts)."""
from tools import field_hygiene as fh

CONFIRM = fh.CONFIRM


def test_temperature_in_time_field_moved_out():
    p = {"workflow": [{"step_id": "s1", "title": "PCR", "instructions": ["Run PCR."],
                       "time_estimate": "95-98 °C, 30 s-3 min", "conditions": {}}]}
    fh.clean(p)
    s = p["workflow"][0]
    assert s["time_estimate"] == CONFIRM
    assert any("95-98" in i for i in s["instructions"])


def test_storage_temp_blanked_on_reaction_step():
    p = {"workflow": [{"step_id": "s1", "title": "PCR amplification",
                       "instructions": ["Amplify the gene."],
                       "time_estimate": CONFIRM, "conditions": {"temperature": "-20"}}]}
    fh.clean(p)
    assert p["workflow"][0]["conditions"]["temperature"] == CONFIRM


def test_storage_temp_kept_on_storage_step():
    p = {"workflow": [{"step_id": "s1", "title": "Store plasmids",
                       "instructions": ["Store the minipreps at -20 °C."],
                       "time_estimate": CONFIRM, "conditions": {"temperature": "-20 °C"}}]}
    fh.clean(p)
    assert p["workflow"][0]["conditions"]["temperature"] == "-20 °C"   # legit storage temp kept


def test_amount_depropagated_across_reagents():
    rg = lambda item: {"item": item, "amount": "159 ng"}
    p = {"workflow": [{"step_id": "s1", "title": "Digest", "instructions": ["Digest."],
                       "reagents": [rg("NheI-HF"), rg("PciI"), rg("rSAP"), rg("NEBuilder")],
                       "conditions": {}, "time_estimate": CONFIRM}]}
    fh.clean(p)
    amts = [r["amount"] for r in p["workflow"][0]["reagents"]]
    assert all(a == CONFIRM for a in amts)   # 159 ng on 4 different reagents -> all blanked


def test_legit_unique_amount_kept():
    p = {"workflow": [{"step_id": "s1", "title": "Digest", "instructions": ["Digest vector."],
                       "reagents": [{"item": "vector", "amount": "1 µg"}],
                       "conditions": {}, "time_estimate": CONFIRM}]}
    fh.clean(p)
    assert p["workflow"][0]["reagents"][0]["amount"] == "1 µg"


def test_real_duration_kept():
    p = {"workflow": [{"step_id": "s1", "title": "Incubate", "instructions": ["Wait."],
                       "time_estimate": "30 minutes", "conditions": {}}]}
    fh.clean(p)
    assert p["workflow"][0]["time_estimate"] == "30 minutes"
