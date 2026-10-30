"""
fill_slots
==========
Helpers to enumerate, read, and write the *unconfirmed* quantitative fields of a
protocol ("slots"), and to propose grounded values from the kit library. Used by
the AI-assisted Fill flow. No model calls here.

Slot id scheme:
  mat:{i}:amount                       -> materials[i]["amount"]
  step:{step_id}:time                  -> workflow step time_estimate
  step:{step_id}:cond:{field}          -> workflow step conditions[field]
  step:{step_id}:reag:{ri}:amount      -> workflow step reagents[ri]["amount"]

Only safe-to-suggest fields are exposed (amounts, times, temperatures, speeds).
Catalog numbers and vendors are NEVER exposed here — those must not be invented.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

CONFIRM = "[confirm with source protocol]"

# common life-science vendors, for extracting vendor names from a source document
_VENDORS = [
    "Addgene", "New England Biolabs", "NEB", "Sigma-Aldrich", "Sigma",
    "Thermo Fisher", "ThermoFisher", "Thermo Scientific", "Thermo", "Invitrogen",
    "Gibco", "QIAGEN", "Qiagen", "Zymo Research", "Zymo", "Promega", "Takara",
    "Clontech", "Bio-Rad", "BioRad", "Millipore", "MilliporeSigma", "Miltenyi",
    "Corning", "Lonza", "Abcam", "Cell Signaling", "Santa Cruz", "IDT",
    "Integrated DNA Technologies", "GeneWiz", "Azenta", "ATCC", "Roche",
    "BD Biosciences", "Beckman", "Agilent", "Macherey-Nagel", "Worthington",
]


# generic words that must NOT be used to locate a material in the source text
_ITEM_GENERIC = {
    "lentivirus", "lentiviral", "plasmid", "vector", "dna", "rna", "medium",
    "media", "growth", "serum", "bovine", "fetal", "buffer", "kit", "cells",
    "cell", "water", "reagent", "mix", "stock", "solution", "the", "and", "for",
    "with", "gene", "genes", "protein", "marker",
}


def _distinctive_tokens(item: str) -> List[str]:
    toks = re.split(r"[^A-Za-z0-9.]+", item)
    out = []
    for t in toks:
        low = t.lower()
        if (len(t) >= 4 and low not in _ITEM_GENERIC) or (any(c.isdigit() for c in t) and len(t) >= 3):
            out.append(t)
    # prefer tokens with digits, then longer — these are the most specific
    out.sort(key=lambda x: (any(c.isdigit() for c in x), len(x)), reverse=True)
    return out


def scan_vendors(raw_text: str, materials: List[Dict[str, Any]]) -> Dict[str, str]:
    """Extract vendor names for materials by finding a DISTINCTIVE item name in
    the uploaded source text and looking for a known vendor nearby. Never invents
    — only returns a vendor that actually appears next to that specific item in
    the document. Returns {"mat:{i}:vendor": vendor}."""
    out: Dict[str, str] = {}
    if not raw_text:
        return out
    low = raw_text.lower()
    for i, m in enumerate(materials or []):
        for tok in _distinctive_tokens(m.get("item", "")):
            p = low.find(tok.lower())
            if p == -1:
                continue
            window = raw_text[p:p + 160]  # look just AFTER the item name
            for v in _VENDORS:
                if v.lower() in window.lower():
                    out[f"mat:{i}:vendor"] = v
                    break
            if f"mat:{i}:vendor" in out:
                break
    return out


def _is_confirm(v: Any) -> bool:
    return not str(v or "").strip() or CONFIRM in str(v)


def _shorten(s: str, n: int = 70) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "…"


def list_slots(proto: Dict[str, Any]) -> List[Dict[str, str]]:
    slots: List[Dict[str, str]] = []
    for i, m in enumerate(proto.get("materials", []) or []):
        if _is_confirm(m.get("amount")):
            slots.append({
                "id": f"mat:{i}:amount",
                "label": f"Material — {m.get('item','?')} (amount)",
                "context": str(m.get("notes", "")),
            })
        if _is_confirm(m.get("vendor")):
            slots.append({
                "id": f"mat:{i}:vendor",
                "label": f"Material — {m.get('item','?')} (vendor)",
                "context": str(m.get("notes", "")),
            })
    for s in proto.get("workflow", []) or []:
        sid = s.get("step_id")
        n = s.get("step_number", "?")
        title = s.get("title", "")
        instr_all = " ".join(s.get("instructions", []) or [])[:300]
        if _is_confirm(s.get("time_estimate")):
            slots.append({"id": f"step:{sid}:time",
                          "label": f"Step {n} ({title}) — time",
                          "context": instr_all})
        cond = s.get("conditions", {}) or {}
        for field in ("temperature", "speed", "other"):
            if _is_confirm(cond.get(field)) and cond.get(field):
                slots.append({"id": f"step:{sid}:cond:{field}",
                              "label": f"Step {n} ({title}) — {field}",
                              "context": instr_all})
        for ri, r in enumerate(s.get("reagents", []) or []):
            if _is_confirm(r.get("amount")):
                slots.append({"id": f"step:{sid}:reag:{ri}:amount",
                              "label": f"Step {n} ({title}) — {r.get('item','reagent')} amount",
                              "context": instr_all})
        # values embedded inside instruction text, e.g. "incubate for [confirm…]"
        for idx, line in enumerate(s.get("instructions", []) or []):
            occ = str(line).count(CONFIRM)
            for k in range(occ):
                slots.append({
                    "id": f"step:{sid}:instr:{idx}:{k}",
                    "label": f"Step {n} ({title}) — value in: \"{_shorten(line)}\"",
                    "context": str(line),
                })
    return slots


def _replace_nth(text: str, old: str, new: str, n: int) -> str:
    idx = -1
    for _ in range(n + 1):
        idx = text.find(old, idx + 1)
        if idx == -1:
            return text
    return text[:idx] + new + text[idx + len(old):]


def read_slot(proto: Dict[str, Any], slot_id: str) -> Optional[str]:
    p = slot_id.split(":")
    try:
        if p[0] == "mat":
            return proto["materials"][int(p[1])].get(p[2])
        if p[0] == "step":
            step = next(s for s in proto.get("workflow", []) if s.get("step_id") == p[1])
            if p[2] == "time":
                return step.get("time_estimate")
            if p[2] == "cond":
                return step.get("conditions", {}).get(p[3])
            if p[2] == "reag":
                return step.get("reagents", [])[int(p[3])].get("amount")
            if p[2] == "instr":
                return CONFIRM  # the embedded token is, by definition, unconfirmed
    except Exception:
        return None
    return None


def write_slot(proto: Dict[str, Any], slot_id: str, value: str) -> bool:
    p = slot_id.split(":")
    try:
        if p[0] == "mat":
            proto["materials"][int(p[1])][p[2]] = value
            return True
        if p[0] == "step":
            step = next(s for s in proto.get("workflow", []) if s.get("step_id") == p[1])
            if p[2] == "time":
                step["time_estimate"] = value
            elif p[2] == "cond":
                step.setdefault("conditions", {})[p[3]] = value
            elif p[2] == "reag":
                step.setdefault("reagents", [])[int(p[3])]["amount"] = value
            elif p[2] == "instr":
                idx, k = int(p[3]), int(p[4])
                line = step["instructions"][idx]
                step["instructions"][idx] = _replace_nth(line, CONFIRM, value, k)
            return True
    except Exception:
        return False
    return False


def apply_values(proto: Dict[str, Any], values: Dict[str, str]) -> int:
    """Write multiple slot values safely. Instruction-token slots on the same
    line are applied highest-occurrence-first so earlier indices stay valid."""
    def _key(sid: str):
        p = sid.split(":")
        if len(p) == 5 and p[2] == "instr":
            return (p[1], int(p[3]), -int(p[4]))  # same line: higher k first
        return (p[0], 0, 0)
    cnt = 0
    for sid in sorted(values, key=_key):
        v = values[sid]
        if v and write_slot(proto, sid, v):
            cnt += 1
    return cnt


def kit_suggestions(proto: Dict[str, Any], slots: List[Dict[str, str]],
                    max_kits: int = 3) -> Dict[str, str]:
    """Grounded fallback: fill a clone from the best-matching library kits and
    report the values that landed in each slot. Used in DEMO mode."""
    from .kit_lookup import search_kits, get_kit, apply_kit

    query = (proto.get("protocol_title", "") + " " + proto.get("assay_type", "")).strip()
    hits = search_kits(query)[:max_kits] if query else []
    if not hits:
        return {}
    clone = copy.deepcopy(proto)
    for h in hits:
        clone, _ = apply_kit(clone, get_kit(h["id"]))
    out: Dict[str, str] = {}
    for slot in slots:
        v = read_slot(clone, slot["id"])
        if v and not _is_confirm(v):
            out[slot["id"]] = v
    return out
