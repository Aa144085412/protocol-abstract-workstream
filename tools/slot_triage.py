"""
slot_triage
==========
A deterministic DECISION TREE that decides, for an uncertainty slot, whether the
field even APPLIES to its step — so the agent can retire flags that are schema
artifacts (e.g. a centrifuge *speed* attached to a plating step) instead of asking
the human to answer something meaningless.

This is the auditable backbone behind ``SlotTriageAgent``: in DEMO/offline mode
the agent falls back to this tree; live, the model makes the same call with
reasoning, grounded by these rules. No model calls here.

Decision for a slot:
  - "not_applicable"  the step does not perform this operation -> suggest Mark N/A
  - "applicable"      the field is meaningful for this step    -> keep / resolve

Only CONDITION slots (speed, temperature) are triaged for applicability — those
are the ones the protocol schema tends to create spuriously. Amounts, times, and
identities default to "applicable".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .protocol_check import _infer_intent

# step intents (from protocol_check._infer_intent) for which a condition is meaningful
_APPLIES_INTENT = {
    "speed": {"centrifuge"},
    "temperature": {"incubate", "pcr", "digest", "ligate", "transform", "bind"},
}
# keyword backstop: if the step text mentions the operation, the field applies
# regardless of the inferred intent. (NOT unit tokens like 'rpm' — operation words.)
_APPLIES_KW = {
    "speed": ("spin", "centrifug", "pellet"),
    "temperature": ("incubat", "heat", " ice", "chill", "warm", "anneal", "denatur",
                    "thaw", "°c", "37", "65", "95", "4°", "-20", "-80"),
}


def _step(proto: Dict[str, Any], step_id: Optional[str]) -> Dict[str, Any]:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == step_id:
            return s
    return {}


def _step_text(step: Dict[str, Any]) -> str:
    return (str(step.get("title", "")) + " "
            + " ".join(str(i) for i in step.get("instructions", []) or [])).lower()


def triage_slot(proto: Dict[str, Any], obj: Dict[str, Any]) -> Dict[str, Any]:
    """Decide whether obj's field applies to its step. Returns:
    {decision, reason, confidence, rule, auto_safe}."""
    etype = obj.get("expected_type")
    if etype not in _APPLIES_INTENT:
        return {"decision": "applicable", "reason": f"a {etype} value is expected here",
                "confidence": 0.5, "rule": "default_applicable", "auto_safe": False}

    step = _step(proto, obj.get("step_id"))
    text = _step_text(step)
    intent = _infer_intent(step) if step else "step"
    by_intent = intent in _APPLIES_INTENT[etype]
    by_kw = any(k in text for k in _APPLIES_KW[etype])

    if by_intent or by_kw:
        why = (f"step intent '{intent}'" if by_intent else "the step text mentions the operation")
        return {"decision": "applicable", "reason": f"{etype} applies — {why}.",
                "confidence": 0.75, "rule": f"{etype}_applies", "auto_safe": False}

    title = step.get("title", "this step")
    return {
        "decision": "not_applicable",
        "reason": (f"'{title}' (intent: {intent}) does not perform a "
                   f"{'centrifugation' if etype == 'speed' else 'thermal'} step, so a "
                   f"{etype} value is not meaningful."),
        "confidence": 0.85,
        "rule": f"{etype}_on_non_matching_step",
        "auto_safe": True,   # deterministic + high-confidence -> safe to auto Mark N/A
    }


def triage_protocol(proto: Dict[str, Any], only_unresolved: bool = True) -> List[Dict[str, Any]]:
    """Triage every (unresolved) condition slot. Returns a list of
    {slot_id, step_id, expected_type, decision, reason, confidence, rule, auto_safe}."""
    from . import uncertainty_slots as us
    out: List[Dict[str, Any]] = []
    for obj in us.registry(proto).values():
        if only_unresolved and obj.get("status") != "unresolved":
            continue
        if obj.get("expected_type") not in _APPLIES_INTENT:
            continue
        t = triage_slot(proto, obj)
        out.append({"slot_id": obj["slot_id"], "step_id": obj.get("step_id"),
                    "expected_type": obj.get("expected_type"), **t})
    return out


def auto_not_applicable(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The slots the deterministic tree is confident are not applicable (auto_safe)."""
    return [t for t in triage_protocol(proto) if t["decision"] == "not_applicable" and t["auto_safe"]]
