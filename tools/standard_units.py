"""
standard_units
=============
The standardization core: parse a messy lab quantity ("250 µL", "1.5 µg",
"10 ng/µL", "2 µM", "2.5 × 10^5 cells", "37 °C") into a normalized internal
representation, and convert within a dimension.

Goal (Phase 1 of the redesign): every protocol value normalizes to ONE canonical
unit per dimension, so downstream scaling / dependency recompute is exact and
auditable. Pure-local, deterministic, no model calls.

Canonical units:
  mass         -> ng
  volume       -> uL
  molarity     -> M
  amount       -> mol
  concentration (mass/vol) -> ng/uL
  count (cells)-> cells
  enzyme       -> U
  temperature  -> C
  od           -> OD
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# --------------------------------------------------------------------------- #
# unit tables: factor TO the canonical unit of each dimension
# --------------------------------------------------------------------------- #
_MASS = {"pg": 1e-3, "ng": 1.0, "ug": 1e3, "µg": 1e3, "μg": 1e3, "mcg": 1e3,
         "mg": 1e6, "g": 1e9, "kg": 1e12}
_VOLUME = {"nl": 1e-3, "nL": 1e-3, "ul": 1.0, "uL": 1.0, "µl": 1.0, "µL": 1.0,
           "μl": 1.0, "μL": 1.0, "ml": 1e3, "mL": 1e3, "l": 1e6, "L": 1e6}
_MOLARITY = {"M": 1.0, "mM": 1e-3, "uM": 1e-6, "µM": 1e-6, "μM": 1e-6,
             "nM": 1e-9, "pM": 1e-12, "fM": 1e-15}
_AMOUNT = {"fmol": 1e-15, "pmol": 1e-12, "nmol": 1e-9, "umol": 1e-6, "µmol": 1e-6,
           "μmol": 1e-6, "mmol": 1e-3, "mol": 1.0}
_ENZYME = {"U": 1.0, "u": 1.0, "units": 1.0, "unit": 1.0}
_COUNT = {"cells": 1.0, "cell": 1.0, "nuclei": 1.0, "nucleus": 1.0}
_OD = {"od": 1.0, "od600": 1.0}

# dimension -> (table, canonical_unit)
_DIMENSIONS = {
    "mass": (_MASS, "ng"),
    "volume": (_VOLUME, "uL"),
    "molarity": (_MOLARITY, "M"),
    "amount": (_AMOUNT, "mol"),
    "enzyme": (_ENZYME, "U"),
    "count": (_COUNT, "cells"),
    "od": (_OD, "OD"),
}

# superscript digits -> ascii
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


@dataclass
class Quantity:
    value: float
    unit: str
    dimension: str
    canonical_value: float
    canonical_unit: str

    def as_dict(self):
        return {"value": self.value, "unit": self.unit, "dimension": self.dimension,
                "canonical_value": self.canonical_value, "canonical_unit": self.canonical_unit}


# --------------------------------------------------------------------------- #
# number parsing (handles 2.5e5, 2.5 × 10^5, 2.5×10⁵, 1e6, plain floats, commas)
# --------------------------------------------------------------------------- #
def parse_number(text: str) -> Optional[float]:
    s = str(text or "").strip().translate(_SUP)
    s = s.replace(",", "")
    # "2.5 × 10⁵" already had superscripts translated -> "2.5 × 105"; handle generic forms:
    # a ×/x 10 ^ b   OR   a ×/x 10 b
    s = re.sub(r"(?i)([0-9.]+)\s*[×x]\s*10\s*\^?\s*([+-]?[0-9]+)", r"\1e\2", s)
    s = s.replace("^", "")
    m = re.search(r"[-+]?[0-9]*\.?[0-9]+(?:e[-+]?[0-9]+)?", s, re.I)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _lookup_unit(unit: str) -> Optional[Tuple[str, float, str]]:
    """Return (dimension, factor_to_canonical, canonical_unit) for a unit token."""
    u = unit.strip()
    for dim, (table, canon) in _DIMENSIONS.items():
        if u in table:
            return dim, table[u], canon
        if u.lower() in table:               # case-insensitive fallback (cells, od…)
            return dim, table[u.lower()], canon
    return None


# --------------------------------------------------------------------------- #
# concentration (mass / volume), e.g. "ng/µL", "µg/mL"
# --------------------------------------------------------------------------- #
def _parse_concentration(value: float, unit: str) -> Optional[Quantity]:
    m = re.match(r"\s*([a-zµμ]+)\s*/\s*([a-zµμ]+)\s*$", unit, re.I)
    if not m:
        return None
    mass_u, vol_u = m.group(1), m.group(2)
    if mass_u not in _MASS or vol_u not in _VOLUME:
        return None
    # 1 (mass_u/vol_u) expressed in the canonical ng/uL
    factor = _MASS[mass_u] / _VOLUME[vol_u]
    return Quantity(value=value, unit=f"{mass_u}/{vol_u}", dimension="concentration",
                    canonical_value=value * factor, canonical_unit="ng/uL")


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def parse_quantity(text: str) -> Optional[Quantity]:
    """Parse '250 µL' / '2.5 × 10^5 cells' / '10 ng/µL' / '37 °C' into a Quantity."""
    s = str(text or "").strip()
    if not s:
        return None
    val = parse_number(s)
    if val is None:
        return None

    # temperature first (special: not a simple factor table)
    if re.search(r"°?\s*c\b", s, re.I) and not re.search(r"[a-z]/[a-z]", s, re.I):
        if re.search(r"(?i)\b(?:od|cells?|nuclei)\b", s) is None:
            return Quantity(val, "C", "temperature", val, "C")

    # strip the numeric part to isolate the unit token(s)
    unit_part = s.translate(_SUP)
    unit_part = re.sub(r"(?i)[0-9.,]+\s*[×x]\s*10\s*\^?\s*[+-]?[0-9]+", "", unit_part)
    unit_part = re.sub(r"[-+]?[0-9]*\.?[0-9]+(?:e[-+]?[0-9]+)?", "", unit_part, flags=re.I)
    unit_part = unit_part.replace("^", "").strip()

    # concentration (mass/vol)
    if "/" in unit_part:
        conc = _parse_concentration(val, unit_part)
        if conc:
            return conc

    # single-token unit
    token = unit_part.split()[0] if unit_part.split() else unit_part
    hit = _lookup_unit(token)
    if hit:
        dim, factor, canon = hit
        return Quantity(val, token, dim, val * factor, canon)
    return None


def to_canonical(text_or_value, unit: Optional[str] = None) -> Optional[float]:
    """Canonical-unit magnitude for a quantity. Accepts a string ('1.5 µg') or
    (value, unit)."""
    if unit is None:
        q = parse_quantity(str(text_or_value))
        return q.canonical_value if q else None
    q = parse_quantity(f"{text_or_value} {unit}")
    return q.canonical_value if q else None


def convert(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    """Convert a value between two units of the SAME dimension."""
    a = _lookup_unit(from_unit)
    b = _lookup_unit(to_unit)
    if a and b and a[0] == b[0]:
        # value -> canonical -> target
        return value * a[1] / b[1]
    # concentration
    ca = _parse_concentration(1.0, from_unit)
    cb = _parse_concentration(1.0, to_unit)
    if ca and cb:
        return value * ca.canonical_value / cb.canonical_value
    return None


def same_dimension(unit_a: str, unit_b: str) -> bool:
    a, b = _lookup_unit(unit_a), _lookup_unit(unit_b)
    if a and b:
        return a[0] == b[0]
    return bool(_parse_concentration(1, unit_a)) and bool(_parse_concentration(1, unit_b))
