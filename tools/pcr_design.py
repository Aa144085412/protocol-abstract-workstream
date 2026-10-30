"""
pcr_design
==========
Compute a PCR setup deterministically from primer sequences + polymerase — no
guessing, no external source needed.

- Primer Tm via nearest-neighbor thermodynamics (SantaLucia 1998 unified params,
  salt-corrected).
- Annealing temperature from the lower primer Tm with a polymerase-specific rule.
- Extension time from amplicon length and the polymerase's extension rate.
- Standard reaction composition and a thermocycling program per polymerase.

These are calculated estimates following standard manufacturer guidance; the user
should still verify against their specific enzyme datasheet.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

# SantaLucia 1998 unified nearest-neighbor parameters (ΔH kcal/mol, ΔS cal/mol·K)
_NN_H = {
    "AA": -7.6, "TT": -7.6, "AT": -7.2, "TA": -7.2, "CA": -8.5, "TG": -8.5,
    "GT": -8.4, "AC": -8.4, "CT": -7.8, "AG": -7.8, "GA": -8.2, "TC": -8.2,
    "CG": -10.6, "GC": -9.8, "GG": -8.0, "CC": -8.0,
}
_NN_S = {
    "AA": -21.3, "TT": -21.3, "AT": -20.4, "TA": -21.3, "CA": -22.7, "TG": -22.7,
    "GT": -22.4, "AC": -22.4, "CT": -21.0, "AG": -21.0, "GA": -22.2, "TC": -22.2,
    "CG": -27.2, "GC": -24.4, "GG": -19.9, "CC": -19.9,
}


def clean_seq(seq: str) -> str:
    return re.sub(r"[^ACGT]", "", str(seq or "").upper())


def gc_percent(seq: str) -> Optional[float]:
    s = clean_seq(seq)
    if not s:
        return None
    return round(100.0 * (s.count("G") + s.count("C")) / len(s), 1)


def tm_nn(seq: str, primer_uM: float = 0.5, na_mM: float = 50.0) -> Optional[float]:
    """Nearest-neighbor primer Tm (°C), salt-corrected."""
    s = clean_seq(seq)
    if len(s) < 2:
        return None
    dH = dS = 0.0
    for i in range(len(s) - 1):
        pair = s[i:i + 2]
        dH += _NN_H[pair]
        dS += _NN_S[pair]
    # initiation penalties for each terminal base
    for end in (s[0], s[-1]):
        if end in "AT":
            dH += 2.3; dS += 4.1
        else:
            dH += 0.1; dS += -2.8
    na = max(na_mM, 1e-3) / 1000.0
    dS += 0.368 * (len(s) - 1) * math.log(na)
    R = 1.987
    ct = max(primer_uM, 1e-3) * 1e-6
    try:
        tm = (dH * 1000.0) / (dS + R * math.log(ct / 4.0)) - 273.15
    except (ValueError, ZeroDivisionError):
        return None
    return round(tm, 1)


# polymerase presets: extension rate (s/kb), anneal rule, recipe (per 50 uL), cycling
_POLYMERASES = {
    "Q5 (NEB)": {
        "ext_s_per_kb": 30, "denat": "98 C, 10 s", "init_denat": "98 C, 30 s",
        "anneal_rule": lambda lo: round(lo),   # NEB Q5: use the lower primer Tm
        "final_ext": "72 C, 2 min", "cycles": 30,
        "recipe": [("Q5 2X Master Mix", "25 uL"), ("Forward primer (10 uM)", "2.5 uL"),
                   ("Reverse primer (10 uM)", "2.5 uL"), ("Template DNA", "1-10 ng (var.)"),
                   ("Nuclease-free water", "to 50 uL")],
    },
    "Phusion (NEB/Thermo)": {
        "ext_s_per_kb": 30, "denat": "98 C, 10 s", "init_denat": "98 C, 30 s",
        "anneal_rule": lambda lo: round(lo + 3),  # Phusion: lower Tm + 3
        "final_ext": "72 C, 5 min", "cycles": 30,
        "recipe": [("5X HF Buffer", "10 uL"), ("10 mM dNTPs", "1 uL"),
                   ("Forward primer (10 uM)", "2.5 uL"), ("Reverse primer (10 uM)", "2.5 uL"),
                   ("Phusion polymerase", "0.5 uL"), ("Template DNA", "1-10 ng (var.)"),
                   ("Nuclease-free water", "to 50 uL")],
    },
    "Taq (standard)": {
        "ext_s_per_kb": 60, "denat": "95 C, 30 s", "init_denat": "95 C, 30 s",
        "anneal_rule": lambda lo: round(lo - 5),  # Taq: lower Tm - 5
        "final_ext": "68 C, 5 min", "cycles": 30,
        "recipe": [("10X Standard Taq Buffer", "5 uL"), ("10 mM dNTPs", "1 uL"),
                   ("Forward primer (10 uM)", "1 uL"), ("Reverse primer (10 uM)", "1 uL"),
                   ("Taq polymerase", "0.25 uL"), ("Template DNA", "<1000 ng (var.)"),
                   ("Nuclease-free water", "to 50 uL")],
    },
    "OneTaq (NEB)": {
        "ext_s_per_kb": 60, "denat": "94 C, 30 s", "init_denat": "94 C, 30 s",
        "anneal_rule": lambda lo: round(lo - 5),
        "final_ext": "68 C, 5 min", "cycles": 30,
        "recipe": [("OneTaq 2X Master Mix", "25 uL"), ("Forward primer (10 uM)", "1 uL"),
                   ("Reverse primer (10 uM)", "1 uL"), ("Template DNA", "<1000 ng (var.)"),
                   ("Nuclease-free water", "to 50 uL")],
    },
}


def polymerases() -> List[str]:
    return list(_POLYMERASES.keys())


def _fmt_time(sec: int) -> str:
    sec = max(int(math.ceil(sec / 5.0)) * 5, 5)  # round up to nearest 5 s
    if sec >= 60:
        m, s = divmod(sec, 60)
        return f"{m} min {s} s" if s else f"{m} min"
    return f"{sec} s"


def design_pcr(fwd: str, rev: str, amplicon_bp: int, polymerase: str = "Q5 (NEB)",
               primer_uM: float = 0.5, na_mM: float = 50.0) -> Dict[str, Any]:
    p = _POLYMERASES.get(polymerase, _POLYMERASES["Q5 (NEB)"])
    tm_f = tm_nn(fwd, primer_uM, na_mM)
    tm_r = tm_nn(rev, primer_uM, na_mM)
    tms = [t for t in (tm_f, tm_r) if t is not None]
    if not tms:
        return {"error": "Enter valid forward and reverse primer sequences (A/C/G/T)."}
    lo = min(tms)
    anneal = p["anneal_rule"](lo)
    ext_s = (amplicon_bp / 1000.0) * p["ext_s_per_kb"]
    ext_time = _fmt_time(ext_s)

    cycling = [
        f"Initial denaturation: {p['init_denat']}",
        f"{p['cycles']} cycles of:",
        f"    Denature: {p['denat']}",
        f"    Anneal: {anneal} C, 20-30 s",
        f"    Extend: 72 C, {ext_time}",
        f"Final extension: {p['final_ext']}",
        "Hold: 4 C",
    ]
    return {
        "polymerase": polymerase,
        "tm_forward": tm_f, "tm_reverse": tm_r,
        "gc_forward": gc_percent(fwd), "gc_reverse": gc_percent(rev),
        "annealing_C": anneal,
        "extension_time": ext_time,
        "amplicon_bp": amplicon_bp,
        "reaction": [{"item": i, "amount": a} for i, a in p["recipe"]],
        "cycling": cycling,
        "note": ("Calculated from primer sequences and standard manufacturer guidance "
                 "for the selected polymerase. Verify against your enzyme datasheet."),
    }


def design_to_instructions(d: Dict[str, Any]) -> List[str]:
    """Render a design dict into bench instruction lines."""
    lines = [
        f"Set up the PCR ({d['polymerase']}) on ice. Reaction (50 uL): "
        + "; ".join(f"{r['item']} {r['amount']}" for r in d.get("reaction", [])) + ".",
        f"Primer Tm: F {d.get('tm_forward')} C, R {d.get('tm_reverse')} C → "
        f"anneal at {d.get('annealing_C')} C.",
        "Thermocycling: " + " | ".join(d.get("cycling", [])),
        f"(Extension {d.get('extension_time')} for a ~{d.get('amplicon_bp')} bp amplicon.)",
    ]
    return lines
