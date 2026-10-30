"""
reaction_scaling
===============
Per-reaction → per-assay scaling. Standardized values are stated PER REACTION;
this scales them to N reactions with an overage (pipetting excess) to build a
master mix. Deterministic; reuses standard_units for parsing/formatting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import standard_units as su


def _fmt(value: float, unit: str) -> str:
    if unit and unit.lower() in ("ul", "µl", "μl") and value >= 1000:
        return f"{value / 1000:.2f} mL"          # tidy large µL into mL
    if value >= 100:
        return f"{value:.0f} {unit}".strip()
    return f"{value:.3g} {unit}".strip()


def scale_per_reaction(per_rxn: str, n_reactions: int,
                       overage_frac: float = 0.1) -> Optional[str]:
    """Total for N reactions including overage: per_rxn × N × (1 + overage)."""
    num = su.parse_number(per_rxn)
    if num is None or not n_reactions:
        return None
    q = su.parse_quantity(per_rxn)
    unit = q.unit if q else ""
    return _fmt(num * n_reactions * (1.0 + overage_frac), unit)


def master_mix(components: List[Dict[str, Any]], n_reactions: int,
               overage_frac: float = 0.1) -> Dict[str, Any]:
    """components: [{name, per_rxn}]. Returns per-component per-rxn + scaled total."""
    rows = []
    for c in components:
        total = scale_per_reaction(str(c.get("per_rxn", "")), n_reactions, overage_frac)
        rows.append({"name": c.get("name", ""), "per_rxn": c.get("per_rxn", ""),
                     "total": total})
    return {"n_reactions": n_reactions, "overage_frac": overage_frac,
            "reactions_with_overage": round(n_reactions * (1.0 + overage_frac), 2),
            "rows": rows,
            "note": f"Totals = per-reaction × {n_reactions} × {1 + overage_frac:.2f} "
                    f"(includes {int(overage_frac * 100)}% overage)."}
