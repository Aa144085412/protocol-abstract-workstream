"""
sanity_check
============
Domain plausibility check. Source-confirmed values (a user's uploaded ground truth)
don't need a per-value audit — but they CAN be wrong. This flags values that are
*obviously off* for a wet-lab biology/chemistry protocol: negatives, impossible
magnitudes, out-of-range pH/temperature, absurd centrifuge speeds, etc.

Conservative by design — it only flags values that violate hard physical/chemical
limits, so a flag almost always means a real typo or unit error, not a judgment call.
Deterministic; no model calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import standard_units as su

# canonical-unit plausibility bounds (only obvious impossibilities)
_TEMP_MIN_C, _TEMP_MAX_C = -210.0, 300.0       # LN2 ≈ -196; autoclave/bake up to ~250
_MOLARITY_MAX_M = 60.0                          # pure water ≈ 55 M; stocks rarely exceed
_VOLUME_MAX_UL = 5.0e7                          # 50 L — absurd for a bench step
_MASS_MAX_NG = 1.0e15                           # 1 kg — absurd for a reagent amount
_CELLS_MAX = 1.0e15                             # absurd cell count
_GFORCE_MAX = 1.5e6                             # ultracentrifuges top out ~1,000,000 × g
_RPM_MAX = 150000.0


def _label(o: Dict[str, Any]) -> str:
    return f"{o.get('step_id') or 'material'} · {o.get('field_name', 'value')}"


# nucleic-acid items are measured by MASS (ng/µg) or molarity — never enzyme "units"
_DNA_KW = ("dsdna", "ssdna", "dna", "insert", "vector", "backbone", "plasmid", "amplicon",
           "fragment", "gblock", "oligo", "template", "rna", "construct")
# transfection/transduction reagents that should carry a WORKING CONCENTRATION, not a bare volume
_TRANSFECT_KW = ("polybrene", "hexadimethrine", "lipofectamine", "pei", "fugene",
                 "transfection reagent", "protamine")


def _resolve_item_name(proto: Dict[str, Any], o: Dict[str, Any]) -> str:
    """Best-effort reagent/material NAME for a slot, so unit checks know what the value
    describes (the registry object only stores field_name, not the item)."""
    sid = str(o.get("slot_id", ""))
    try:
        if sid.startswith("mat:"):
            idx = int(sid.split(":")[1])
            mats = proto.get("materials", []) or []
            if 0 <= idx < len(mats):
                return str(mats[idx].get("item", "")).lower()
        elif sid.startswith("step:") and ":reag:" in sid:
            parts = sid.split(":")
            step_id, ri = parts[1], int(parts[3])
            for s in proto.get("workflow", []) or []:
                if s.get("step_id") == step_id:
                    reags = s.get("reagents", []) or []
                    if 0 <= ri < len(reags):
                        return str(reags[ri].get("item", "")).lower()
    except (ValueError, IndexError):
        pass
    return str(o.get("field_name", "")).lower()


def _check_value(o: Dict[str, Any], val: str, name: str = "") -> Optional[str]:
    """Return a human reason if the value is implausible for the domain, else None."""
    s = str(val or "").strip()
    if not s:
        return None
    num = su.parse_number(s)
    name = (name or str(o.get("field_name", ""))).lower()

    # 1) negatives are never valid for a lab quantity
    if num is not None and num < 0:
        return "negative value — likely a typo or sign error"

    # 2) wrong KIND of unit for a nucleic acid: 'U'/'unit' is enzyme activity, not DNA amount
    import re as _re
    if any(k in name for k in _DNA_KW) and "enzyme" not in name and "ligase" not in name \
            and "polymerase" not in name and "phosphatase" not in name:
        if _re.search(r"\b\d+(\.\d+)?\s*(u|units?)\b", s, _re.I) and "µ" not in s and "/" not in s:
            return ("a DNA/nucleic-acid amount should be a MASS (ng/µg) or molarity, not enzyme "
                    "'units' (U) — e.g. '1 U' likely means '1 ng'")

    # 3) a transfection/transduction reagent given as a bare VOLUME needs a working concentration.
    #    BUT if it's a known reagent we can resolve from the standard-working-conc table, don't
    #    flag it (no redundant flag — the auto-fill corrects it instead).
    if any(k in name for k in _TRANSFECT_KW):
        from . import known_reagents
        if known_reagents.lookup(name):
            return None
        q = su.parse_quantity(s)
        if q is not None and q.dimension == "volume":
            return ("specify a WORKING CONCENTRATION (e.g. ~8 µg/mL final), not just a volume — "
                    "it comes as a stock, so the volume alone is meaningless")

    # 2) pH (by field name / explicit 'pH') must be 0–14
    field = (o.get("field_name", "") + " " + s).lower()
    if "ph" in re.findall(r"[a-z]+", field) or re.search(r"\bph\b", s, re.I):
        if num is not None and (num < 0 or num > 14):
            return f"pH {num:g} is outside the possible range 0–14"

    # 3) centrifuge speed: g-force or rpm
    if re.search(r"[×x]\s*g\b|\brcf\b|\bg\s*force", s, re.I):
        if num is not None and num > _GFORCE_MAX:
            return f"{num:g} × g exceeds any real centrifuge (>~1,000,000 × g)"
    if re.search(r"\brpm\b", s, re.I) and num is not None and num > _RPM_MAX:
        return f"{num:g} rpm is faster than any lab centrifuge"

    # 4) dimensioned quantities, checked in canonical units
    q = su.parse_quantity(s)
    if q is not None:
        dim, can = q.dimension, q.canonical_value
        if dim == "temperature" and not (_TEMP_MIN_C <= can <= _TEMP_MAX_C):
            return f"{can:g} °C is outside a plausible lab range ({_TEMP_MIN_C:g}–{_TEMP_MAX_C:g} °C)"
        if dim == "molarity" and can > _MOLARITY_MAX_M:
            return f"{can:g} M is chemically impossible (water itself is ≈55 M)"
        if dim == "volume" and can > _VOLUME_MAX_UL:
            return f"{can/1e6:g} L is implausibly large for a single step"
        if dim == "mass" and can > _MASS_MAX_NG:
            return f"{can/1e9:g} g is implausibly large for a reagent amount"
        if dim == "count" and can > _CELLS_MAX:
            return f"{can:g} cells is implausibly large"
    return None


def flag(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scan every filled value (confirmed OR suggested) and return the implausible ones:
    [{slot_id, label, value, reason, status}]. Empty list = nothing looks off."""
    reg = proto.get("uncertainty", {}) or {}
    out: List[Dict[str, Any]] = []
    for o in reg.values():
        if o.get("status") == "not_applicable":
            continue
        val = o.get("current_value") or o.get("recommended_candidate")
        if not val:
            continue
        reason = _check_value(o, val, _resolve_item_name(proto, o))
        if reason:
            out.append({"slot_id": o.get("slot_id"), "label": _label(o),
                        "value": val, "reason": reason, "status": o.get("status")})
    return out
