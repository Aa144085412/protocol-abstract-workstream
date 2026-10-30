"""
field_hygiene
=============
Deterministic clean-up of common PARSE artifacts so the generated protocol doesn't reach the
user pre-seeded with nonsense. Runs during parse → design. It does NOT invent values — it only
REMOVES values that are demonstrably misplaced/duplicated, leaving them to be filled honestly:

  1. A temperature / thermocycling string sitting in the TIME field ("95-98 °C, 30 s-3 min")
     is not a duration — move it into the instructions, blank the time.
  2. A storage temperature (-20 / -80 °C) on a step that isn't a storage/freeze step is a leak
     from another step — blank it.
  3. The SAME amount repeated across many different reagents ("159 ng" on every enzyme) is a
     propagation artifact — blank the copies that the step text doesn't support.

Everything blanked becomes a normal "to confirm" slot — honest, not wrong.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from . import uncertainty_slots as us

CONFIRM = us.CONFIRM
_HAS_TEMP = re.compile(r"-?\d+(\.\d+)?\s*°?\s*c\b|\b\d+\s*°", re.I)
_STORAGE_TEMP = re.compile(r"-\s*20|-\s*80|minus\s*20|minus\s*80", re.I)
_STORAGE_WORDS = ("store", "stora", "freez", "aliquot", "-20", "-80", "long-term", "keep at")


def _step_text(s: Dict[str, Any]) -> str:
    return (str(s.get("title", "")) + " "
            + " ".join(str(i) for i in s.get("instructions", []) or [])).lower()


def clean(proto: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Clean misplaced/duplicated values in place. Returns [(kind, where)] for logging."""
    wf = proto.get("workflow", []) or []
    changes: List[Tuple[str, str]] = []

    # 1) temperature / cycling stuck in the TIME field -> move to instructions, blank time
    for s in wf:
        t = str(s.get("time_estimate", "") or "").strip()
        if t and t != CONFIRM and (_HAS_TEMP.search(t) or "cycle" in t.lower()):
            instr = list(s.get("instructions", []) or [])
            note = f"Thermocycling/conditions (from source): {t}"
            if note not in instr:
                instr.append(note)
            s["instructions"] = instr
            s["time_estimate"] = CONFIRM
            changes.append(("time_misfiled", s.get("step_id", "")))

    # 2) storage temperature on a non-storage step -> blank (it leaked from another step)
    for s in wf:
        cond = s.get("conditions", {}) or {}
        v = str(cond.get("temperature", "") or "").strip()
        if v and v != CONFIRM and _STORAGE_TEMP.search(v):
            if not any(w in _step_text(s) for w in _STORAGE_WORDS):
                cond["temperature"] = CONFIRM
                changes.append(("storage_temp_misplaced", s.get("step_id", "")))
        # wrong-dimension speed (a non-speed value in the speed field) -> blank
        sp = str(cond.get("speed", "") or "").strip()
        if sp and sp != CONFIRM and us.dimension_ok("speed", sp) is False:
            cond["speed"] = CONFIRM
            changes.append(("speed_wrongdim", s.get("step_id", "")))

    # 3) de-propagate a reagent amount copied across many DIFFERENT reagents
    val_items: Dict[str, set] = defaultdict(set)
    for s in wf:
        for r in s.get("reagents", []) or []:
            amt = str(r.get("amount", "") or "").strip()
            if amt and amt != CONFIRM:
                val_items[amt].add(str(r.get("item", "")).strip().lower())
    suspicious = {v for v, items in val_items.items() if len(items) >= 3}
    for s in wf:
        text = _step_text(s)
        for r in s.get("reagents", []) or []:
            amt = str(r.get("amount", "") or "").strip()
            if amt in suspicious and amt.lower() not in text:
                r["amount"] = CONFIRM
                changes.append(("amount_depropagated", r.get("item", "")))

    return changes
