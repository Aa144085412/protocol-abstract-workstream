"""
Tests for the assay-gap detector (context-aware 'clarify to design').
Run: cd lab_agent_prototype && python -m pytest tests/test_assay_gaps.py -q
"""

from tools import assay_gaps


def test_detects_pcr_and_flags_gaps():
    proto = {"protocol_title": "PCR amplification",
             "workflow": [{"title": "Amplify with Q5 polymerase",
                           "instructions": ["Run PCR with Q5 polymerase, anneal 60 C"]}]}
    res = assay_gaps.detect(proto)
    names = {a["assay"] for a in res}
    assert "PCR / amplification" in names
    pcr = next(a for a in res if a["assay"] == "PCR / amplification")
    # annealing temp present (60 C / anneal); cycle number not stated -> a gap
    assert "annealing temperature" in pcr["present"]
    assert "cycle number" in pcr["gaps"]


def test_unrelated_protocol_has_no_assays():
    proto = {"protocol_title": "Make a buffer",
             "workflow": [{"title": "Dissolve salt", "instructions": ["Stir until dissolved"]}]}
    assert assay_gaps.detect(proto) == []


def test_cell_culture_detected():
    proto = {"protocol_title": "Transduce cells",
             "workflow": [{"title": "Plate cells",
                           "instructions": ["Seed cells in a 10 cm dish with media"]}]}
    names = {a["assay"] for a in assay_gaps.detect(proto)}
    assert "Cell culture / transduction" in names


def test_total_gaps_is_sum():
    proto = {"protocol_title": "PCR then ligation",
             "workflow": [{"title": "PCR then ligate",
                           "instructions": ["PCR with polymerase", "ligate insert with ligase"]}]}
    res = assay_gaps.detect(proto)
    assert assay_gaps.total_gaps(proto) == sum(len(a["gaps"]) for a in res)
