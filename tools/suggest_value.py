"""
suggest_value
=============
Hierarchy tiers 6 and 7 — SUGGESTIONS, never confirmations.

  Tier 6  typical value / range from the deterministic KB  -> typical_range
  Tier 7  AI common-practice candidate (optional model)    -> ai_suggested

Both return value_promoter-shaped proposals. Neither ever yields a *_confirmed
status: a suggestion must be confirmed by evidence (evidence_resolver) or an
explicit user action (value_promoter.user_confirm) to earn readiness credit.

Guardrails:
  - vendor / catalog_number / reagent_identity are NEVER suggested (must not be
    invented).
  - A suggestion's value is always dimension-checked against the slot's
    expected_type, so e.g. a time never lands in a speed slot.

Tier 6 is pure-local. Tier 7 only runs if a ``fill_agent`` is passed in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import typical_values
from . import uncertainty_slots as us


def _proposal(value: str, status: str, source_name: str,
              conf: float, rationale: str = "") -> Dict[str, Any]:
    return {
        "value": str(value).strip(),
        "proposed_status": status,
        "evidence": {
            "evidence_class": status,
            "source_name": source_name,
            "source_quote": None,
            "source_location": None,
            "confidence": conf,
            "rationale": rationale,
        },
    }


def _step_text(proto: Dict[str, Any], obj: Dict[str, Any]) -> str:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == obj.get("step_id"):
            return (str(s.get("title", "")) + ". "
                    + " ".join(str(i) for i in s.get("instructions", []) or []))
    return proto.get("protocol_title", "") or ""


def _suggestion_value(s: Dict[str, Any]) -> Optional[str]:
    """Build a single value string from a typical_values suggestion dict."""
    if s.get("low") is not None:
        if s.get("low") == s.get("high"):
            return f"{s['low']} {s.get('unit', '')}".strip()
        return f"{s['low']}-{s['high']} {s.get('unit', '')}".strip()
    if s.get("typical") is not None:
        return f"{s['typical']} {s.get('unit', '')}".strip()
    return None


# --------------------------------------------------------------------------- #
# Tier 6 — typical ranges (deterministic)
# --------------------------------------------------------------------------- #
def typical_candidates(proto: Dict[str, Any], obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    if obj.get("expected_type") in us.NON_SUGGESTABLE_TYPES:
        return []
    out: List[Dict[str, Any]] = []
    for s in typical_values.suggest_for_text(_step_text(proto, obj)):
        val = _suggestion_value(s)
        if val and us.dimension_ok(obj["expected_type"], val):
            out.append(_proposal(val, "typical_range", "tools/typical_values",
                                 conf=0.4, rationale=s.get("rationale", "")))
    return out


# --------------------------------------------------------------------------- #
# Tier 7 — AI common practice (optional, requires a fill_agent)
# --------------------------------------------------------------------------- #
def ai_candidate(proto: Dict[str, Any], obj: Dict[str, Any],
                 fill_agent: Any = None, context: str = "",
                 source_text: str = "") -> Optional[Dict[str, Any]]:
    """Ask the FillAgent for a single-slot value. Tagged ai_suggested (a guess);
    never confirmed, never a vendor/catalog. Returns one proposal or None."""
    if fill_agent is None or obj.get("expected_type") in us.NON_SUGGESTABLE_TYPES:
        return None
    slot = {"id": obj["slot_id"],
            "label": f"{obj.get('field_name')} ({obj.get('expected_type')})",
            "context": context or _step_text(proto, obj)}
    try:
        res = fill_agent.suggest(proto, [slot], context, source_text=source_text)
    except Exception:
        return None
    sugg = (res or {}).get("suggestions", {}) or {}
    val = sugg.get(obj["slot_id"])
    if isinstance(val, dict):                    # tolerate richer return shapes
        val = val.get("value")
    if not val or not str(val).strip():
        return None
    # dimension sanity: a guess in the wrong dimension is dropped, not surfaced
    if us.dimension_ok(obj["expected_type"], val) is False:
        return None
    conf = 0.35
    return _proposal(str(val), "ai_suggested", f"agent:{getattr(fill_agent, 'name', 'Fill')}",
                     conf=conf, rationale="AI common-practice suggestion — confirm before use.")


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
def suggest(obj: Dict[str, Any], proto: Dict[str, Any],
            fill_agent: Any = None, context: str = "",
            source_text: str = "") -> List[Dict[str, Any]]:
    """Typical candidates first (deterministic), then an optional AI candidate."""
    out = typical_candidates(proto, obj)
    ai = ai_candidate(proto, obj, fill_agent, context, source_text)
    if ai:
        out.append(ai)
    return out
