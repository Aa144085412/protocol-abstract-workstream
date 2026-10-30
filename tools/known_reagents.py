"""
known_reagents
==============
Standard WORKING concentrations for common RAW reagents (chemicals/antibiotics/transduction
enhancers) — NOT products, kits, or plasmids. These are textbook-standard values a bench
scientist expects, so the agent can fill them as typical suggestions instead of leaving a
blank or a meaningless volume (e.g. polybrene as "30 µL").

Deliberately conservative and raw-reagent only. Anything cell-line- or titration-dependent
is labelled so. No catalog numbers, no vendors — those are product details, not reagent facts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# each entry: keywords (any match, lowercase substring) -> working concentration + note
RAW_REAGENTS: List[Dict[str, Any]] = [
    # transduction / transfection enhancers (raw chemicals)
    {"kw": ["polybrene", "hexadimethrine"], "working": "8 µg/mL",
     "note": "final, in medium during transduction (typical 4–10 µg/mL; titrate for toxicity)"},
    {"kw": ["protamine sulfate"], "working": "10 µg/mL",
     "note": "final, transduction enhancer alternative to polybrene"},
    # selection antibiotics (mammalian — titrate with a kill curve)
    {"kw": ["puromycin"], "working": "1–2 µg/mL", "note": "mammalian selection — titrate (kill curve)"},
    {"kw": ["blasticidin"], "working": "5–10 µg/mL", "note": "mammalian selection — titrate"},
    {"kw": ["geneticin", "g418"], "working": "400–800 µg/mL", "note": "mammalian selection — titrate"},
    {"kw": ["hygromycin"], "working": "100–200 µg/mL", "note": "mammalian selection — titrate"},
    {"kw": ["zeocin"], "working": "100–400 µg/mL", "note": "mammalian selection — titrate"},
    # bacterial selection antibiotics (standard working concentrations)
    {"kw": ["ampicillin", "carbenicillin"], "working": "100 µg/mL", "note": "bacterial (LB) selection"},
    {"kw": ["kanamycin"], "working": "50 µg/mL", "note": "bacterial (LB) selection"},
    {"kw": ["chloramphenicol"], "working": "25 µg/mL", "note": "bacterial (LB) selection"},
    {"kw": ["spectinomycin"], "working": "50 µg/mL", "note": "bacterial (LB) selection"},
    {"kw": ["tetracycline"], "working": "10 µg/mL", "note": "bacterial (LB) selection"},
    {"kw": ["gentamicin"], "working": "10–50 µg/mL", "note": "bacterial selection"},
    # induction / screening
    {"kw": ["iptg"], "working": "0.1–1 mM", "note": "induction (lac/T7)"},
    {"kw": ["x-gal", "xgal"], "working": "40 µg/mL", "note": "blue/white screening"},
]


def lookup(item_name: str) -> Optional[Dict[str, Any]]:
    """Return the standard-working-concentration record for a raw reagent, or None."""
    it = str(item_name or "").lower()
    if not it:
        return None
    for rec in RAW_REAGENTS:
        if any(k in it for k in rec["kw"]):
            return rec
    return None


def suggest(item_name: str) -> Optional[Dict[str, Any]]:
    """A proposal dict (value_promoter shape) for a raw reagent's working concentration, or
    None. Tagged typical_range — a standard default to confirm, never a source-confirmed value."""
    rec = lookup(item_name)
    if not rec:
        return None
    return {
        "value": rec["working"],
        "proposed_status": "typical_range",
        "evidence": {
            "evidence_class": "typical_range",
            "source_name": "known reagent (standard working conc.)",
            "source_quote": None, "source_location": None,
            "confidence": 0.5,
            "rationale": f"Standard working concentration — {rec['note']}.",
        },
    }
