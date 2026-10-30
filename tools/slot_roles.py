"""
slot_roles
=========
Semantic-role tagging for uncertainty slots — the bridge from a free-form protocol
to a dependency graph. A "role" names what a value MEANS (media_volume, wash_volume,
spin_speed, ...) so downstream values can be bound to upstream intent (vessel,
cell number) and recomputed when it changes.

Deterministic heuristics over step text + field + reagent name. No model calls.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ROLES = {"media_volume", "wash_volume", "lysis_volume", "cell_number", "rna_input",
         "spin_speed", "incubation_temp", "duration", "reagent_amount"}

_MEDIA = ("media", "medium", "dmem", "rpmi", "fbs", "growth medium", "complete medium")
_WASH = ("pbs", "wash", "rinse")
_LYSIS = ("lysis", "lysis buffer", "rlt", "ripa")
_CELLS = ("cells", "nuclei", "cell suspension")
_RNA = ("rna", "total rna", "mrna")
_RT_STEP = ("cdna", "reverse transcri", "rt reaction", "first-strand", "first strand")


def detect_role(step_text: str, field_name: str, expected_type: Optional[str],
                item: str = "") -> Optional[str]:
    it = (item or "").lower()
    t = (step_text or "").lower()
    if expected_type == "speed":
        return "spin_speed"
    if expected_type == "temperature":
        return "incubation_temp"
    if expected_type == "time":
        return "duration"
    if expected_type in ("material_amount", "volume", "cell_number", "count"):
        if any(k in it for k in _MEDIA):
            return "media_volume"
        if any(k in it for k in _WASH):
            return "wash_volume"
        if any(k in it for k in _LYSIS):
            return "lysis_volume"
        if any(k in it for k in _CELLS) or expected_type in ("cell_number", "count"):
            return "cell_number"
        if any(k in it for k in _RNA) or any(k in t for k in _RT_STEP):
            return "rna_input"
        return "reagent_amount"
    return None


def _step(proto: Dict[str, Any], step_id: Optional[str]) -> Dict[str, Any]:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == step_id:
            return s
    return {}


def _reagent_item(proto: Dict[str, Any], slot_id: str) -> str:
    p = slot_id.split(":")
    if len(p) == 5 and p[0] == "step" and p[2] == "reag":
        s = _step(proto, p[1])
        try:
            return (s.get("reagents", []) or [])[int(p[3])].get("item", "")
        except Exception:
            return ""
    if len(p) == 3 and p[0] == "mat":
        try:
            return (proto.get("materials", []) or [])[int(p[1])].get("item", "")
        except Exception:
            return ""
    return ""


def tag_roles(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Attach obj['role'] to every uncertainty slot. Idempotent."""
    from . import uncertainty_slots as us
    for o in us.registry(proto).values():
        step = _step(proto, o.get("step_id"))
        text = (str(step.get("title", "")) + " "
                + " ".join(str(i) for i in step.get("instructions", []) or [])) if step else ""
        o["role"] = detect_role(text, o.get("field_name", ""), o.get("expected_type"),
                                _reagent_item(proto, o["slot_id"]))
    return proto


def slots_with_role(proto: Dict[str, Any], role: str):
    from . import uncertainty_slots as us
    return [o for o in us.registry(proto).values() if o.get("role") == role]
