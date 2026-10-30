"""Reagent-to-step validation: relocate/flag reagents that don't belong on a step."""
from tools import reagent_placement as rp


def test_packaging_plasmid_moved_to_virus_step():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Sanger Sequencing Verification",
         "instructions": ["Send recombinant plasmids for Sanger sequencing."],
         "reagents": [{"item": "psPAX2 lentivirus plasmid"}, {"item": "pMD2.G lentivirus plasmid"}]},
        {"step_id": "s2", "title": "Lentivirus Production",
         "instructions": ["Transfect HEK293T cells and harvest viral supernatant."],
         "reagents": []},
    ]}
    moves = rp.apply(proto)
    s1 = proto["workflow"][0]["reagents"]
    s2 = {r["item"] for r in proto["workflow"][1]["reagents"]}
    assert all("pspax" not in r["item"].lower() for r in s1)   # moved off the sequencing step
    assert "psPAX2 lentivirus plasmid" in s2 and "pMD2.G lentivirus plasmid" in s2
    assert all(m["action"] == "moved" for m in moves)


def test_restriction_enzyme_stays_on_named_step():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Digest", "instructions": ["Digest with NheI-HF and PciI."],
         "reagents": [{"item": "NheI-HF restriction enzyme"}]},
    ]}
    assert rp.apply(proto) == []        # named in the step text -> left alone


def test_enzyme_flagged_when_no_fitting_step():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Plate cells", "instructions": ["Plate cells on agar."],
         "reagents": [{"item": "EcoRI restriction enzyme"}]},
    ]}
    moves = rp.apply(proto)
    assert moves and moves[0]["action"] == "flagged"
    assert any("doesn't fit" in n for n in proto["workflow"][0]["human_review_required"])


def test_unknown_reagent_untouched():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Mystery step", "instructions": ["Do something."],
         "reagents": [{"item": "Special Buffer X"}]},
    ]}
    assert rp.apply(proto) == []


def test_idempotent():
    proto = {"workflow": [
        {"step_id": "s1", "title": "Sequencing", "instructions": ["Sanger sequence."],
         "reagents": [{"item": "psPAX2"}]},
        {"step_id": "s2", "title": "Virus production", "instructions": ["Transfect and harvest virus."],
         "reagents": []},
    ]}
    rp.apply(proto)
    assert rp.apply(proto) == []        # second pass: nothing left to move
