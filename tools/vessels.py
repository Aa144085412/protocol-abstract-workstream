"""
vessels
=======
Standard cell-culture vessel geometry + context-aware scaling. Lets the agent
rescale area-dependent values (cell number, seeding) and volume-dependent values
(media, wash, reagents) when the user switches vessel — instead of making them
recompute by hand.

Values are standard Corning/Thermo growth areas (cm2) and typical working volumes
(mL). Pure-local, deterministic, no model calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import standard_units as su

# key -> {name, format, area_cm2, working_volume_mL}
VESSELS: Dict[str, Dict[str, Any]] = {
    "t25":  {"name": "T25 flask",  "format": "flask", "area_cm2": 25.0,  "working_volume_mL": 5.0},
    "t75":  {"name": "T75 flask",  "format": "flask", "area_cm2": 75.0,  "working_volume_mL": 12.0},
    "t175": {"name": "T175 flask", "format": "flask", "area_cm2": 175.0, "working_volume_mL": 25.0},
    "t225": {"name": "T225 flask", "format": "flask", "area_cm2": 225.0, "working_volume_mL": 35.0},
    "dish_6cm":  {"name": "6 cm dish",  "format": "dish", "area_cm2": 21.0,  "working_volume_mL": 4.0},
    "dish_10cm": {"name": "10 cm dish", "format": "dish", "area_cm2": 56.7, "working_volume_mL": 10.0},
    "dish_15cm": {"name": "15 cm dish", "format": "dish", "area_cm2": 152.0, "working_volume_mL": 22.0},
    "plate_6":   {"name": "6-well plate",  "format": "plate", "area_cm2": 9.6, "working_volume_mL": 2.0},
    "plate_12":  {"name": "12-well plate", "format": "plate", "area_cm2": 3.8, "working_volume_mL": 1.0},
    "plate_24":  {"name": "24-well plate", "format": "plate", "area_cm2": 1.9, "working_volume_mL": 0.5},
    "plate_48":  {"name": "48-well plate", "format": "plate", "area_cm2": 1.1, "working_volume_mL": 0.3},
    "plate_96":  {"name": "96-well plate", "format": "plate", "area_cm2": 0.32, "working_volume_mL": 0.1},
    "plate_384": {"name": "384-well plate", "format": "plate", "area_cm2": 0.056, "working_volume_mL": 0.025},
}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", str(s or "").lower())


def resolve(vessel: str) -> Optional[str]:
    """Map a free-text vessel name to a VESSELS key. Handles 'T75', 't-75',
    '75 cm2 flask', '10 cm dish', '100 mm', '6-well', '6 well plate', etc."""
    if not vessel:
        return None
    n = _norm(vessel)
    if n in VESSELS:
        return n
    # flasks: T25/T75/T175/T225 (also '75cm2')
    m = re.search(r"t?(\d{2,3})(?:cm2)?", n)
    if "flask" in n or n.startswith("t") or "cm2flask" in n:
        if m and f"t{m.group(1)}" in VESSELS:
            return f"t{m.group(1)}"
    # dishes: '10cm', '100mm', '6cm', '60mm', '15cm', '150mm'
    md = re.search(r"(\d{1,3})(cm|mm)", n)
    if "dish" in n or md:
        if md:
            v = int(md.group(1))
            if md.group(2) == "mm":
                v = round(v / 10)
            key = f"dish_{v}cm"
            if key in VESSELS:
                return key
    # well plates: '6well', '96wellplate', '24w'
    mw = re.search(r"(\d{1,3})\s*w(?:ell)?", n)
    if "well" in n or "plate" in n or mw:
        if mw and f"plate_{int(mw.group(1))}" in VESSELS:
            return f"plate_{int(mw.group(1))}"
    return None


def get_vessel(vessel: str) -> Optional[Dict[str, Any]]:
    key = resolve(vessel)
    return {**VESSELS[key], "key": key} if key else None


def list_vessels() -> List[Dict[str, Any]]:
    return [{**v, "key": k} for k, v in VESSELS.items()]


# --------------------------------------------------------------------------- #
# scaling
# --------------------------------------------------------------------------- #
def ratio(from_vessel: str, to_vessel: str, kind: str = "area") -> Optional[float]:
    """Scaling factor from one vessel to another.
    kind='area'   -> growth-area ratio (cell number, seeding, area-dependent)
    kind='volume' -> working-volume ratio (media, wash, reagent volumes)."""
    a, b = get_vessel(from_vessel), get_vessel(to_vessel)
    if not a or not b:
        return None
    field = "area_cm2" if kind == "area" else "working_volume_mL"
    if not a.get(field):
        return None
    return b[field] / a[field]


def scale(value: float, from_vessel: str, to_vessel: str, kind: str = "area") -> Optional[float]:
    r = ratio(from_vessel, to_vessel, kind)
    return None if r is None else value * r


def scale_value_str(text: str, from_vessel: str, to_vessel: str,
                    kind: str = "area") -> Optional[str]:
    """Scale a quantity string ('2 mL', '5×10^5 cells') to a new vessel, preserving
    the unit. Returns a formatted string or None."""
    num = su.parse_number(text)
    r = ratio(from_vessel, to_vessel, kind)
    if num is None or r is None:
        return None
    scaled = num * r
    q = su.parse_quantity(text)
    unit = q.unit if q else ""
    if scaled >= 1e4 or (0 < scaled < 1e-2):
        body = f"{scaled:.2e}"
    else:
        body = f"{scaled:.3g}"
    return f"{body} {unit}".strip()


# --------------------------------------------------------------------------- #
# recommendations (used by the future defaults engine)
# --------------------------------------------------------------------------- #
def recommend_seeding(vessel: str, density_per_cm2: float) -> Optional[Dict[str, Any]]:
    """Cells to seed = density (cells/cm2) x growth area."""
    v = get_vessel(vessel)
    if not v:
        return None
    cells = density_per_cm2 * v["area_cm2"]
    return {"vessel": v["name"], "area_cm2": v["area_cm2"],
            "density_per_cm2": density_per_cm2, "cells": cells,
            "explanation": f"{density_per_cm2:.2e} cells/cm² × {v['area_cm2']} cm² "
                           f"= {cells:.2e} cells for a {v['name']}"}


def recommend_media(vessel: str) -> Optional[Dict[str, Any]]:
    v = get_vessel(vessel)
    if not v:
        return None
    return {"vessel": v["name"], "working_volume_mL": v["working_volume_mL"],
            "explanation": f"typical working volume for a {v['name']} is "
                           f"{v['working_volume_mL']} mL"}
