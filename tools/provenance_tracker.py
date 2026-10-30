"""
provenance_tracker
===================
Append-only audit log for uncertainty objects, plus revision carry-over so a
protocol revision never loses history and never silently contaminates a value a
human (or a source) already confirmed.

No model calls. Pure-local. Every value transition in the uncertainty layer is
recorded here as a timestamped event:

  {ts, actor, action, from_status, to_status, value, evidence_ref, note}

actor convention:
  "system:<tool>"   deterministic tool (e.g. system:tools/typical_values)
  "agent:<Name>"    an LLM agent (e.g. agent:Fill Assistant)
  "user:<email>"    an explicit human action
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

# statuses that represent a settled, trusted decision (mirror of
# uncertainty_slots.CONFIRMED; duplicated here to avoid an import cycle).
_CONFIRMED = {"source_confirmed", "kit_confirmed", "calculated", "user_confirmed"}


def _utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


_CONFIRM = "[confirm with source protocol]"


def _norm(v: Any) -> str:
    """Loose value equality: collapse whitespace + casefold so '4000 xg' and
    '4000  XG' compare equal. Used to decide whether a revision actually changed
    a confirmed value."""
    return " ".join(str(v or "").split()).casefold()


def _has_concrete_value(v: Any) -> bool:
    """A real, stated value (not empty, not the CONFIRM placeholder)."""
    s = str(v or "").strip()
    return bool(s) and _CONFIRM not in s


def append(obj: Dict[str, Any], actor: str, action: str,
           from_status: Optional[str], to_status: Optional[str],
           value: Any = None, evidence: Optional[Dict[str, Any]] = None,
           note: str = "") -> Dict[str, Any]:
    """Append one audit event to obj['audit_trail'] and return the event."""
    event = {
        "ts": _utc(),
        "actor": actor,
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "value": value,
        "evidence_ref": (evidence or {}).get("source_name"),
        "note": note,
    }
    obj.setdefault("audit_trail", []).append(event)
    return event


def carry_over(old_proto: Dict[str, Any], new_proto: Dict[str, Any]) -> Dict[str, Any]:
    """On revision: merge the prior uncertainty registry into the new one by
    slot_id so (a) audit history is preserved and (b) confirmed values are not
    contaminated.

    For each slot present in BOTH protocols:
      - prepend the old audit_trail to the new one (history is monotonic);
      - if the OLD slot was CONFIRMED:
          * if the new current_value matches the old -> restore the old
            confirmed status/evidence (a revision must not downgrade it);
          * if it differs -> mark the slot 'conflict' and log it (never a silent
            overwrite of a confirmed value).
    Returns new_proto.
    """
    old_reg = (old_proto or {}).get("uncertainty", {}) or {}
    new_reg = new_proto.setdefault("uncertainty", {})

    for sid, oobj in old_reg.items():
        nobj = new_reg.get(sid)
        if nobj is None:
            # slot no longer exists in the revised protocol (step removed/merged);
            # keep nothing in the tree but do not error.
            continue

        # 1) history first
        nobj["audit_trail"] = (oobj.get("audit_trail", []) or []) + nobj.get("audit_trail", [])

        # 2) protect a settled decision.
        #    A revision that did NOT restate the value (left it empty/CONFIRM) is
        #    not a disagreement -> restore the confirmed decision. Only a NEW,
        #    concrete, DIFFERENT value raises a conflict (never a silent overwrite).
        if oobj.get("status") in _CONFIRMED:
            new_val = nobj.get("current_value")
            disagrees = _has_concrete_value(new_val) and _norm(new_val) != _norm(oobj.get("current_value"))
            if not disagrees:
                for k in ("status", "evidence", "source_quote", "source_name",
                          "source_location", "current_value", "confidence",
                          "requires_user_confirmation", "legacy_imported"):
                    if k in oobj:
                        nobj[k] = oobj[k]
                append(nobj, "system:revision", "preserved",
                       oobj["status"], oobj["status"], nobj.get("current_value"),
                       note="confirmed value carried across revision unchanged")
            else:
                prev = nobj.get("status")
                nobj["status"] = "conflict"
                nobj["requires_user_confirmation"] = True
                append(nobj, "system:revision", "conflict_on_revision",
                       prev, "conflict", new_val,
                       note=(f"revision proposes '{new_val}' but "
                             f"'{oobj.get('current_value')}' was {oobj['status']}"))
    return new_proto
