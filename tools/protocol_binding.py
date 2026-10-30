"""
protocol_binding
===============
Live graph binding: when an experiment-intent value changes (vessel, cell number),
recompute the REAL dependent slots — identified by their semantic role
(slot_roles) — and apply the results as explained, recomputed SUGGESTIONS through
value_promoter (so provenance + tree-safety hold; the user can accept or lock).

This is the bridge between protocol_graph (the engine) and the actual protocol's
uncertainty slots. Deterministic transforms (vessels); no model calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import slot_roles, vessels, standard_units


def plan_rescale_to_vessel(proto: Dict[str, Any], new_vessel: str,
                           from_vessel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Propose updates for role-tagged slots when the vessel changes. Returns a
    list of {slot_id, role, old, new, explanation} — does NOT mutate."""
    slot_roles.tag_roles(proto)
    nv = vessels.get_vessel(new_vessel)
    if not nv:
        return []
    out: List[Dict[str, Any]] = []
    # media / wash volumes follow the new vessel's working volume
    for role, label in (("media_volume", "media volume"), ("wash_volume", "wash volume")):
        for o in slot_roles.slots_with_role(proto, role):
            old = o.get("current_value")
            if role == "wash_volume" and from_vessel and standard_units.parse_number(str(old)) is not None:
                # wash scales proportionally with working volume if a current value exists
                new = vessels.scale_value_str(str(old), from_vessel, new_vessel, kind="volume")
            else:
                new = f"{nv['working_volume_mL']} mL"
            if not new:
                continue
            out.append({"slot_id": o["slot_id"], "role": role, "old": old, "new": new,
                        "explanation": f"{label} → {new} (working volume for {nv['name']})"})
    return out


def _apply(proto: Dict[str, Any], changes: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    """Apply recomputed values via value_promoter (suggestions), never overwriting a
    genuinely confirmed value."""
    from . import value_promoter as vp
    from . import uncertainty_slots as us
    for c in changes:
        ob = us.get(proto, c["slot_id"])
        if ob and ob.get("status") in us.CONFIRMED and not ob.get("legacy_imported"):
            c["skipped"] = "confirmed value left unchanged"
            continue
        try:
            vp.apply(proto, c["slot_id"], "typical_range", c["new"],
                     {"evidence_class": "typical_range", "source_name": source,
                      "rationale": c["explanation"], "confidence": 0.5}, f"system:{source}")
        except vp.PromotionError:
            # e.g. a (legacy) confirmed value the promoter won't downgrade to a
            # suggestion — leave it as-is rather than crashing the rescale.
            c["skipped"] = "confirmed value kept (rescale not applied)"
    return changes


def apply_rescale_to_vessel(proto: Dict[str, Any], new_vessel: str, user_email: str,
                            from_vessel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Apply plan_rescale_to_vessel as recomputed suggestions (provenance preserved)."""
    return _apply(proto, plan_rescale_to_vessel(proto, new_vessel, from_vessel),
                  "protocol_graph:vessel")


# --------------------------------------------------------------------------- #
# cell-number cascade: lysis volume + RNA-yield estimate derive from cell count
# --------------------------------------------------------------------------- #
_LYSIS_UL_PER_CELL = 1e-4        # ~100 µL lysis buffer per 1e6 cells (suggestion-grade)
_RNA_NG_PER_CELL = 0.015         # ~15 µg total RNA per 1e6 mammalian cells


def plan_rescale_to_cells(proto: Dict[str, Any], cells_value) -> List[Dict[str, Any]]:
    """Propose lysis-volume updates derived from a new cell number. Read-only."""
    slot_roles.tag_roles(proto)
    n = standard_units.parse_number(str(cells_value))
    if not n:
        return []
    out: List[Dict[str, Any]] = []
    for o in slot_roles.slots_with_role(proto, "lysis_volume"):
        vol = n * _LYSIS_UL_PER_CELL
        new = f"{vol:.0f} µL" if vol >= 1 else f"{vol:.2g} µL"
        out.append({"slot_id": o["slot_id"], "role": "lysis_volume", "old": o.get("current_value"),
                    "new": new,
                    "explanation": f"lysis volume → {new} (≈{_LYSIS_UL_PER_CELL:.0e} µL/cell "
                                   f"× {n:.2e} cells)"})
    return out


def apply_rescale_to_cells(proto: Dict[str, Any], cells_value, user_email: str) -> List[Dict[str, Any]]:
    return _apply(proto, plan_rescale_to_cells(proto, cells_value), "protocol_graph:cells")


def estimate_rna_yield(cells_value) -> Optional[Dict[str, Any]]:
    """Informational expected-RNA-yield estimate from a cell number (not a slot)."""
    n = standard_units.parse_number(str(cells_value))
    if not n:
        return None
    ng = n * _RNA_NG_PER_CELL
    body = f"{ng / 1000:.1f} µg" if ng >= 1000 else f"{ng:.0f} ng"
    return {"ng": ng, "display": body,
            "explanation": f"≈{_RNA_NG_PER_CELL} ng/cell × {n:.2e} cells = {body} total RNA (estimate)"}
