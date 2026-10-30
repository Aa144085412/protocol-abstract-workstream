"""
kit_lookup
==========
Local, zero-cost retrieval of verified commercial-kit protocols from
``memory/kit_library.json``. No model calls here — this is a static library so
loading a known kit (with exact volumes, spin speeds, and times) is free and
works offline / in DEMO mode.

Two ways to use a kit:
  * ``get_kit(kit_id)`` -> a full, schema-complete protocol with exact values
    (load it wholesale).
  * ``apply_kit(protocol, kit)`` -> fill ONLY the unconfirmed
    ``[confirm with source protocol]`` fields of an existing protocol using the
    kit's values, matching steps by title/keyword. Returns (new_protocol,
    list_of_changes). This is conservative: confirmed values are never
    overwritten.
"""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Dict, List, Tuple

CONFIRM = "[confirm with source protocol]"
_MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")
_LIBRARY_PATH = os.path.join(_MEMORY_DIR, "kit_library.json")
_KITS_DIR = os.path.join(_MEMORY_DIR, "kits")


def _looks_like_kit(obj: Any) -> bool:
    return isinstance(obj, dict) and ("kit_meta" in obj or "workflow" in obj)


def load_library() -> Dict[str, Any]:
    """Merge kits from memory/kit_library.json (a dict of kits) and every
    *.json file in memory/kits/ (each holds a single kit, or a dict of kits).
    Files whose names start with '_' are ignored. This lets new kits be added
    as drop-in files without editing existing ones."""
    library: Dict[str, Any] = {}

    if os.path.exists(_LIBRARY_PATH):
        try:
            with open(_LIBRARY_PATH, "r", encoding="utf-8") as fh:
                library.update(json.load(fh))
        except Exception:
            pass

    if os.path.isdir(_KITS_DIR):
        for fname in sorted(os.listdir(_KITS_DIR)):
            if not fname.endswith(".json") or fname.startswith("_"):
                continue
            path = os.path.join(_KITS_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            stem = os.path.splitext(fname)[0]
            if _looks_like_kit(data):
                library[stem] = data            # single-kit file
            elif isinstance(data, dict):
                library.update(data)            # dict-of-kits file
    return library


def list_kits() -> List[Dict[str, str]]:
    lib = load_library()
    out = []
    for kit_id, kit in lib.items():
        meta = kit.get("kit_meta", {})
        out.append({
            "id": kit_id,
            "title": meta.get("title", kit.get("protocol_title", kit_id)),
            "vendor": meta.get("vendor", ""),
            "assay_type": meta.get("assay_type", kit.get("assay_type", "")),
            "catalog_number": meta.get("catalog_number", ""),
            "provenance": meta.get("provenance", ""),
        })
    return out


def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def search_kits(query: str) -> List[Dict[str, str]]:
    """Rank library kits by keyword/title overlap with the query."""
    q = set(_tokens(query))
    lib = load_library()
    scored: List[Tuple[int, Dict[str, str]]] = []
    for kit_id, kit in lib.items():
        meta = kit.get("kit_meta", {})
        hay = set(_tokens(meta.get("title", "")) + _tokens(kit_id)
                  + [k.lower() for k in meta.get("keywords", [])]
                  + _tokens(meta.get("assay_type", "")))
        score = len(q & hay)
        # substring boost
        if query and query.lower() in (meta.get("title", "") + " " + kit_id).lower():
            score += 2
        if score:
            scored.append((score, {
                "id": kit_id,
                "title": meta.get("title", kit_id),
                "vendor": meta.get("vendor", ""),
                "assay_type": meta.get("assay_type", ""),
                "catalog_number": meta.get("catalog_number", ""),
                "provenance": meta.get("provenance", ""),
                "score": score,
            }))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored]


def get_kit(kit_id: str) -> Dict[str, Any]:
    """Return a deep copy of the full kit protocol (ready to load wholesale)."""
    lib = load_library()
    kit = copy.deepcopy(lib.get(kit_id, {}))
    return kit


def _needs_fill(value: Any) -> bool:
    return isinstance(value, str) and (CONFIRM in value or value.strip() == "")


# generic words that must NOT, on their own, make two steps/materials "match"
_GENERIC = {
    "add", "mix", "the", "to", "and", "of", "in", "a", "an", "with", "prepare",
    "step", "for", "on", "by", "your", "into", "from", "buffer", "dna", "rna",
    "sample", "solution", "tube", "at", "room", "temp", "reagent", "complex",
    "kit", "protocol", "spin", "column", "transfer", "incubate", "centrifuge",
}


def _match_strength(a_title: str, b_title: str) -> float:
    """Overlap coefficient between two titles, but only counting DISTINCTIVE
    (non-generic, length>=4) shared tokens. Returns 0 if the only overlap is
    generic words like 'add'/'dna'/'buffer'. 1.0 = strong match."""
    A, B = set(_tokens(a_title)), set(_tokens(b_title))
    if not A or not B:
        return 0.0
    inter = A & B
    distinctive = {t for t in inter if len(t) >= 4 and t not in _GENERIC}
    if not distinctive:
        return 0.0
    # coefficient relative to the smaller distinctive-eligible token set
    base = min(len({t for t in A if len(t) >= 4 and t not in _GENERIC}) or 1,
               len({t for t in B if len(t) >= 4 and t not in _GENERIC}) or 1)
    return len(distinctive) / base


def _best_step_match(target_step: Dict[str, Any], kit_steps: List[Dict[str, Any]],
                     threshold: float = 0.5):
    """Match a protocol step to a kit step ONLY when titles share distinctive
    tokens strongly enough — so unrelated steps (e.g. a transfection-complex step
    vs a 'DNA Binding Buffer' step) are never matched on a single generic word."""
    best, best_s = None, 0.0
    for ks in kit_steps:
        s = _match_strength(target_step.get("title", ""), ks.get("title", ""))
        if s >= threshold and s > best_s:
            best, best_s = ks, s
    return best


def apply_kit(protocol: Dict[str, Any], kit: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Fill ONLY unconfirmed fields of ``protocol`` from ``kit``. Non-destructive."""
    new = copy.deepcopy(protocol)
    changes: List[str] = []
    meta = kit.get("kit_meta", {})
    kit_name = meta.get("title", "kit")

    # --- materials: match by item-name token overlap ---
    kit_mats = kit.get("materials", [])
    for m in new.get("materials", []):
        km = _match_material(m.get("item", ""), kit_mats)
        if not km:
            continue
        for field in ("amount", "vendor", "catalog_number", "notes"):
            if _needs_fill(m.get(field)) and km.get(field) and not _needs_fill(km.get(field)):
                m[field] = km[field]
                changes.append(f"material '{m.get('item','')}' {field} <- {km[field]}")

    # --- workflow: match steps by title, fill conditions/time/reagents ---
    kit_steps = kit.get("workflow", [])
    for step in new.get("workflow", []):
        ks = _best_step_match(step, kit_steps)
        if not ks:
            continue
        if _needs_fill(step.get("time_estimate")) and ks.get("time_estimate"):
            step["time_estimate"] = ks["time_estimate"]
            changes.append(f"{step['step_id']} time <- {ks['time_estimate']}")
        sc = step.setdefault("conditions", {})
        kc = ks.get("conditions", {})
        for field in ("temperature", "speed", "other"):
            if _needs_fill(sc.get(field)) and kc.get(field) and not _needs_fill(kc.get(field)):
                sc[field] = kc[field]
                changes.append(f"{step['step_id']} {field} <- {kc[field]}")
        # bring over per-step reagents ONLY on a strong title match, and only if
        # each reagent's name is plausibly relevant to this step (avoids injecting
        # e.g. 'DNA Binding Buffer' into a transfection step).
        strong = _match_strength(step.get("title", ""), ks.get("title", "")) >= 0.75
        if strong and not step.get("reagents") and ks.get("reagents"):
            step_text = (step.get("title", "") + " " + " ".join(step.get("instructions", []) or [])).lower()
            relevant = [r for r in ks["reagents"]
                        if any(tok in step_text for tok in _tokens(r.get("item", ""))
                               if len(tok) >= 4 and tok not in _GENERIC)]
            if relevant:
                step["reagents"] = copy.deepcopy(relevant)
                changes.append(f"{step['step_id']} reagents <- {len(relevant)} item(s)")

    if changes:
        new.setdefault("revision_log", []).append({
            "version": new.get("protocol_version", "v1"),
            "reason": f"Filled unconfirmed values from kit library: {kit_name}",
            "changed_step_ids": sorted({c.split()[0] for c in changes if c.startswith('step_')}),
        })
        new["kit_source"] = {"title": kit_name, "provenance": meta.get("provenance", "")}
    return new, changes


def _match_material(item: str, kit_mats: List[Dict[str, Any]]):
    best, best_score = None, 0.0
    for km in kit_mats:
        score = _match_strength(item, km.get("item", ""))
        if score >= 0.5 and score > best_score:
            best, best_score = km, score
    return best if best_score > 0 else None


def _remap_text(text: str, idmap: Dict[str, str]) -> str:
    if not isinstance(text, str):
        return text
    for old, new in idmap.items():
        text = text.replace(old, new)
    return text


def combine_protocols(protocols: List[Dict[str, Any]], title: str = "") -> Dict[str, Any]:
    """Combine several protocols into ONE sequential bench protocol.

    Steps are concatenated and globally renumbered (step_01..step_NN). Each step
    gets a ``stage`` label = its source protocol title. Materials, QC checkpoints,
    decision points and failure branches are merged; step-id references inside
    QC ``when`` text and failure ``step_ids_affected`` are remapped to the new
    numbering. This models a real multi-stage bench day (e.g. miniprep ->
    gel recovery -> clean & concentrate).
    """
    titles = [p.get("protocol_title", f"Stage {i+1}") for i, p in enumerate(protocols)]
    combined: Dict[str, Any] = {
        "agent": "Protocol Agent",
        "status": "success",
        "protocol_title": title or "Combined: " + " + ".join(titles),
        "protocol_version": "v1",
        "assay_type": "Multi-stage workflow",
        "objective": "Run multiple protocols back-to-back as one guided bench session.",
        "intended_user": "mixed",
        "summary": "Combined sequential protocol built from: " + "; ".join(titles)
        + ". Stages run in order; each step shows its source stage. Confirm all "
        "values carried over from the source protocols.",
        "preconditions": {
            "sample_requirements": [], "reagent_requirements": [],
            "equipment_requirements": [], "safety_notes": [],
            "lab_specific_fields_to_confirm": [],
        },
        "materials": [], "workflow": [], "qc_checkpoints": [], "decision_points": [],
        "failure_branches": [], "artifact_outputs": [],
        "revision_log": [{"version": "v1",
                          "reason": "combined from: " + ", ".join(titles),
                          "changed_step_ids": []}],
        "open_questions_for_human": [], "confidence": "medium",
        "stages": titles, "timestamp": "",
    }

    confidences = []
    counter = 0
    for stage_idx, p in enumerate(protocols, start=1):
        stage_name = p.get("protocol_title", f"Stage {stage_idx}")
        confidences.append(p.get("confidence", "medium"))
        idmap: Dict[str, str] = {}

        for s in p.get("workflow", []) or []:
            counter += 1
            ns = copy.deepcopy(s)
            old_id = ns.get("step_id", f"step_{counter}")
            new_id = f"step_{counter:02d}"
            idmap[old_id] = new_id
            ns["step_id"] = new_id
            ns["step_number"] = counter
            ns["stage"] = stage_name
            combined["workflow"].append(ns)

        for q in p.get("qc_checkpoints", []) or []:
            q2 = copy.deepcopy(q)
            q2["when"] = _remap_text(q2.get("when", ""), idmap)
            q2["stage"] = stage_name
            combined["qc_checkpoints"].append(q2)

        for d in p.get("decision_points", []) or []:
            d2 = copy.deepcopy(d)
            d2["when"] = _remap_text(d2.get("when", ""), idmap)
            d2["stage"] = stage_name
            combined["decision_points"].append(d2)

        for b in p.get("failure_branches", []) or []:
            b2 = copy.deepcopy(b)
            b2["step_ids_affected"] = [idmap.get(x, x) for x in b.get("step_ids_affected", [])]
            b2["stage"] = stage_name
            combined["failure_branches"].append(b2)

        for m in p.get("materials", []) or []:
            m2 = copy.deepcopy(m)
            note = (m2.get("notes", "") + f" [stage: {stage_name}]").strip()
            m2["notes"] = note
            combined["materials"].append(m2)

        pre = p.get("preconditions", {}) or {}
        for key in ("sample_requirements", "reagent_requirements",
                    "equipment_requirements", "safety_notes",
                    "lab_specific_fields_to_confirm"):
            for v in pre.get(key, []) or []:
                tagged = f"[{stage_name}] {v}" if key in ("sample_requirements",) else v
                if tagged not in combined["preconditions"][key]:
                    combined["preconditions"][key].append(tagged)

        for v in p.get("open_questions_for_human", []) or []:
            combined["open_questions_for_human"].append(f"[{stage_name}] {v}")

    if "low" in confidences:
        combined["confidence"] = "low"
    elif all(c == "high" for c in confidences) and confidences:
        combined["confidence"] = "high"
    return combined


# branded kits whose exact values depend on a format the user must pick
_AMBIGUOUS_KITS = [
    {"match": ["zymopure"], "key": "zymopure_format",
     "question": "ZymoPURE format", "options": ["spin-column", "vacuum"]},
    {"match": ["plasmid plus", "qiaprep plus", "qiagen plus"], "key": "qiagen_format",
     "question": "QIAGEN format", "options": ["spin (microcentrifuge)", "vacuum"]},
]
# generic fallback for unbranded large preps (only if no branded match)
_GENERIC_PREP = {"match": ["maxiprep", "midiprep", "gigaprep"], "key": "prep_format",
                 "question": "Prep format", "options": ["spin-column", "vacuum/gravity"]}


def detect_format_questions(protocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect multi-format/version kits in the protocol that need a user choice
    before exact values can be filled. Returns [{key, question, options}]."""
    text = " ".join([
        protocol.get("protocol_title", ""), protocol.get("assay_type", ""),
        " ".join(m.get("item", "") for m in protocol.get("materials", []) or []),
        (protocol.get("kit_source", {}) or {}).get("title", ""),
        (protocol.get("kit_source", {}) or {}).get("provenance", ""),
        " ".join(s.get("title", "") for s in protocol.get("workflow", []) or []),
    ]).lower()
    out = []
    for rule in _AMBIGUOUS_KITS:
        if any(m in text for m in rule["match"]):
            out.append({k: rule[k] for k in ("key", "question", "options")})
    if out:
        return out  # a branded kit already covers the format question
    prov = (protocol.get("kit_source", {}) or {}).get("provenance", "").lower()
    if any(m in text for m in _GENERIC_PREP["match"]) or ("spin" in prov and "vacuum" in prov):
        out.append({k: _GENERIC_PREP[k] for k in ("key", "question", "options")})
    return out


def count_confirm(obj: Any) -> int:
    if isinstance(obj, str):
        return 1 if CONFIRM in obj else 0
    if isinstance(obj, dict):
        return sum(count_confirm(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(count_confirm(v) for v in obj)
    return 0
