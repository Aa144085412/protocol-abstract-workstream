"""
step_ops
========
Merge/consolidate consecutive workflow steps into one. Pure-local (no model).

merge_steps(protocol, step_ids) combines a CONSECUTIVE block of steps into a
single step (concatenating instructions/reagents, merging conditions, combining
times, unioning flags), then renumbers the whole workflow and remaps step-id
references in QC checkpoints, decision points, and failure branches.

suggest_merges(protocol) proposes runs of consecutive "trivial" steps (single
action, same stage, no pause point or human-review flag) that are safe to merge.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

CONFIRM = "[confirm with source protocol]"


def _remap_text(text: str, idmap: Dict[str, str]) -> str:
    if not isinstance(text, str):
        return text
    # replace longer ids first to avoid partial clobbering (step_1 vs step_10)
    for old in sorted(idmap, key=len, reverse=True):
        text = text.replace(old, idmap[old])
    return text


def _parse_min(t: str):
    s = str(t or "").lower()
    if not s.strip() or CONFIRM in s or "overnight" in s:
        return None
    nums = [float(x) for x in re.findall(r"\d+\.?\d*", s)]
    if not nums:
        return None
    v = max(nums)
    if "h" in s or "hr" in s or "hour" in s:
        v *= 60
    return v


def _combine_times(times: List[str]) -> str:
    vals = [_parse_min(t) for t in times]
    if all(v is not None for v in vals) and vals:
        total = int(round(sum(vals)))
        if total >= 60:
            h, m = divmod(total, 60)
            return f"~{h} h {m} min" if m else f"~{h} h"
        return f"~{total} min"
    # otherwise join distinct, non-empty, non-confirm
    seen, out = set(), []
    for t in times:
        t = str(t or "").strip()
        if t and CONFIRM not in t and t not in seen:
            seen.add(t); out.append(t)
    return " + ".join(out) if out else ""


def _combine_conditions(block: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}
    for field in ("temperature", "speed", "other"):
        seen, vals = set(), []
        for s in block:
            v = str((s.get("conditions", {}) or {}).get(field, "") or "").strip()
            if v and CONFIRM not in v and v not in seen:
                seen.add(v); vals.append(v)
        out[field] = " / ".join(vals)
    return out


def _dedup(items, key):
    seen, out = set(), []
    for it in items:
        k = key(it)
        if k not in seen:
            seen.add(k); out.append(it)
    return out


def _merge_block(block: List[Dict[str, Any]]) -> Dict[str, Any]:
    titles = [s.get("title", "") for s in block]
    uniq_titles = list(dict.fromkeys(t for t in titles if t))
    return {
        "_old_ids": [s.get("step_id") for s in block],
        "title": " + ".join(uniq_titles) if len(uniq_titles) > 1 else (uniq_titles[0] if uniq_titles else "Merged step"),
        "purpose": "; ".join(dict.fromkeys(s.get("purpose", "") for s in block if s.get("purpose"))),
        "stage": block[0].get("stage", ""),
        "instructions": [i for s in block for i in (s.get("instructions") or [])],
        "reagents": _dedup([r for s in block for r in (s.get("reagents") or [])],
                           key=lambda r: (r.get("item", ""), r.get("amount", ""))),
        "time_estimate": _combine_times([s.get("time_estimate", "") for s in block]),
        "conditions": _combine_conditions(block),
        "expected_observation": " ".join(s.get("expected_observation", "") for s in block if s.get("expected_observation")).strip(),
        "checkpoint": next((s.get("checkpoint") for s in reversed(block) if s.get("checkpoint")), ""),
        "pause_point": any(s.get("pause_point") for s in block),
        "human_review_required": list(dict.fromkeys(h for s in block for h in (s.get("human_review_required") or []))),
        "troubleshooting": [t for s in block for t in (s.get("troubleshooting") or [])],
        "notes": [n for s in block for n in (s.get("notes") or [])] + [f"[Merged from {len(block)} steps]"],
    }


def merge_steps(protocol: Dict[str, Any], step_ids: List[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (new_protocol, error). Steps must be consecutive."""
    new = copy.deepcopy(protocol)
    wf = new.get("workflow", []) or []
    sel = sorted(i for i, s in enumerate(wf) if s.get("step_id") in set(step_ids))
    if len(sel) < 2:
        return protocol, "Select at least 2 steps to merge."
    if sel != list(range(sel[0], sel[-1] + 1)):
        return protocol, "Steps must be consecutive (no gaps)."

    block = wf[sel[0]:sel[-1] + 1]
    merged = _merge_block(block)
    rebuilt = wf[:sel[0]] + [merged] + wf[sel[-1] + 1:]

    # renumber + build old_id -> new_id map (block ids all map to the merged step)
    idmap: Dict[str, str] = {}
    for n, s in enumerate(rebuilt, 1):
        nid = f"step_{n:02d}"
        for oid in s.pop("_old_ids", [s.get("step_id")]):
            if oid:
                idmap[oid] = nid
        s["step_id"] = nid
        s["step_number"] = n
    new["workflow"] = rebuilt

    for q in new.get("qc_checkpoints", []) or []:
        q["when"] = _remap_text(q.get("when", ""), idmap)
    for d in new.get("decision_points", []) or []:
        d["when"] = _remap_text(d.get("when", ""), idmap)
    for b in new.get("failure_branches", []) or []:
        b["step_ids_affected"] = list(dict.fromkeys(idmap.get(x, x) for x in b.get("step_ids_affected", [])))
    return new, None


def _renumber(protocol: Dict[str, Any], idmap_extra: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Renumber workflow step_ids/numbers and remap references everywhere."""
    wf = protocol.get("workflow", []) or []
    idmap: Dict[str, str] = dict(idmap_extra or {})
    for n, s in enumerate(wf, 1):
        old = s.get("step_id")
        nid = f"step_{n:02d}"
        if old:
            idmap[old] = nid
        s["step_id"] = nid
        s["step_number"] = n
    for q in protocol.get("qc_checkpoints", []) or []:
        q["when"] = _remap_text(q.get("when", ""), idmap)
    for d in protocol.get("decision_points", []) or []:
        d["when"] = _remap_text(d.get("when", ""), idmap)
    for b in protocol.get("failure_branches", []) or []:
        b["step_ids_affected"] = list(dict.fromkeys(idmap.get(x, x) for x in b.get("step_ids_affected", [])))
    return protocol


def split_step(protocol: Dict[str, Any], step_id: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Split a step into one sub-step per instruction line. Needs >=2 instructions."""
    new = copy.deepcopy(protocol)
    wf = new.get("workflow", []) or []
    idx = next((i for i, s in enumerate(wf) if s.get("step_id") == step_id), None)
    if idx is None:
        return protocol, "Step not found."
    src = wf[idx]
    instrs = src.get("instructions", []) or []
    if len(instrs) < 2:
        return protocol, "Step has fewer than 2 instructions to split."
    parts = []
    for j, line in enumerate(instrs):
        sub = copy.deepcopy(src)
        sub["instructions"] = [line]
        sub["title"] = f"{src.get('title','Step')} ({j + 1}/{len(instrs)})"
        # only the last sub-step keeps the checkpoint / pause / expected-observation
        if j != len(instrs) - 1:
            sub["checkpoint"] = ""
            sub["pause_point"] = False
            sub["expected_observation"] = ""
        # reagents/conditions stay on the first sub-step to avoid duplication
        if j != 0:
            sub["reagents"] = []
        parts.append(sub)
    new["workflow"] = wf[:idx] + parts + wf[idx + 1:]
    _renumber(new)
    return new, None


def move_step(protocol: Dict[str, Any], step_id: str, direction: int) -> Tuple[Dict[str, Any], Optional[str]]:
    """Move a step up (direction=-1) or down (+1) by one position."""
    new = copy.deepcopy(protocol)
    wf = new.get("workflow", []) or []
    idx = next((i for i, s in enumerate(wf) if s.get("step_id") == step_id), None)
    if idx is None:
        return protocol, "Step not found."
    j = idx + direction
    if j < 0 or j >= len(wf):
        return protocol, "Already at the edge."
    wf[idx], wf[j] = wf[j], wf[idx]
    _renumber(new)
    return new, None


def delete_step(protocol: Dict[str, Any], step_id: str) -> Tuple[Dict[str, Any], Optional[str]]:
    new = copy.deepcopy(protocol)
    wf = new.get("workflow", []) or []
    if not any(s.get("step_id") == step_id for s in wf):
        return protocol, "Step not found."
    if len(wf) <= 1:
        return protocol, "Cannot delete the only step."
    new["workflow"] = [s for s in wf if s.get("step_id") != step_id]
    _renumber(new)
    return new, None


def move_to_preconditions(protocol: Dict[str, Any], step_id: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Remove a step from the workflow and record it as a precondition / gate
    (e.g. 'BSL-2 training' belongs before bench work, not as a numbered step)."""
    new = copy.deepcopy(protocol)
    wf = new.get("workflow", []) or []
    src = next((s for s in wf if s.get("step_id") == step_id), None)
    if src is None:
        return protocol, "Step not found."
    if len(wf) <= 1:
        return protocol, "Cannot move the only step."
    text = src.get("title", "Prerequisite")
    detail = "; ".join(src.get("instructions", []) or [])
    entry = f"{text}" + (f" — {detail}" if detail else "")
    pre = new.setdefault("preconditions", {})
    pre.setdefault("lab_specific_fields_to_confirm", [])
    # store as a sample-requirement-style prerequisite line
    pre.setdefault("sample_requirements", [])
    pre["sample_requirements"].append(f"[Prerequisite] {entry}")
    new["workflow"] = [s for s in wf if s.get("step_id") != step_id]
    _renumber(new)
    return new, None


def suggest_merges(protocol: Dict[str, Any]) -> List[List[str]]:
    """Runs of >=2 consecutive 'trivial' same-stage steps that are safe to merge."""
    wf = protocol.get("workflow", []) or []

    def trivial(s):
        return (len(s.get("instructions") or []) <= 1
                and not s.get("pause_point")
                and not (s.get("human_review_required") or []))

    runs, run = [], []
    for s in wf:
        if run and trivial(s) and s.get("stage", "") == run[-1].get("stage", "") \
                and not run[-1].get("pause_point"):
            run.append(s)
        else:
            if len(run) >= 2:
                runs.append(run)
            run = [s] if trivial(s) else []
    if len(run) >= 2:
        runs.append(run)
    return [[s.get("step_id") for s in r] for r in runs]
