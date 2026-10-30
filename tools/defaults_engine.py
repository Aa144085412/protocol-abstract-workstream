"""
defaults_engine
==============
The standardized-default recommendation engine. For an uncertainty slot it returns
the single best PROPOSAL, walking a strict priority ladder so the user never has to
invent a value but provenance is always preserved:

    1. evidence      source / kit / calculation / reference   -> *_confirmed / literature
    2. catalog       memory/standard_defaults.json            -> typical_range (cited basis)
    3. typical       tools/typical_values                     -> typical_range
    4. AI            FillAgent (optional)                     -> ai_suggested
    else                                                      -> None (stays needs_confirmation)

Returned proposals are value_promoter-ready (``auto_resolve``) and additionally
carry ``inference_basis``, ``citation``, ``risk_level``, and ``tier`` for the UI.
Pure-local except the optional AI tier. (The future Knowledge broker plugs in as a
tier between 1 and 2.)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import evidence_resolver, suggest_value, standard_defaults
from .protocol_check import _infer_intent


def _step(proto: Dict[str, Any], step_id: Optional[str]) -> Dict[str, Any]:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == step_id:
            return s
    return {}


def _step_text(proto: Dict[str, Any], obj: Dict[str, Any]) -> str:
    s = _step(proto, obj.get("step_id"))
    return (str(s.get("title", "")) + ". "
            + " ".join(str(i) for i in s.get("instructions", []) or [])) if s \
        else proto.get("protocol_title", "")


def _catalog_proposal(proto: Dict[str, Any], obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    s = _step(proto, obj.get("step_id"))
    intent = _infer_intent(s) if s else None
    e = standard_defaults.best(_step_text(proto, obj), obj.get("expected_type"), intent)
    if not e:
        return None
    cit = e.get("citation") or {}
    return {
        "value": e.get("value"),
        "proposed_status": "typical_range",          # a suggestion, not the user's kit value
        "evidence": {
            "evidence_class": "typical_range",
            "source_name": f"catalog:{e['id']}" + (f" ({cit.get('company')})" if cit.get("company") else ""),
            "source_quote": e.get("inference_basis"),
            "source_location": cit or None,
            "confidence": 0.45,
            "rationale": e.get("inference_basis"),
        },
        "inference_basis": e.get("inference_basis"),
        "citation": cit or None,
        "risk_level": e.get("risk_level"),
        "range": e.get("range"),
        "tier": "catalog",
    }


def _tag(prop: Optional[Dict[str, Any]], tier: str) -> Optional[Dict[str, Any]]:
    if prop is not None:
        prop.setdefault("tier", tier)
        prop.setdefault("inference_basis", (prop.get("evidence") or {}).get("rationale")
                        or (prop.get("evidence") or {}).get("source_quote"))
    return prop


def recommend(proto: Dict[str, Any], obj: Dict[str, Any],
              sources: Optional[Dict[str, Any]] = None,
              fill_agent: Any = None) -> Optional[Dict[str, Any]]:
    """Best single proposal for a slot, or None if nothing reasonable exists
    (slot then stays needs_confirmation). Never mutates the protocol."""
    # 1. genuine evidence (source/kit/calc/reference)
    prop = evidence_resolver.best_proposal(obj, proto, sources or {})
    if prop:
        return _tag(prop, "evidence")
    # 2. curated standard-default catalog
    cat = _catalog_proposal(proto, obj)
    if cat:
        return cat
    # 3. deterministic typical ranges
    cands = suggest_value.typical_candidates(proto, obj)
    if cands:
        return _tag(cands[0], "typical")
    # 4. optional AI common-practice
    if fill_agent is not None:
        ai = suggest_value.ai_candidate(proto, obj, fill_agent)
        if ai:
            return _tag(ai, "ai")
    return None


def prefill_unresolved(proto: Dict[str, Any], sources: Optional[Dict[str, Any]] = None,
                       fill_agent: Any = None, apply: bool = True) -> Dict[str, int]:
    """Run recommend() across every unresolved slot. With apply=True, route each
    proposal through value_promoter (so provenance + tree-safety hold). Returns
    counts by tier. High-risk slots are still proposed but stay non-confirmed
    suggestions requiring user confirmation."""
    from . import uncertainty_slots as us
    from . import value_promoter as vp
    counts = {"evidence": 0, "catalog": 0, "typical": 0, "ai": 0, "left": 0}
    for obj in list(us.registry(proto).values()):
        if obj.get("status") != "unresolved":
            continue
        prop = recommend(proto, obj, sources, fill_agent)
        if not prop:
            counts["left"] += 1
            continue
        counts[prop.get("tier", "typical")] = counts.get(prop.get("tier", "typical"), 0) + 1
        if apply:
            vp.auto_resolve(proto, obj["slot_id"], prop)
            o = us.get(proto, obj["slot_id"])
            if prop.get("inference_basis"):
                o["inference_basis"] = prop["inference_basis"]
            if prop.get("citation"):
                o["citation"] = prop["citation"]
            o.setdefault("candidate_values", []).append(prop)
    return counts
