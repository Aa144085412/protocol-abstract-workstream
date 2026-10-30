"""
Tests for the knowledge-sources tier in evidence_resolver: a broker (PDF manual)
supplies a cited value for an unresolved slot, mapped to the right status.
Inert when no broker / disabled. Run:
  cd lab_agent_prototype && python -m pytest tests/test_evidence_knowledge_tier.py -q
"""

import pytest

import knowledge_sources as ks
from knowledge_sources import cache
from knowledge_sources.pdf_manual_provider import PDFManualProvider
from tools import uncertainty_slots as us
from tools import evidence_resolver as er

CONFIRM = us.CONFIRM
_MANUAL = ("QIAprep Spin Miniprep. To elute, add 50 µL Buffer EB to the column "
           "and centrifuge at 17,900 x g for 1 min.")


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "_DIR", str(tmp_path / "kcache"))


def _proto():
    return {"protocol_title": "miniprep", "assay_type": "", "materials": [],
            "workflow": [{"step_id": "e1", "step_number": 1, "title": "Elute DNA",
                          "instructions": ["Elute the DNA from the column."],
                          "time_estimate": CONFIRM,
                          "conditions": {"other": ""},
                          "reagents": [{"item": "Buffer EB", "amount": CONFIRM}]}]}


def _broker():
    p = PDFManualProvider()
    p.add_manual(_MANUAL, title="QIAprep Spin Miniprep", company="QIAGEN",
                 product="QIAprep Spin Miniprep", catalog_number="27104")
    return ks.KnowledgeBroker(providers=[p], enabled=True)


def test_inert_without_broker():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:e1:reag:0:amount")
    assert er.from_knowledge_sources(p, o, broker=None) == []
    # disabled broker also inert
    disabled = ks.KnowledgeBroker(providers=[PDFManualProvider()], enabled=False)
    assert er.from_knowledge_sources(p, o, broker=disabled) == []


def test_manual_supplies_cited_value():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:e1:reag:0:amount")     # expected_type material_amount (vol/mass)
    props = er.from_knowledge_sources(p, o, broker=_broker())
    assert props
    assert any("50" in pr["value"] for pr in props)
    pr = props[0]
    assert pr["proposed_status"] == "kit_confirmed"            # vendor_spec -> kit_confirmed
    assert pr["evidence"]["source_name"] == "knowledge:pdf_manual"


def test_best_proposal_uses_broker_tier():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:e1:reag:0:amount")
    best = er.best_proposal(o, p, {"source_text": ""}, broker=_broker())
    assert best and best["proposed_status"] == "kit_confirmed" and "50" in best["value"]


def test_source_still_beats_knowledge_tier():
    p = _proto(); us.enumerate_slots(p)
    o = us.get(p, "step:e1:reag:0:amount")
    src = {"source_text": "Elute the DNA in 30 µL of Buffer EB."}
    best = er.best_proposal(o, p, src, broker=_broker())
    assert best["proposed_status"] == "source_confirmed" and "30" in best["value"]
