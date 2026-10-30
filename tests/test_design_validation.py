"""
Tests for goal-aware validation-assay design (offline) — the AI should design the readout
that proves the goal (e.g. anti-mCherry Western for P2A WT vs mutant), grounded in the doc.
Run: cd lab_agent_prototype && DEMO_MODE=true python -m pytest tests/test_design_validation.py -q
"""

import os
os.environ.setdefault("DEMO_MODE", "true")

from agents.experiment_design_agent import ExperimentDesignAgent


def test_p2a_reporter_validation_designed_from_doc():
    docs = [{"title": "construct notes",
             "text": "gene-P2A-mCherry. The P2A mutant is cleavage-dead so mCherry runs "
                     "larger as an uncleaved fusion; WT P2A gives free mCherry."}]
    d = ExperimentDesignAgent().design("validate P2A WT vs mutant", {}, docs)
    vas = d.get("validation_assays") or []
    assert vas, "expected a validation assay to be designed"
    top = vas[0]
    assert "western" in top["name"].lower() and "mcherry" in top["name"].lower()
    exp = top["expected_results"]
    # WT -> free reporter; mutant -> larger fusion
    joined = " ".join(str(v).lower() for v in exp.values())
    assert "free" in joined and ("fusion" in joined or "higher" in joined or "larger" in joined)
    # grounded in the uploaded doc
    assert "uploaded doc" in top["provenance"].lower()


def test_validation_flows_into_protocol_outline_and_readouts():
    docs = [{"title": "x", "text": "egfp reporter, P2A wild-type vs mutant cleavage"}]
    d = ExperimentDesignAgent().design("", {}, docs)
    stages = " ".join(s.get("stage", "") for s in d.get("protocol_outline", [])).lower()
    assert "western" in stages                      # validation appears as an outline stage
    assert any("western" in r.lower() for r in d.get("readouts", []))


def test_generic_validation_when_no_reporter():
    d = ExperimentDesignAgent().design("measure cell viability after drug X", {}, [])
    vas = d.get("validation_assays") or []
    assert vas and "validation" in vas[0]["name"].lower()
    assert vas[0]["provenance"] == "[domain knowledge]"
