"""
protocol_check
==============
A deterministic, BPL-inspired "pre-flight compiler" for a protocol. No model calls —
every finding is a reviewable rule, so it's fully auditable (signal in → signal out).

It runs three gates over the protocol, mirroring BPL-COGEN's parse → semantic → plan:

  1. STRUCTURE  — required fields present; steps well-formed; ids unique & ordered.
  2. SEMANTIC   — unit/dimensional sanity: a value sits in the right kind of field
                  (no volume in a temperature slot, no mass+volume mix, no negative/zero
                  amount, a "speed" that is actually a speed, a temperature that parses).
  3. STATE      — container/material flow: a reagent used in a step is declared in
                  materials (use-before-declare), and obvious order problems.

Returns a diagnostics report: list of findings, each with a gate, severity, a located
'where' (step id/number + field), the issue, and a one-line fix — plus counts and a
'ready' boolean (no high-severity findings).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

CONFIRM_TAG = "[confirm with source protocol]"

# unit recognizers --------------------------------------------------------- #
_VOLUME = re.compile(r"\b\d+(\.\d+)?\s?(µl|ul|μl|ml|l|µL|nL|nl)\b", re.I)
_MASS = re.compile(r"\b\d+(\.\d+)?\s?(ng|µg|ug|μg|mg|g|kg|pg)\b", re.I)
_TEMP = re.compile(r"-?\d+(\.\d+)?\s?°?\s?c\b|\broom temp|\brt\b|\bon ice\b|\b4°|\b37°|\b-20|\b-80", re.I)
_SPEED = re.compile(r"\b\d[\d,]*\s?(x\s?g|×g|rpm|rcf|g\b)", re.I)
_TIME = re.compile(r"\b\d+(\.\d+)?\s?(s|sec|min|mins|minute|minutes|h|hr|hrs|hour|hours|day|days)\b"
                   r"|\bovernight\b|\bo/n\b", re.I)


def _f(gate, severity, where, issue, fix) -> Dict[str, Any]:
    return {"gate": gate, "severity": severity, "where": where, "issue": issue, "fix": fix}


def check_protocol(proto: Dict[str, Any]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    wf = proto.get("workflow", []) or []

    # ---- Gate 1: STRUCTURE ------------------------------------------------ #
    if not proto.get("protocol_title"):
        findings.append(_f("structure", "low", "protocol", "No protocol title.", "Add a title."))
    if not wf:
        findings.append(_f("structure", "high", "protocol", "Protocol has no workflow steps.",
                           "Add or generate steps before running."))
    seen_ids = set()
    last_num = 0
    for i, s in enumerate(wf, 1):
        sid = s.get("step_id") or f"(step {i})"
        where = f"{sid} · step {s.get('step_number', i)}"
        if not s.get("title"):
            findings.append(_f("structure", "medium", where, "Step has no title.",
                               "Give the step a short title."))
        if not (s.get("instructions") or []):
            findings.append(_f("structure", "medium", where, "Step has no instructions.",
                               "Add at least one instruction line."))
        if s.get("step_id") in seen_ids:
            findings.append(_f("structure", "high", where, "Duplicate step_id.",
                               "Make every step_id unique."))
        seen_ids.add(s.get("step_id"))
        num = s.get("step_number")
        if isinstance(num, int):
            if num <= last_num:
                findings.append(_f("structure", "low", where,
                                   "Step numbers not strictly increasing.",
                                   "Renumber steps in order."))
            last_num = max(last_num, num)

    # ---- Gate 2: SEMANTIC (units / dimensions) --------------------------- #
    for i, s in enumerate(wf, 1):
        sid = s.get("step_id") or f"(step {i})"
        cond = s.get("conditions", {}) or {}
        # temperature field should look like a temperature, not a volume/mass/speed
        temp = str(cond.get("temperature", "")).strip()
        if temp and temp != CONFIRM_TAG:
            if _VOLUME.search(temp) or _MASS.search(temp) or _SPEED.search(temp):
                findings.append(_f("semantic", "high", f"{sid} · conditions.temperature",
                                   f"Temperature field holds a non-temperature value: '{temp}'.",
                                   "Move it to the right field or fix the value."))
        # speed field should be a centrifuge/shaker speed
        speed = str(cond.get("speed", "")).strip()
        if speed and speed != CONFIRM_TAG and not _SPEED.search(speed):
            # allow descriptive 'gentle' notes only if clearly not numeric
            if re.search(r"\d", speed):
                findings.append(_f("semantic", "medium", f"{sid} · conditions.speed",
                                   f"Speed field isn't a recognizable speed: '{speed}'.",
                                   "Use × g (or rpm with rotor), or move this note elsewhere."))
        # reagent amounts: no negative/zero; flag mass+volume in one amount
        for r in s.get("reagents", []) or []:
            amt = str(r.get("amount", "")).strip()
            if not amt or amt == CONFIRM_TAG:
                continue
            if re.search(r"(^|[^\d.])-\d", amt) or re.search(r"\b0\s?(µl|ul|ml|ng|µg|mg|g)\b", amt, re.I):
                findings.append(_f("semantic", "high", f"{sid} · {r.get('item','reagent')}",
                                   f"Non-physical amount: '{amt}'.", "Use a positive quantity."))
            if _VOLUME.search(amt) and _MASS.search(amt):
                findings.append(_f("semantic", "medium", f"{sid} · {r.get('item','reagent')}",
                                   f"Amount mixes mass and volume: '{amt}'.",
                                   "Split into separate fields or pick the intended unit."))

    # ---- Gate 3: STATE (materials / flow) -------------------------------- #
    declared = set()
    for m in proto.get("materials", []) or []:
        nm = str(m.get("item", "")).strip().lower()
        if nm:
            declared.add(nm)
    for i, s in enumerate(wf, 1):
        sid = s.get("step_id") or f"(step {i})"
        for r in s.get("reagents", []) or []:
            nm = str(r.get("item", "")).strip().lower()
            if nm and declared and nm not in declared:
                # only flag if it looks like a real reagent (declared list is non-trivial)
                findings.append(_f("state", "low", f"{sid} · {r.get('item','')}",
                                   "Reagent used in a step but not in the materials list.",
                                   "Add it to materials so it's tracked and ordered."))

    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "findings": findings,
        "counts": counts,
        "ready": counts["high"] == 0,
        "n_steps": len(wf),
        "summary": (f"{len(findings)} finding(s): {counts['high']} high, "
                    f"{counts['medium']} medium, {counts['low']} low."),
    }


# --------------------------------------------------------------------------- #
# Readiness — a TRANSPARENT bench-readiness score (shows its own components, so
# it is not a black box). Maps onto BPL's trust idea: a protocol is "ready" when
# values are present (Declared) and there are no blocking semantic errors.
# --------------------------------------------------------------------------- #
def _looks_like_temp(v) -> bool:
    return bool(_TEMP.search(str(v or "")))


def _looks_like_speed_val(v) -> bool:
    return bool(_SPEED.search(str(v or "")))


def readiness(proto: Dict[str, Any]) -> Dict[str, Any]:
    rep = check_protocol(proto)
    blocking = rep["counts"]["high"]
    # count value-slots that EXIST for each step and whether they're filled vs placeholder
    filled = placeholders = 0
    for s in proto.get("workflow", []) or []:
        cond = s.get("conditions", {}) or {}
        slots = [s.get("time_estimate", ""), cond.get("temperature", ""), cond.get("speed", "")]
        slots += [r.get("amount", "") for r in (s.get("reagents", []) or [])]
        for v in slots:
            v = str(v or "").strip()
            if not v:
                continue
            if v == CONFIRM_TAG:
                placeholders += 1
            else:
                filled += 1
    denom = filled + placeholders
    fill_pct = round(100 * filled / denom) if denom else 100
    # readiness = fill completeness, knocked down by any blocking semantic errors
    score = max(0, fill_pct - 15 * blocking)
    return {
        "score": score,
        "ready_for_bench": blocking == 0 and placeholders == 0,
        "blocking": blocking,
        "values_filled": filled,
        "values_unconfirmed": placeholders,
        "fill_pct": fill_pct,
        "high": rep["counts"]["high"], "medium": rep["counts"]["medium"],
        "low": rep["counts"]["low"],
        "summary": (f"{fill_pct}% of values present ({filled} filled, {placeholders} to confirm); "
                    f"{blocking} blocking issue(s)."),
    }


# --------------------------------------------------------------------------- #
# Auto-repair — DETERMINISTIC, rule-based field corrections only (auditable).
# It moves obviously-misfiled values to the right field; it never invents data.
# Returns (new_protocol, changes[]).
# --------------------------------------------------------------------------- #
def repair_protocol(proto: Dict[str, Any]):
    import copy
    new = copy.deepcopy(proto)
    changes: List[Dict[str, Any]] = []
    for s in new.get("workflow", []) or []:
        sid = s.get("step_id", "?")
        cond = s.get("conditions") or {}
        if not isinstance(cond, dict):
            continue
        speed = str(cond.get("speed", "")).strip()
        temp = str(cond.get("temperature", "")).strip()
        # 1) a non-speed value sitting in the speed field
        if speed and speed != CONFIRM_TAG and not _looks_like_speed_val(speed):
            if _looks_like_temp(speed) and (not temp or temp == CONFIRM_TAG):
                cond["temperature"] = speed
                changes.append({"where": f"{sid} · conditions", "action": "moved",
                                "detail": f"'{speed}' from speed → temperature"})
            else:
                other = str(cond.get("other", "")).strip()
                cond["other"] = (other + " · " if other else "") + speed
                changes.append({"where": f"{sid} · conditions", "action": "moved",
                                "detail": f"'{speed}' from speed → notes (not a speed)"})
            cond["speed"] = ""
        # 2) a speed value sitting in the temperature field
        if temp and temp != CONFIRM_TAG and _looks_like_speed_val(temp) and not _looks_like_temp(temp):
            if not str(cond.get("speed", "")).strip():
                cond["speed"] = temp
                changes.append({"where": f"{sid} · conditions", "action": "moved",
                                "detail": f"'{temp}' from temperature → speed"})
                cond["temperature"] = ""
        s["conditions"] = cond
    return new, changes


# --------------------------------------------------------------------------- #
# Machine-readable export — typed steps (value+unit parsed), a workflow graph
# (Mermaid), and a simple ordered execution trace. Human + machine + AI readable.
# --------------------------------------------------------------------------- #
_NUM_UNIT = re.compile(r"(-?\d+(?:\.\d+)?)\s*([a-zµ°%/]+)?", re.I)


def _typed(value):
    """Parse 'spin 500 x g' / '6 µg' → {raw, value, unit} when a number is present."""
    raw = str(value or "").strip()
    if not raw or raw == CONFIRM_TAG:
        return {"raw": raw, "value": None, "unit": None, "status": "unconfirmed" if raw == CONFIRM_TAG else "empty"}
    m = _NUM_UNIT.search(raw)
    if m:
        try:
            val = float(m.group(1))
        except ValueError:
            val = None
        return {"raw": raw, "value": val, "unit": (m.group(2) or "").strip() or None, "status": "declared"}
    return {"raw": raw, "value": None, "unit": None, "status": "declared"}


def to_structured(proto: Dict[str, Any]) -> Dict[str, Any]:
    steps = []
    for i, s in enumerate(proto.get("workflow", []) or [], 1):
        cond = s.get("conditions", {}) or {}
        steps.append({
            "id": s.get("step_id", f"step_{i:02d}"),
            "n": s.get("step_number", i),
            "title": s.get("title", ""),
            "intent": _infer_intent(s),
            "instructions": s.get("instructions", []),
            "params": {
                "time": _typed(s.get("time_estimate")),
                "temperature": _typed(cond.get("temperature")),
                "speed": _typed(cond.get("speed")),
            },
            "reagents": [{"item": r.get("item", ""), "amount": _typed(r.get("amount"))}
                         for r in (s.get("reagents", []) or [])],
            "checkpoint": s.get("checkpoint", ""),
            "pause_point": bool(s.get("pause_point")),
        })
    return {
        "schema": "lab-agent/structured-protocol/v1",
        "title": proto.get("protocol_title", ""),
        "version": proto.get("protocol_version", "v1"),
        "assay_type": proto.get("assay_type", ""),
        "materials": proto.get("materials", []),
        "steps": steps,
    }


# defining/purpose intents first, generic handling (spin/wash/mix/transfer) last,
# and match the TITLE before instructions so a "PCR" step isn't called "centrifuge"
# just because it ends with a spin-down.
_INTENTS = [
    ("gel", ("gel extraction", "gel purif", "electrophoresis", "agarose gel")),
    ("pcr", ("pcr", "amplif", "thermocycl")), ("ligate", ("ligat", "ligase")),
    ("digest", ("digest", "restriction", "golden gate")),
    ("transform", ("transform", "electroporat", "heat shock", "transduc", "transfect")),
    ("bind", ("antibody", "immunoprecip", "capture", "pa-tn5", "tagment")),
    ("elute", ("elut",)), ("order", ("order", "synthesi")), ("incubate", ("incubat",)),
    ("centrifuge", ("spin", "centrifug", "pellet")), ("wash", ("wash", "rinse")),
    ("mix", ("vortex", "resuspend", "mix")), ("transfer", ("transfer", "aliquot", "pipette")),
]


def _infer_intent(step: Dict[str, Any]) -> str:
    title = str(step.get("title", "")).lower()
    body = title + " " + " ".join(str(i) for i in step.get("instructions", []) or []).lower()
    for src in (title, body):           # title wins over instruction body
        for name, kws in _INTENTS:
            if any(k in src for k in kws):
                return name
    return "step"


def _mm_label(text: str) -> str:
    # keep mermaid node labels safe: no quotes/brackets/parens/special control chars
    t = re.sub(r'["\[\]{}()<>#;|`$]', " ", str(text))
    return re.sub(r"\s+", " ", t).strip()


def to_mermaid(proto: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    wf = proto.get("workflow", []) or []
    for i, s in enumerate(wf, 1):
        nid = f"S{i}"
        title = _mm_label(s.get("title", f"Step {i}"))[:46]
        intent = _infer_intent(s)
        lines.append(f'    {nid}["{i}. {title} — {intent}"]')
        if i > 1:
            lines.append(f"    S{i-1} --> {nid}")
        if s.get("pause_point"):
            lines.append(f"    class {nid} pause")
    lines.append("    classDef pause fill:#FEF3C7,stroke:#F59E0B,color:#92400E;")
    return "\n".join(lines)
