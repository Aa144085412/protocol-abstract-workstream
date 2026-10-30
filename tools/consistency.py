"""
consistency
==========
Make the SAME reagent carry the SAME value across the protocol. After AI fill,
the same item (e.g. "complete medium", a kit) can get different suggested amounts/
vendors/catalogs in different steps. This pass groups slots by reagent identity +
field kind and aligns the non-confirmed ones to a single canonical value:

  - prefer a CONFIRMED value if one exists in the group (propagate it as a suggestion);
  - else the most common suggested value;
  - never overwrite a user/source/kit/calc-confirmed slot.

Deterministic; applies through value_promoter so provenance + tree-safety hold.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from . import uncertainty_slots as us
from . import slot_roles


def _field_kind(obj: Dict[str, Any]) -> Optional[str]:
    et = obj.get("expected_type")
    if et in ("material_amount", "volume", "mass"):
        return "amount"
    if et in ("vendor", "catalog_number"):
        return et
    return None


def _norm(v) -> str:
    return " ".join(str(v or "").split()).casefold()


def normalize(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Align same-reagent values across steps. Returns the changes made."""
    reg = us.registry(proto)
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for o in reg.values():
        item = slot_roles._reagent_item(proto, o["slot_id"])
        fk = _field_kind(o)
        if item and fk:
            groups.setdefault((item.strip().lower(), fk), []).append(o)

    from . import value_promoter as vp
    changes: List[Dict[str, Any]] = []
    for (item, fk), objs in groups.items():
        if len(objs) < 2:
            continue
        # canonical value
        confirmed = [o for o in objs if o.get("status") in us.CONFIRMED
                     and us._looks_filled(o.get("current_value"))]
        if confirmed:
            canon = confirmed[0]["current_value"]
        else:
            cands = [o.get("recommended_candidate") for o in objs if o.get("recommended_candidate")]
            if not cands:
                continue
            # most common (by normalized form), keep an actual original spelling
            top = Counter(_norm(c) for c in cands).most_common(1)[0][0]
            canon = next(c for c in cands if _norm(c) == top)
        # align the non-confirmed, differing slots
        for o in objs:
            if o.get("status") in us.CONFIRMED:
                continue
            if _norm(o.get("recommended_candidate")) == _norm(canon):
                continue
            try:
                vp.apply(proto, o["slot_id"], "ai_suggested", canon,
                         {"evidence_class": "ai_suggested", "source_name": "system:consistency",
                          "rationale": f"aligned with other '{item}' steps for consistency",
                          "confidence": 0.4}, "system:consistency")
                changes.append({"slot_id": o["slot_id"], "item": item, "field": fk, "new": canon})
            except vp.PromotionError:
                pass
    return changes
