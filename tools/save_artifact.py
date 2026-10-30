"""
save_artifact
=============
Persist run outputs to ``runs/run_YYYYMMDD_HHMMSS/`` as JSON + Markdown, and
render protocols into human-readable Markdown (full protocol + bench mode).
No model calls here — rendering is purely local.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

# runs/ lives at the project root (one level up from tools/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(_PROJECT_ROOT, "runs")
MEMORY_DIR = os.path.join(_PROJECT_ROOT, "memory")


_CONFIRM_TOKEN = "[confirm with source protocol]"
_JUNK_VALUES = {"n/a", "na", "none", "null", "-", "—", "tbd", "?", ""}


def _md_clean(v: Any) -> str:
    """Display value for markdown, or '' for empties/placeholders/'n/a' so the exported
    protocol never shows 'Speed: n/a' or a forced empty field."""
    s = str(v).strip() if v is not None else ""
    if not s or s == _CONFIRM_TOKEN or s.lower() in _JUNK_VALUES:
        return ""
    return s


def _as_list(v: Any) -> List[Any]:
    """Coerce a value to a list (a model may return a bool/str where a list is
    expected). True/False/None/'' -> []; a non-empty string -> [string]."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [v]
    if isinstance(v, dict):
        return [v]
    return []


def _dictify(items: Any, key: str) -> List[Any]:
    """Coerce each item of a list to a dict. A bare string ``s`` becomes
    ``{key: s}`` so renderers that call ``.get()`` never crash. Non-str/dict
    items are dropped."""
    out: List[Any] = []
    for it in _as_list(items):
        if isinstance(it, dict):
            out.append(it)
        elif isinstance(it, str) and it.strip():
            out.append({key: it})
    return out


# Which primary field a stray string should populate, per list field.
_ITEM_KEY = {
    "materials": "item",
    "qc_checkpoints": "checkpoint_name",
    "decision_points": "decision",
    "failure_branches": "condition",
    "revision_log": "reason",
    "reagents": "item",
    "troubleshooting": "problem",
}


def normalize_protocol(p: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce protocol field types so renderers/UI never crash on malformed
    model output (e.g. human_review_required returned as a bool, or
    qc_checkpoints returned as a list of strings). In place."""
    if not isinstance(p, dict):
        return p
    for key in ("workflow", "materials", "qc_checkpoints", "decision_points",
                "failure_branches", "open_questions_for_human", "revision_log",
                "artifact_outputs", "stages"):
        if key in p and not isinstance(p[key], list):
            p[key] = _as_list(p[key])
    # coerce items of structured (dict-of) list fields to dicts
    for key, item_key in _ITEM_KEY.items():
        if key in p and key != "reagents" and key != "troubleshooting":
            p[key] = _dictify(p.get(key), item_key)
    pre = p.get("preconditions")
    if not isinstance(pre, dict):
        p["preconditions"] = {}
    else:
        for k in ("sample_requirements", "reagent_requirements",
                  "equipment_requirements", "safety_notes",
                  "lab_specific_fields_to_confirm"):
            if k in pre and not isinstance(pre[k], list):
                pre[k] = _as_list(pre[k])
    # backfill step_id / step_number so rewritten or added steps never collide
    # (e.g. two steps with step_id=None producing duplicate UI keys).
    seen_ids: set = set()
    for i, s in enumerate(p.get("workflow", []) or [], 1):
        if not isinstance(s, dict):
            continue
        sid = s.get("step_id")
        if not sid or sid in seen_ids:
            sid = f"step_{i:02d}"
            # ensure uniqueness if step_NN already taken
            while sid in seen_ids:
                i += 1
                sid = f"step_{i:02d}"
            s["step_id"] = sid
        seen_ids.add(s["step_id"])
        if not s.get("step_number"):
            s["step_number"] = i
    for s in p.get("workflow", []) or []:
        if not isinstance(s, dict):
            continue
        for k in ("instructions", "human_review_required", "notes"):
            if k in s and not isinstance(s[k], list):
                s[k] = _as_list(s[k])
        # reagents/troubleshooting are lists of dicts -> coerce items too
        s["reagents"] = _dictify(s.get("reagents"), "item")
        s["troubleshooting"] = _dictify(s.get("troubleshooting"), "problem")
        if not isinstance(s.get("conditions"), dict):
            s["conditions"] = {}
    return p


def new_run_dir() -> str:
    os.makedirs(RUNS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RUNS_DIR, f"run_{stamp}")
    # guard against collisions within the same second
    suffix = 0
    base = path
    while os.path.exists(path):
        suffix += 1
        path = f"{base}_{suffix}"
    os.makedirs(path, exist_ok=True)
    return path


def save_json(run_dir: str, filename: str, data: Any) -> str:
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def save_text(run_dir: str, filename: str, text: str) -> str:
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------- #
# Markdown rendering
# ---------------------------------------------------------------------- #
def _md_list(items: List[Any], bullet: str = "- ") -> str:
    if not items:
        return "_none_\n"
    out = []
    for it in items:
        out.append(f"{bullet}{it}")
    return "\n".join(out) + "\n"


def protocol_to_markdown(proto: Dict[str, Any]) -> str:
    """Full protocol as Markdown (materials, workflow, QC, branches, log)."""
    normalize_protocol(proto)
    lines: List[str] = []
    lines.append(f"# {proto.get('protocol_title', 'Protocol')} ({proto.get('protocol_version', 'v1')})")
    lines.append("")
    lines.append(f"- **检测类型:** {proto.get('assay_type', '')}")
    lines.append(f"- **预期使用者:** {proto.get('intended_user', '')}")
    lines.append(f"- **置信度:** {proto.get('confidence', '')}")
    lines.append(f"- **生成时间:** {proto.get('timestamp', '')}")
    lines.append("")
    lines.append(f"**目的:** {proto.get('objective', '')}\n")
    lines.append(f"**概要:** {proto.get('summary', '')}\n")

    if proto.get("root_cause_diagnosis"):
        lines.append(f"**根因诊断 (修订):** {proto['root_cause_diagnosis']}\n")
    if proto.get("summary_of_changes"):
        lines.append(f"**变更摘要:** {proto['summary_of_changes']}\n")

    pre = proto.get("preconditions", {}) or {}
    lines.append("## 前置条件\n")
    lines.append("**样本要求**\n")
    lines.append(_md_list(pre.get("sample_requirements", [])))
    lines.append("**试剂要求**\n")
    lines.append(_md_list(pre.get("reagent_requirements", [])))
    lines.append("**设备要求**\n")
    lines.append(_md_list(pre.get("equipment_requirements", [])))
    lines.append("**安全注意事项**\n")
    lines.append(_md_list(pre.get("safety_notes", [])))
    lines.append("**需实验室自行确认的字段**\n")
    lines.append(_md_list(pre.get("lab_specific_fields_to_confirm", [])))

    lines.append("## 材料\n")
    lines.append("| 物品 | 供应商 | 货号 | 用量 | 必需 | 备注 |")
    lines.append("|---|---|---|---|---|---|")
    for m in proto.get("materials", []) or []:
        lines.append(
            f"| {m.get('item','')} | {m.get('vendor','')} | {m.get('catalog_number','')} "
            f"| {m.get('amount','')} | {m.get('required','')} | {m.get('notes','')} |"
        )
    lines.append("")

    lines.append("## 工作流程\n")
    for s in proto.get("workflow", []) or []:
        lines.append(f"### 步骤 {s.get('step_number','?')} — {s.get('title','')}  `({s.get('step_id','')})`")
        if s.get("stage"):
            lines.append(f"_阶段: {s['stage']}_\n")
        if s.get("purpose"):
            lines.append(f"*目的:* {s['purpose']}\n")
        cond = s.get("conditions", {}) or {}
        meta = []
        if _md_clean(s.get("time_estimate")):
            meta.append(f"**用时:** {_md_clean(s.get('time_estimate'))}")
        if _md_clean(cond.get("temperature")):
            meta.append(f"**温度:** {_md_clean(cond.get('temperature'))}")
        if _md_clean(cond.get("speed")):
            meta.append(f"**速度:** {_md_clean(cond.get('speed'))}")
        if _md_clean(cond.get("other")):
            meta.append(f"**其他:** {_md_clean(cond.get('other'))}")
        if meta:
            lines.append(" · ".join(meta) + "\n")
        reagents = s.get("reagents", []) or []
        if reagents:
            lines.append("**试剂 (精确用量)**\n")
            lines.append(_md_list([f"{r.get('item','')}: **{r.get('amount','')}**" for r in reagents]))
        lines.append("**操作**\n")
        lines.append(_md_list(s.get("instructions", [])))
        if _md_clean(s.get("expected_observation")):
            lines.append(f"- **预期观察:** {_md_clean(s.get('expected_observation'))}")
        if _md_clean(s.get("checkpoint")):
            lines.append(f"- **检查点:** {_md_clean(s.get('checkpoint'))}")
        if s.get("pause_point"):
            lines.append(f"- **暂停点:** {s.get('pause_point')}")
        if s.get("human_review_required"):
            lines.append("- **⚠ 需人工审查:**")
            for hr in s["human_review_required"]:
                lines.append(f"    - {hr}")
        if s.get("troubleshooting"):
            lines.append("- **故障排除:**")
            for t in s["troubleshooting"]:
                lines.append(f"    - *问题:* {t.get('problem','')}")
                if t.get("possible_causes"):
                    lines.append(f"        - 原因: {', '.join(t['possible_causes'])}")
                if t.get("actions"):
                    lines.append(f"        - 操作: {', '.join(t['actions'])}")
                if t.get("escalate_if"):
                    lines.append(f"        - 出现以下情况时上报: {t['escalate_if']}")
        if s.get("notes"):
            lines.append("- **备注:**")
            for n in s["notes"]:
                lines.append(f"    - {n}")
        lines.append("")

    lines.append("## QC 检查点\n")
    for q in proto.get("qc_checkpoints", []) or []:
        lines.append(f"### {q.get('checkpoint_name','')} — _{q.get('when','')}_")
        lines.append(f"- 测量项: {', '.join(q.get('measurements', []))}")
        lines.append(f"- 通过标准: {', '.join(q.get('pass_criteria', []))}")
        lines.append(f"- 失败信号: {', '.join(q.get('fail_signals', []))}")
        lines.append(f"- 失败时: {q.get('recommended_action_on_fail','')}")
        lines.append("")

    lines.append("## 决策点\n")
    for d in proto.get("decision_points", []) or []:
        lines.append(f"- **{d.get('decision','')}** ({d.get('when','')})")
        for o in d.get("options", []):
            lines.append(f"    - {o}")
    lines.append("")

    lines.append("## 失败分支\n")
    for b in proto.get("failure_branches", []) or []:
        lines.append(f"- **条件:** {b.get('condition','')}")
        lines.append(f"    - 受影响步骤: {', '.join(b.get('step_ids_affected', []))}")
        lines.append(f"    - 可能原因: {', '.join(b.get('likely_causes', []))}")
        lines.append(f"    - 修改措施: {', '.join(b.get('recommended_modifications', []))}")
        lines.append(f"    - 重复/停止: {b.get('whether_to_repeat_or_stop','')}")
    lines.append("")

    lines.append("## 待人工确认的问题\n")
    lines.append(_md_list(proto.get("open_questions_for_human", [])))

    lines.append("## 修订日志\n")
    for r in proto.get("revision_log", []) or []:
        lines.append(
            f"- **{r.get('version','')}** — {r.get('reason','')} "
            f"(变更步骤: {', '.join(r.get('changed_step_ids', [])) or '无'})"
        )
    lines.append("")
    return "\n".join(lines)


def plan_to_markdown(plan: Dict[str, Any]) -> str:
    """Render a day-by-day execution plan as Markdown."""
    lines: List[str] = []
    lines.append(f"# Execution plan — {plan.get('protocol_title','Protocol')} "
                 f"({plan.get('protocol_version','v1')})")
    a = plan.get("assumptions", {}) or {}
    lines.append(f"_Assumptions: {a.get('hours_per_day','?')} h/day, "
                 f"overnight incubations {'allowed' if a.get('allow_overnight', True) else 'not allowed'}._\n")
    lines.append(f"**Total estimated time:** {plan.get('total_estimated_time','')}  ·  "
                 f"**Sessions:** {plan.get('num_sessions', len(plan.get('sessions', [])))}")
    if plan.get("total_hands_on") or plan.get("total_walk_away"):
        lines.append(f"**Hands-on:** {plan.get('total_hands_on','?')}  ·  "
                     f"**Walk-away:** {plan.get('total_walk_away','?')}")
    lines.append("")
    for sess in plan.get("sessions", []) or []:
        ho = sess.get("estimated_hands_on")
        wa = sess.get("estimated_walk_away")
        split = f"  (hands-on {ho} · walk-away {wa})" if ho or wa else ""
        lines.append(f"## {sess.get('title', 'Day')} — {sess.get('estimated_time','')}{split}")
        steps = sess.get("steps", []) or []
        if steps:
            for s in steps:
                stage = f" _({s['stage']})_" if s.get("stage") else ""
                lines.append(f"- ☐ Step {s.get('step_number','?')}: {s.get('title','')}"
                             f"  · {s.get('time_estimate','')}{stage}")
        if sess.get("reagents_to_prepare"):
            lines.append(f"\n**Prepare:** {', '.join(sess['reagents_to_prepare'])}")
        lines.append(f"\n**Break after:** {sess.get('break_after','')}")
        for w in sess.get("warnings", []) or []:
            lines.append(f"> ⚠ {w}")
        for nnote in sess.get("notes", []) or []:
            lines.append(f"> {nnote}")
        lines.append("")
    if plan.get("open_questions"):
        lines.append("## Open questions")
        lines.append(_md_list(plan["open_questions"]))
    return "\n".join(lines)


def bench_to_markdown(proto: Dict[str, Any]) -> str:
    """Bench-mode checklist: compact, one block per step, for printing/bench use."""
    normalize_protocol(proto)
    lines: List[str] = []
    lines.append(f"# 台边模式 — {proto.get('protocol_title','Protocol')} ({proto.get('protocol_version','v1')})")
    lines.append(f"_预期使用者: {proto.get('intended_user','')}_\n")
    safety = (proto.get("preconditions", {}) or {}).get("safety_notes", [])
    if safety:
        lines.append("## ⚠ 安全第一")
        lines.append(_md_list(safety))
    total = len(proto.get("workflow", []) or [])
    for s in proto.get("workflow", []) or []:
        cond = s.get("conditions", {}) or {}
        lines.append(f"## ☐ 步骤 {s.get('step_number','?')}/{total} — {s.get('title','')}")
        if s.get("stage"):
            lines.append(f"_🧩 阶段: {s['stage']}_\n")
        if s.get("purpose"):
            lines.append(f"> {s['purpose']}\n")
        reagents = s.get("reagents", []) or []
        if reagents:
            lines.append("**试剂:**")
            lines.append(_md_list([f"☐ {r.get('item','')}: **{r.get('amount','')}**" for r in reagents]))
        lines.append("**操作:**")
        lines.append(_md_list([f"☐ {i}" for i in s.get("instructions", [])]))
        meta = []
        if s.get("time_estimate"):
            meta.append(f"⏱ {s['time_estimate']}")
        if cond.get("temperature"):
            meta.append(f"🌡 {cond['temperature']}")
        if cond.get("speed"):
            meta.append(f"🔁 {cond['speed']}")
        if meta:
            lines.append("  ".join(meta) + "\n")
        lines.append(f"**预期:** {s.get('expected_observation','')}\n")
        lines.append(f"**检查点:** {s.get('checkpoint','')}\n")
        if s.get("pause_point"):
            lines.append("**⏸ 暂停点 — 可在此安全停止。**\n")
        if s.get("human_review_required"):
            lines.append("**⚠ 人工审查:** " + "; ".join(s["human_review_required"]) + "\n")
        if s.get("troubleshooting"):
            lines.append("**失败时:**")
            for t in s["troubleshooting"]:
                lines.append(f"- {t.get('problem','')} → {', '.join(t.get('actions', []))}")
            lines.append("")
        lines.append("---\n")
    return "\n".join(lines)
