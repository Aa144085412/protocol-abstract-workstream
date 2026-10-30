"""
value_promoter
==============
The ONLY component allowed to write a value into the protocol tree's uncertainty
layer. Every status change goes through ``apply``, which:

  1. validates the transition against ``ALLOWED`` (a model guess can never become
     a *_confirmed status);
  2. enforces that user-only transitions come from a ``user:`` actor;
  3. guards confirmed values: a different incoming value never silently overwrites
     a confirmed one — it becomes ``conflict``;
  4. writes the value into the tree (only for value-bearing statuses), runs the
     deterministic dimension check, appends provenance, and re-syncs the inline
     string.

No model calls here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import uncertainty_slots as us
from . import provenance_tracker as prov

# from_status -> {to_status: required actor kind}
#   "user"     : only an explicit user action
#   "evidence" : a source/kit/calculation (or user) — i.e. genuine evidence
#   "system"   : any deterministic/system actor
ALLOWED: Dict[str, Dict[str, str]] = {
    "unresolved": {
        "source_confirmed": "evidence", "kit_confirmed": "evidence", "calculated": "evidence",
        "literature_supported": "evidence", "typical_range": "system", "ai_suggested": "system",
        "user_confirmed": "user", "not_applicable": "user", "conflict": "system",
    },
    "typical_range": {
        "user_confirmed": "user", "source_confirmed": "evidence", "kit_confirmed": "evidence",
        "calculated": "evidence", "ai_suggested": "system", "typical_range": "system",
        "literature_supported": "evidence", "conflict": "system", "unresolved": "user",
        "not_applicable": "user",
    },
    "ai_suggested": {
        "user_confirmed": "user", "source_confirmed": "evidence", "kit_confirmed": "evidence",
        "calculated": "evidence", "typical_range": "system", "ai_suggested": "system",
        "literature_supported": "evidence", "conflict": "system", "unresolved": "user",
        "not_applicable": "user",
    },
    "literature_supported": {
        "user_confirmed": "user", "source_confirmed": "evidence", "kit_confirmed": "evidence",
        "calculated": "evidence", "literature_supported": "system", "conflict": "system",
        "unresolved": "user", "not_applicable": "user",
    },
    # Confirmed states accept re-assertion by genuine evidence/user so the conflict
    # guard can compare values: same value -> stays/updates; different -> conflict.
    "source_confirmed": {"conflict": "system", "unresolved": "user", "user_confirmed": "user",
                         "source_confirmed": "evidence", "kit_confirmed": "evidence", "calculated": "evidence"},
    "kit_confirmed": {"conflict": "system", "unresolved": "user", "user_confirmed": "user",
                      "source_confirmed": "evidence", "kit_confirmed": "evidence", "calculated": "evidence"},
    "calculated": {"conflict": "system", "unresolved": "user", "user_confirmed": "user",
                   "source_confirmed": "evidence", "kit_confirmed": "evidence", "calculated": "evidence"},
    "user_confirmed": {"conflict": "system", "unresolved": "user", "user_confirmed": "user",
                       "source_confirmed": "evidence", "kit_confirmed": "evidence", "calculated": "evidence"},
    "conflict": {"user_confirmed": "user", "source_confirmed": "user", "unresolved": "user"},
    "not_applicable": {"unresolved": "user"},
}

WRITE_STATUSES = us.WRITE_STATUSES


class PromotionError(Exception):
    pass


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def _actor_kind_ok(required: str, actor: str) -> bool:
    if required == "user":
        return actor.startswith("user:")
    if required == "evidence":
        # genuine evidence = a deterministic system tool (evidence_resolver,
        # kit_lookup, calculator) or an explicit user. A bare 'agent:' (LLM) actor
        # is NOT evidence and can never reach a *_confirmed status on its own.
        return actor.startswith("user:") or actor.startswith("system:")
    return True  # "system": any actor (incl. agent: producing a suggestion)


def _to_conflict(proto, obj, value, evidence, actor) -> Dict[str, Any]:
    prev = obj["status"]
    obj["status"] = "conflict"
    obj["requires_user_confirmation"] = True
    # keep the incoming proposal visible as the contested candidate
    obj["recommended_candidate"] = value if value is not None else obj.get("recommended_candidate")
    prov.append(obj, actor, "conflict", prev, "conflict", value, evidence,
                note=f"incoming '{value}' disagrees with confirmed '{obj.get('current_value')}'")
    us.sync_inline(proto)
    return obj


def apply(proto: Dict[str, Any], slot_id: str, to_status: str,
          value: Any = None, evidence: Optional[Dict[str, Any]] = None,
          actor: str = "system:unknown") -> Dict[str, Any]:
    reg = us.registry(proto)
    obj = reg.get(slot_id)
    if obj is None:
        raise PromotionError(f"unknown slot_id: {slot_id}")
    frm = obj["status"]

    required = ALLOWED.get(frm, {}).get(to_status)
    if required is None:
        raise PromotionError(f"illegal transition {frm} -> {to_status} for {slot_id}")
    if not _actor_kind_ok(required, actor):
        raise PromotionError(
            f"transition {frm} -> {to_status} requires a '{required}' actor, got '{actor}'")

    # CONFLICT GUARD: a *different* value can never silently overwrite a confirmed one
    if (us.is_confirmed(frm) and to_status != "conflict"
            and value is not None and _norm(value) != _norm(obj.get("current_value"))):
        return _to_conflict(proto, obj, value, evidence, actor)

    # Record the value. recommended_candidate holds the best value for ANY tier;
    # current_value (the tree mirror) is only advanced for CONFIRMED statuses, so a
    # suggestion never appears as the protocol's actual value.
    if to_status in WRITE_STATUSES and value is not None:
        obj["recommended_candidate"] = value
        obj["confidence"] = (evidence or {}).get("confidence", obj.get("confidence", 0.0))
        obj["deterministic_checks_passed"] = us.dimension_ok(obj["expected_type"], value)
        if to_status in us.CONFIRMED:
            obj["current_value"] = value

    obj["status"] = to_status
    if evidence is not None:
        obj["evidence"] = {
            "evidence_class": evidence.get("evidence_class", to_status),
            "source_name": evidence.get("source_name"),
            "source_quote": evidence.get("source_quote"),
            "source_location": evidence.get("source_location"),
            "deterministic_checks_passed": obj.get("deterministic_checks_passed"),
        }
        obj["source_quote"] = evidence.get("source_quote")
        obj["source_name"] = evidence.get("source_name")
        obj["source_location"] = evidence.get("source_location")
    obj["requires_user_confirmation"] = to_status not in us.CONFIRMED
    if to_status in us.CONFIRMED and to_status != "user_confirmed":
        obj["legacy_imported"] = False  # real evidence supersedes any legacy bootstrap

    prov.append(obj, actor, "promoted", frm, to_status, value, evidence)
    us.sync_inline(proto)
    return obj


# --------------------------------------------------------------------------- #
# thin wrappers used by the UI / resolvers
# --------------------------------------------------------------------------- #
def user_confirm(proto, slot_id, value, user_email) -> Dict[str, Any]:
    return apply(proto, slot_id, "user_confirmed", value,
                 {"evidence_class": "user_confirmed", "source_name": f"user:{user_email}"},
                 f"user:{user_email}")


def mark_not_applicable(proto, slot_id, user_email) -> Dict[str, Any]:
    return apply(proto, slot_id, "not_applicable", None, None, f"user:{user_email}")


def keep_unresolved(proto, slot_id, user_email) -> Dict[str, Any]:
    return apply(proto, slot_id, "unresolved", None, None, f"user:{user_email}")


def resolve_conflict(proto, slot_id, chosen_value, user_email) -> Dict[str, Any]:
    return apply(proto, slot_id, "user_confirmed", chosen_value,
                 {"evidence_class": "user_confirmed", "source_name": f"user:{user_email}"},
                 f"user:{user_email}")


def auto_resolve(proto, slot_id, proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a proposal produced by evidence_resolver/suggest_value.
    proposal = {value, proposed_status, evidence{...}}."""
    ev = proposal.get("evidence", {})
    actor = f"system:{ev.get('source_name', 'resolver')}"
    return apply(proto, slot_id, proposal["proposed_status"], proposal.get("value"), ev, actor)
