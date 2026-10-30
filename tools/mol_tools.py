"""
mol_tools
=========
Deterministic molecular-biology bench calculators (no model, no source needed):

- ligation_insert_ng: ng of insert for a target insert:vector molar ratio.
- dilution: C1V1 = C2V2 (solve for the unknown).
- cell_seeding: total cells + volume needed to seed N wells at a density, and
  how much stock cell suspension to add.
- molarity helpers (ng <-> pmol for dsDNA).

All return a dict with the result plus a short, human-readable explanation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Average MW of a dsDNA base pair ~ 650 g/mol
BP_MW = 650.0


def dsdna_pmol(ng: float, length_bp: float) -> Optional[float]:
    """pmol of dsDNA from mass (ng) and length (bp)."""
    if not length_bp or length_bp <= 0:
        return None
    # ng / (bp * 650 g/mol) -> mol; *1e3 (ng->ug?) handle units:
    # mass_g = ng*1e-9; mol = mass_g/(bp*650); pmol = mol*1e12
    return round((ng * 1e-9) / (length_bp * BP_MW) * 1e12, 4)


def ligation_insert_ng(vector_ng: float, vector_bp: float, insert_bp: float,
                       molar_ratio: float = 3.0) -> Dict[str, Any]:
    """ng of insert to use for a given insert:vector molar ratio."""
    if min(vector_ng, vector_bp, insert_bp) <= 0:
        return {"error": "Enter positive vector ng, vector bp, and insert bp."}
    # insert_ng = vector_ng * (insert_bp/vector_bp) * molar_ratio
    insert_ng = vector_ng * (insert_bp / vector_bp) * molar_ratio
    v_pmol = dsdna_pmol(vector_ng, vector_bp)
    i_pmol = dsdna_pmol(insert_ng, insert_bp)
    return {
        "insert_ng": round(insert_ng, 1),
        "vector_pmol": v_pmol, "insert_pmol": i_pmol,
        "ratio": molar_ratio,
        "explain": (f"For a {molar_ratio}:1 insert:vector molar ratio with {vector_ng:g} ng "
                    f"vector ({vector_bp:g} bp) and a {insert_bp:g} bp insert, use "
                    f"~{round(insert_ng,1)} ng insert. Include a vector-only (no-insert) "
                    "ligation control."),
    }


def dilution(c1: Optional[float], v1: Optional[float], c2: Optional[float],
             v2: Optional[float], unit_c: str = "", unit_v: str = "") -> Dict[str, Any]:
    """Solve C1V1 = C2V2 for the single missing value (pass it as None)."""
    vals = [c1, v1, c2, v2]
    missing = [i for i, v in enumerate(vals) if v in (None, "")]
    if len(missing) != 1:
        return {"error": "Leave exactly ONE field blank to solve for it."}
    try:
        c1f = None if c1 in (None, "") else float(c1)
        v1f = None if v1 in (None, "") else float(v1)
        c2f = None if c2 in (None, "") else float(c2)
        v2f = None if v2 in (None, "") else float(v2)
    except ValueError:
        return {"error": "Enter numbers."}
    idx = missing[0]
    try:
        if idx == 0:
            res = c2f * v2f / v1f; field = "C1 (stock concentration)"
        elif idx == 1:
            res = c2f * v2f / c1f; field = "V1 (stock volume to use)"
        elif idx == 2:
            res = c1f * v1f / v2f; field = "C2 (final concentration)"
        else:
            res = c1f * v1f / c2f; field = "V2 (final volume)"
    except (ZeroDivisionError, TypeError):
        return {"error": "Division by zero — check inputs."}
    out = {"result": round(res, 4), "field": field}
    # helpful diluent volume when solving for V1
    if idx == 1 and v2f is not None:
        out["diluent_to_add"] = round(v2f - res, 4)
        out["explain"] = (f"Add {round(res,4)} {unit_v} of stock + "
                          f"{round(v2f-res,4)} {unit_v} diluent → {v2f:g} {unit_v} "
                          f"at {c2f:g} {unit_c}.")
    else:
        out["explain"] = f"{field} = {round(res,4)} (C1·V1 = C2·V2)."
    return out


def cell_seeding(target_density: float, volume_per_well_uL: float, n_wells: int,
                 stock_cells_per_mL: float, extra_pct: float = 10.0) -> Dict[str, Any]:
    """Compute cells needed and how much stock suspension to add to seed wells.

    target_density: cells per WELL (e.g. 200000) — treat as cells/well.
    """
    if min(target_density, volume_per_well_uL, n_wells, stock_cells_per_mL) <= 0:
        return {"error": "Enter positive values."}
    factor = 1 + extra_pct / 100.0
    total_cells = target_density * n_wells * factor
    stock_per_uL = stock_cells_per_mL / 1000.0
    stock_volume_uL = total_cells / stock_per_uL if stock_per_uL else 0
    total_volume_uL = volume_per_well_uL * n_wells * factor
    medium_raw = total_volume_uL - stock_volume_uL          # negative => infeasible
    required_per_mL = (total_cells / total_volume_uL) * 1000.0 if total_volume_uL else 0
    warning = ""
    if stock_volume_uL > total_volume_uL + 1e-6:
        warning = (f"Infeasible as set: the wells need ~{required_per_mL:,.0f} cells/mL but the stock "
                   f"is only {stock_cells_per_mL:,.0f} cells/mL — you can't reach this density by "
                   f"adding medium. Concentrate the cells (spin & resuspend) to ≥ "
                   f"{required_per_mL:,.0f} cells/mL, lower the density, or use a larger volume/well.")
    elif abs(medium_raw) < 1e-6:
        warning = "No dilution needed — stock concentration equals the seeding density; use it undiluted."
    medium_uL = max(medium_raw, 0)
    explain = (f"For {n_wells} wells at {target_density:g} cells/well (+{extra_pct:g}% excess): "
               f"need ~{int(round(total_cells))} cells in {round(total_volume_uL,1)} µL "
               f"(≈{required_per_mL:,.0f} cells/mL). ")
    if not warning or "undiluted" in warning:
        explain += (f"Add {round(stock_volume_uL,1)} µL stock ({stock_cells_per_mL:g} cells/mL) + "
                    f"{round(medium_uL,1)} µL medium; dispense {volume_per_well_uL:g} µL/well.")
    return {
        "total_cells_needed": int(round(total_cells)),
        "stock_to_add_uL": round(stock_volume_uL, 1),
        "medium_to_add_uL": round(medium_uL, 1),
        "master_mix_volume_uL": round(total_volume_uL, 1),
        "required_cells_per_mL": int(round(required_per_mL)),
        "warning": warning,
        "explain": explain,
    }
