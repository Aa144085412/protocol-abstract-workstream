"""
assay_gaps
==========
Context-aware "clarify to design" detector. Scans a protocol for the assay types it
contains (restriction digest, PCR, ligation, cell culture/transduction, CUT&Tag, …)
and, for each, lists the standardization parameters that assay needs — flagging which
ones already appear in the protocol text and which are still gaps the user should
clarify so the experiment can be fully designed.

Deterministic and advisory: it never writes values, it only surfaces what's missing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# assay -> (detection keywords, standardization parameters with a presence regex each)
ASSAY_SPECS: Dict[str, Dict[str, Any]] = {
    "Restriction digest": {
        "keywords": ["restriction", "digest", "endonuclease", "neb cutsmart", "cutsmart"],
        "params": {
            "enzyme units (U/µg)": r"\bU\s*/\s*[µu]?g\b|\bunits?\b",
            "reaction volume": r"\b\d+(\.\d+)?\s*[µu]?l\b|\breaction\s+volume\b",
            "incubation temperature": r"\b\d{2}\s*°?\s*c\b|\b37\b",
            "incubation time": r"\b\d+\s*(min|h|hr|hour)\b|overnight",
        },
    },
    "PCR / amplification": {
        "keywords": ["pcr", "amplif", "polymerase", "thermocycl", "anneal", "kapa", "q5", "phusion"],
        "params": {
            "reaction volume": r"\b\d+(\.\d+)?\s*[µu]?l\b|\b25\s*[µu]l\b|\b50\s*[µu]l\b",
            "primer concentration": r"\b\d+(\.\d+)?\s*[µu]?m\b|\bprimer.{0,12}conc",
            "annealing temperature": r"anneal|\b5[0-9]\s*°?\s*c\b|\b6[0-9]\s*°?\s*c\b",
            "extension time": r"extension|\b\d+\s*(s|sec|min)\b",
            "cycle number": r"\b\d{1,2}\s*cycles?\b|\bx\s*\d{1,2}\b",
        },
    },
    "Ligation / assembly": {
        "keywords": ["ligat", "ligase", "gibson", "golden gate", "assembly", "insert:vector"],
        "params": {
            "insert:vector ratio": r"\d+\s*:\s*\d+|insert.{0,6}vector",
            "reaction volume": r"\b\d+(\.\d+)?\s*[µu]?l\b",
            "incubation temperature": r"\b\d{2}\s*°?\s*c\b|room temp|\brt\b|\b16\b",
            "incubation time": r"\b\d+\s*(min|h|hr|hour)\b|overnight",
        },
    },
    "Cell culture / transduction": {
        "keywords": ["cells", "plate", "media", "transduc", "seed", "culture", "flask", "well",
                     "lentivir", "moi"],
        "params": {
            "vessel / culture format": r"\b(t25|t75|t175|6-?well|12-?well|24-?well|96-?well|10\s*cm|15\s*cm|dish|flask)\b",
            "seeding density": r"\b\d[\d,.]*\s*(cells|x\s*10)\b|density",
            "media volume": r"\b\d+(\.\d+)?\s*(ml|[µu]l)\b",
            "MOI": r"\bmoi\b|multiplicity",
        },
    },
    "CUT&Tag / chromatin": {
        "keywords": ["cut&tag", "cut and tag", "tagment", "pag-tn5", "pa-tn5", "chromatin",
                     "antibody", "h3k", "concanavalin"],
        "params": {
            "antibody dilution": r"\b1\s*:\s*\d+\b|dilution",
            "pAG-Tn5 amount": r"tn5|\b\d+(\.\d+)?\s*[µu]?l\b",
            "tagmentation temperature": r"\b37\s*°?\s*c\b|\b\d{2}\s*°?\s*c\b",
            "tagmentation time": r"\b\d+\s*(min|h|hr|hour)\b|overnight",
        },
    },
}


def _protocol_text(proto: Dict[str, Any]) -> str:
    parts: List[str] = [str(proto.get("protocol_title", ""))]
    for s in proto.get("workflow", []) or []:
        parts.append(str(s.get("title", "")))
        parts.extend(str(i) for i in s.get("instructions", []) or [])
        cond = s.get("conditions", {}) or {}
        parts.extend(str(v) for v in cond.values())
        for r in s.get("reagents", []) or []:
            parts.append(str(r.get("item", "")))
            parts.append(str(r.get("amount", "")))
    return " ".join(parts).lower()


def detect(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return [{assay, present:[param], gaps:[param]}] for every assay found in the
    protocol. An assay is 'found' if any of its keywords appear. A parameter is
    'present' if its regex matches the protocol text, else it's a gap to clarify."""
    text = _protocol_text(proto)
    out: List[Dict[str, Any]] = []
    for assay, spec in ASSAY_SPECS.items():
        if not any(k in text for k in spec["keywords"]):
            continue
        present, gaps = [], []
        for param, rx in spec["params"].items():
            (present if re.search(rx, text, re.I) else gaps).append(param)
        out.append({"assay": assay, "present": present, "gaps": gaps})
    return out


def total_gaps(proto: Dict[str, Any]) -> int:
    return sum(len(a["gaps"]) for a in detect(proto))
