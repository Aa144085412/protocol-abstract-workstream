"""
uncertainty_slots
=================
The side-car registry layer for active uncertainty objects.

Design (see UNCERTAINTY_OBJECTS_DESIGN.md):
  - Rich objects live in ``proto["uncertainty"][slot_id]``.
  - The inline protocol-tree value stays a STRING, rendered from the object's
    status, so legacy scanners (_count_confirm, fill_slots, protocol_check) keep
    working unchanged.
  - Slot ids reuse the ``fill_slots`` scheme (step_id-addressed, survives
    renumbering). ``fill_slots.read_slot`` / ``write_slot`` do the tree IO.

No model calls here.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from . import fill_slots
from . import provenance_tracker as prov
# unit recognizers reused from the deterministic pre-flight checker
from .protocol_check import _VOLUME, _MASS, _TEMP, _SPEED, _TIME

CONFIRM = fill_slots.CONFIRM
SCHEMA_VERSION = 1

# ---- trust bands ---------------------------------------------------------- #
CONFIRMED = {"source_confirmed", "kit_confirmed", "calculated", "user_confirmed"}
PARTIAL = {"literature_supported", "typical_range", "ai_suggested"}
SPECIAL = {"unresolved", "conflict", "not_applicable"}
ALL_STATUSES = CONFIRMED | PARTIAL | SPECIAL

# readiness credit per status (see readiness.py Factor 1)
WEIGHT = {
    "source_confirmed": 1.0, "kit_confirmed": 1.0, "calculated": 1.0, "user_confirmed": 1.0,
    "literature_supported": 0.5, "typical_range": 0.2, "ai_suggested": 0.05,
    "unresolved": 0.0, "conflict": 0.0, "not_applicable": 0.0,
}

# statuses whose value is actually written into the protocol tree
WRITE_STATUSES = CONFIRMED | PARTIAL

# expected_type -> dimension regex (None = no deterministic unit check)
_TYPE_RE = {
    "volume": _VOLUME, "mass": _MASS, "material_amount": None,  # amount may be vol OR mass
    "temperature": _TEMP, "speed": _SPEED, "time": _TIME,
    "concentration": None, "cell_number": None, "reagent_identity": None,
    "catalog_number": None, "vendor": None, "other": None, "value": None,
}

# expected_types that must NEVER receive an AI/typical suggestion
# The ONLY thing the agent must never invent is WHICH reagent it is. Vendor/catalog
# MAY be suggested (a consistent likely kit) — but only as a labeled ai_suggested
# value the user verifies before ordering, never as a confirmed value.
NON_SUGGESTABLE_TYPES = {"reagent_identity"}

# default risk per expected_type
_DEFAULT_RISK = {
    "concentration": "high", "reagent_identity": "high",
    "speed": "medium", "temperature": "medium", "time": "medium",
    "volume": "medium", "mass": "medium", "material_amount": "medium",
    "cell_number": "medium", "value": "medium",
    "catalog_number": "low", "vendor": "low", "other": "low",
}
# step intents (from protocol_check._infer_intent) that bump conditions to high risk
_HIGH_RISK_INTENTS = {"transform", "digest", "pcr", "ligate", "bind"}

# high-impact operations: a value here can destroy sample / invalidate an expensive
# run, so it is HIGH risk and must require confirmation even when a value is proposed.
_HIGH_RISK_KW = (
    "tagment", "moi", "transduc", "electropora", "nuclei load", "load onto", "10x",
    "chromium", "gem", "antibiotic", "puromycin", "blasticidin", "g418", "geneticin",
    "drug dose", "dose", "facs", "gate", "ultracentrifug", "gradient", "density gradient",
    "digestion time", "tissue digest", "library pcr", "pcr cycle", "cycles",
    "enzyme concentration", "voltage", "viral", "mge",
)


# --------------------------------------------------------------------------- #
# registry accessors
# --------------------------------------------------------------------------- #
def registry(proto: Dict[str, Any]) -> Dict[str, Any]:
    return proto.setdefault("uncertainty", {})


def get(proto: Dict[str, Any], slot_id: str) -> Optional[Dict[str, Any]]:
    return registry(proto).get(slot_id)


def is_confirmed(status: str) -> bool:
    return status in CONFIRMED


def is_partial(status: str) -> bool:
    return status in PARTIAL


def weight(status: str) -> float:
    return WEIGHT.get(status, 0.0)


# --------------------------------------------------------------------------- #
# slot-id parsing + field discovery
# --------------------------------------------------------------------------- #
def parse_slot_id(slot_id: str) -> Dict[str, Any]:
    """Derive {step_id, field_name, expected_type, field_path} from a fill_slots id."""
    p = slot_id.split(":")
    if p[0] == "mat":
        i, field = p[1], p[2]
        etype = {"amount": "material_amount", "vendor": "vendor",
                 "catalog_number": "catalog_number"}.get(field, "value")
        return {"step_id": None, "field_name": field, "expected_type": etype,
                "field_path": f"materials[{i}].{field}"}
    if p[0] == "step":
        sid = p[1]
        if p[2] == "time":
            return {"step_id": sid, "field_name": "time", "expected_type": "time",
                    "field_path": f"workflow[{sid}].time_estimate"}
        if p[2] == "cond":
            field = p[3]
            etype = {"temperature": "temperature", "speed": "speed"}.get(field, "other")
            return {"step_id": sid, "field_name": field, "expected_type": etype,
                    "field_path": f"workflow[{sid}].conditions.{field}"}
        if p[2] == "reag":
            ri = p[3]
            return {"step_id": sid, "field_name": "amount", "expected_type": "material_amount",
                    "field_path": f"workflow[{sid}].reagents[{ri}].amount"}
        if p[2] == "instr":
            return {"step_id": sid, "field_name": "instruction_value", "expected_type": "value",
                    "field_path": f"workflow[{sid}].instructions[{p[3]}]#{p[4]}"}
    return {"step_id": None, "field_name": "value", "expected_type": "value",
            "field_path": slot_id}


def _all_field_ids(proto: Dict[str, Any]) -> List[str]:
    """Every trackable field id, whether filled or not. (fill_slots.list_slots
    only returns UNCONFIRMED slots, so we enumerate the tree ourselves for the
    persistent fields, then add embedded-instruction CONFIRM tokens from
    list_slots.)"""
    ids: List[str] = []
    for i, _m in enumerate(proto.get("materials", []) or []):
        ids.append(f"mat:{i}:amount")
        ids.append(f"mat:{i}:vendor")
        ids.append(f"mat:{i}:catalog_number")
    for s in proto.get("workflow", []) or []:
        sid = s.get("step_id")
        if not sid:
            continue
        ids.append(f"step:{sid}:time")
        for field in ("temperature", "speed"):
            ids.append(f"step:{sid}:cond:{field}")
        cond = s.get("conditions", {}) or {}
        if str(cond.get("other", "")).strip():
            ids.append(f"step:{sid}:cond:other")
        for ri, _r in enumerate(s.get("reagents", []) or []):
            ids.append(f"step:{sid}:reag:{ri}:amount")
    # embedded "[confirm…]" tokens inside instruction prose
    for slot in fill_slots.list_slots(proto):
        if ":instr:" in slot["id"]:
            ids.append(slot["id"])
    return ids


def _intent_for_step(proto: Dict[str, Any], step_id: str) -> str:
    from .protocol_check import _infer_intent
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == step_id:
            return _infer_intent(s)
    return "step"


def _default_risk(proto: Dict[str, Any], meta: Dict[str, Any]) -> str:
    base = _DEFAULT_RISK.get(meta["expected_type"], "medium")
    sid = meta.get("step_id")
    if sid:
        # a high-impact operation makes ANY value on that step high risk
        step = next((s for s in proto.get("workflow", []) or [] if s.get("step_id") == sid), {})
        text = (str(step.get("title", "")) + " "
                + " ".join(str(i) for i in step.get("instructions", []) or [])).lower()
        if any(k in text for k in _HIGH_RISK_KW):
            return "high"
        if meta["expected_type"] in ("speed", "temperature", "time") \
                and _intent_for_step(proto, sid) in _HIGH_RISK_INTENTS:
            return "high"
    return base


_RISK_TEXT = {
    "speed": "Too high can shear/lyse or pellet too hard; too low fails to pellet.",
    "temperature": "Wrong temperature can denature, kill cells, or stall the reaction.",
    "time": "Too short under-reacts; too long over-digests / over-incubates.",
    "concentration": "Wrong concentration changes stoichiometry and can invalidate the result.",
    "reagent_identity": "The wrong reagent invalidates the experiment.",
    "material_amount": "Wrong amount changes yield/efficiency and may waste sample.",
    "cell_number": "Wrong cell number changes density-dependent outcomes.",
    "catalog_number": "Ordering metadata; low bench risk but affects reproducibility.",
    "vendor": "Ordering metadata; low bench risk but affects reproducibility.",
}


def _empty_evidence() -> Dict[str, Any]:
    return {"evidence_class": None, "source_name": None, "source_quote": None,
            "source_location": None, "deterministic_checks_passed": None}


def _looks_filled(v: Any) -> bool:
    return bool(str(v or "").strip()) and CONFIRM not in str(v)


def dimension_ok(expected_type: str, value: Any) -> Optional[bool]:
    """Deterministic unit/dimension sanity for a chosen value. Returns True/False,
    or None when the type has no checkable dimension."""
    rx = _TYPE_RE.get(expected_type)
    v = str(value or "").strip()
    if not v or v == CONFIRM:
        return None
    if expected_type == "material_amount":  # amount may be volume OR mass
        return bool(_VOLUME.search(v) or _MASS.search(v))
    if expected_type == "speed":
        # tolerant: accept 'x g', 'x g' (× with/without space), 'xg', rpm, rcf, or bare g
        return bool(re.search(r"\d[\d,]*\s*(?:×|x)\s*g|\d[\d,]*\s*(?:rpm|rcf)|\d[\d,]*\s*g\b",
                              v, re.I))
    if rx is None:
        return None
    return bool(rx.search(v))


# --------------------------------------------------------------------------- #
# object construction / enumeration
# --------------------------------------------------------------------------- #
def _new_object(proto: Dict[str, Any], slot_id: str) -> Dict[str, Any]:
    meta = parse_slot_id(slot_id)
    value = fill_slots.read_slot(proto, slot_id)
    filled = _looks_filled(value)
    status = "user_confirmed" if filled else "unresolved"  # filled bootstrap (legacy-style)
    obj = {
        "slot_id": slot_id,
        "field_path": meta["field_path"],
        "step_id": meta["step_id"],
        "field_name": meta["field_name"],
        "expected_type": meta["expected_type"],
        "current_value": value if value is not None else CONFIRM,
        "status": status,
        "risk_level": _default_risk(proto, meta),
        "risk_if_wrong": _RISK_TEXT.get(meta["expected_type"], "Verify before relying on this value."),
        "candidate_values": [],
        "recommended_candidate": value if filled else None,
        "confidence": 1.0 if filled else 0.0,
        "evidence": _empty_evidence(),
        "source_quote": None,
        "source_name": None,
        "source_location": None,
        "deterministic_checks_passed": dimension_ok(meta["expected_type"], value) if filled else None,
        "requires_user_confirmation": not filled,
        "legacy_imported": bool(filled),   # bootstrapped from a pre-existing value, no quote
        "audit_trail": [],
    }
    prov.append(obj, "system:enumerate", "created", None, status,
                value if filled else None,
                note=("bootstrapped from pre-existing value (legacy_imported)" if filled
                      else "no value in source"))
    return obj


def enumerate_slots(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Build/refresh an uncertainty object for every trackable field. Idempotent:
    existing objects are preserved (their current_value mirror is refreshed); new
    fields get a fresh object."""
    reg = registry(proto)
    seen = set()
    for slot_id in _all_field_ids(proto):
        seen.add(slot_id)
        if slot_id in reg:
            obj = reg[slot_id]
            tv = fill_slots.read_slot(proto, slot_id)
            if tv is not None:
                obj["current_value"] = tv
            # Reconcile an EXTERNAL direct write (a manual step edit, a kit/auto fill
            # that wrote straight to the tree, etc.): a concrete value sitting on a slot
            # the registry still thinks is unresolved is a human/kit fill we must trust
            # as user_confirmed (same level as a legacy import — flagged for review),
            # never silently revert it to CONFIRM. Model suggestions never reach here
            # because they keep the tree value as CONFIRM (see value_promoter).
            if _looks_filled(tv) and obj.get("status") == "unresolved":
                obj["status"] = "user_confirmed"
                obj["recommended_candidate"] = tv
                obj["confidence"] = 1.0
                obj["legacy_imported"] = True
                obj["requires_user_confirmation"] = False
                obj["deterministic_checks_passed"] = dimension_ok(obj["expected_type"], tv)
                prov.append(obj, "system:reconcile", "reconciled", "unresolved",
                            "user_confirmed", tv, note="external direct write imported as user-confirmed")
        else:
            reg[slot_id] = _new_object(proto, slot_id)
    proto["uncertainty_schema_version"] = SCHEMA_VERSION
    return reg


# --------------------------------------------------------------------------- #
# inline rendering (keeps the tree string in sync with status)
# --------------------------------------------------------------------------- #
def inline_string(obj: Dict[str, Any]) -> str:
    """What gets written into the protocol TREE for this slot.

    Honesty contract: a suggestion is NOT part of the protocol. Only CONFIRMED
    values (source/kit/calc/user) land in the tree; everything still uncertain —
    unresolved, any PARTIAL suggestion, or a conflict — renders as the CONFIRM
    placeholder so the deterministic tools (planner, methods, protocol_check,
    _count_confirm) never parse a candidate as if it were real. The rich
    candidate/evidence lives only in the registry and is surfaced by the UI.
    """
    s = obj["status"]
    if s in CONFIRMED:
        return str(obj.get("current_value") or CONFIRM)
    if s == "not_applicable":
        return "n/a"
    return CONFIRM  # unresolved / partial / conflict -> still uncertain in the tree


def sync_inline(proto: Dict[str, Any]) -> None:
    """Write each slot's rendered inline string back into the protocol tree."""
    for obj in registry(proto).values():
        if ":instr:" in obj["slot_id"]:
            # embedded-instruction tokens: only substitute a real value once it is
            # CONFIRMED, otherwise leave the CONFIRM token in place (writing would
            # consume the token and we could not re-find the slot).
            if obj["status"] in CONFIRMED and _looks_filled(obj.get("current_value")):
                fill_slots.write_slot(proto, obj["slot_id"], inline_string(obj))
            continue
        rendered = inline_string(obj)
        # Non-clobbering safety net: never overwrite a concrete tree value with the
        # CONFIRM placeholder. (Reconciliation in enumerate_slots normally promotes
        # such a value to user_confirmed first; this guards the edge case.)
        if rendered == CONFIRM and _looks_filled(fill_slots.read_slot(proto, obj["slot_id"])):
            continue
        fill_slots.write_slot(proto, obj["slot_id"], rendered)


# --------------------------------------------------------------------------- #
# migration: legacy CONFIRM strings -> structured objects
# --------------------------------------------------------------------------- #
def _has_source_quote(proto: Dict[str, Any], obj: Dict[str, Any]) -> bool:
    """Hook for evidence-aware migration. Today we have no per-field quote store,
    so this is False; wire it up once DocumentAgent emits source quotes."""
    return False


def migrate_protocol(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy, idempotent, versioned migration. Three-way classification:
        filled value + recoverable quote -> source_confirmed
        filled value + no quote          -> user_confirmed + legacy_imported
        CONFIRM / empty                  -> unresolved
    Safe to call on every render."""
    if proto.get("uncertainty_schema_version") == SCHEMA_VERSION and proto.get("uncertainty"):
        enumerate_slots(proto)      # refresh mirrors only
        sync_inline(proto)
        return proto

    enumerate_slots(proto)
    reg = registry(proto)
    for obj in reg.values():
        v = str(obj.get("current_value") or "")
        if CONFIRM in v or not v.strip():
            if obj["status"] != "unresolved":
                prov.append(obj, "system:migration", "migrated", obj["status"],
                            "unresolved", None, note="empty/CONFIRM -> unresolved")
            obj["status"] = "unresolved"
            obj["legacy_imported"] = False
            obj["requires_user_confirmation"] = True
            obj["recommended_candidate"] = None
            obj["confidence"] = 0.0
        elif _has_source_quote(proto, obj):
            obj["status"] = "source_confirmed"
            obj["legacy_imported"] = False
            obj["requires_user_confirmation"] = False
        else:
            obj["status"] = "user_confirmed"
            obj["legacy_imported"] = True
            obj["requires_user_confirmation"] = False
    proto["uncertainty_schema_version"] = SCHEMA_VERSION
    sync_inline(proto)
    return proto


def legacy_imported_count(proto: Dict[str, Any]) -> int:
    """For the one-time review banner."""
    return sum(1 for o in registry(proto).values() if o.get("legacy_imported"))
