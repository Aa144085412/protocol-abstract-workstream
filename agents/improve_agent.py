"""
ImproveAgent
============
Turns the Review Agent's findings (and the protocol) into CONCRETE, applyable
design additions: missing controls, QC checkpoints, human-review flags, safety
notes, conflict reconciliation, and optional control steps. The user reviews and
applies them.

Additive and conservative: it proposes structural improvements (controls, QC,
flags) and design questions — it does NOT invent exact volumes/times/catalog
numbers (those belong on the Fill page). Routes by the ``improve`` role.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

EMPTY = {
    "add_qc_checkpoints": [], "add_controls": [], "flag_human_review": [],
    "add_safety_notes": [], "add_open_questions": [], "reconcile_conflicts": [],
    "suggested_new_steps": [],
}


def _qc(name, when, measurements, pass_c, fail, action):
    return {"checkpoint_name": name, "when": when, "measurements": measurements,
            "pass_criteria": pass_c, "fail_signals": fail,
            "recommended_action_on_fail": action}


class ImproveAgent(BaseAgent):
    name = "Design Assistant"
    tier = "strong"
    role = "improve"

    def suggest(self, protocol: Dict[str, Any], review: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = {"protocol": protocol, "review": review or {}}
        if self.demo_mode:
            out = self._demo(payload)
            out.update({"agent": self.name, "status": "success", "mode": "offline",
                        "timestamp": utc_timestamp()})
            return out
        prompt = self.load_prompt(
            "improve_agent.txt",
            protocol_title=protocol.get("protocol_title", ""),
            assay_type=protocol.get("assay_type", ""),
            workflow=json.dumps([{"step_id": s.get("step_id"), "step_number": s.get("step_number"),
                                  "title": s.get("title")} for s in protocol.get("workflow", []) or []],
                                ensure_ascii=False)[:6000],
            findings=json.dumps((review or {}).get("findings", []), ensure_ascii=False)[:8000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=4096, temperature=0.2, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        merged = {**EMPTY, **{k: data.get(k, EMPTY[k]) for k in EMPTY}}
        merged.update({"agent": self.name, "status": "success", "mode": "live",
                       "summary": data.get("summary", ""), "timestamp": utc_timestamp()})
        return merged

    # ------------------------------------------------------------------ #
    def _demo(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import copy
        proto = payload["protocol"]
        review = payload.get("review") or {}
        out = copy.deepcopy(EMPTY)
        wf = proto.get("workflow", []) or []
        text = " ".join([proto.get("protocol_title", ""), proto.get("assay_type", ""),
                         " ".join(s.get("title", "") for s in wf)]).lower()

        def add_control(c):
            if c not in out["add_controls"]:
                out["add_controls"].append(c)

        def add_q(q):
            if q not in out["add_qc_checkpoints"]:
                out["add_qc_checkpoints"].append(q)

        # --- assay-driven standard controls & QC ---
        if any(k in text for k in ("lentivir", "transduc", "virus")):
            add_control("Negative control: mock-transfected producer cells (no viral plasmids) to confirm signal is virus-dependent.")
            add_control("Baseline control: untransduced target cells for FACS gating and background fluorescence.")
            add_q(_qc("Lentiviral titer", "Before transduction",
                      ["Functional titer (or p24 ELISA / qPCR)"],
                      ["Titer sufficient for target MOI"], ["Low/no titer"],
                      "Re-produce or concentrate virus; do not proceed to transduction."))
            add_q(_qc("Post-transduction viability", "1-3 days post-transduction",
                      ["Viability (%)", "Cell count"], ["Viability within acceptable range"],
                      ["High death / low recovery"], "Reduce MOI / polybrene; optimize spinoculation."))
        if "transfect" in text:
            add_control("Mock (no-DNA / GFP-only) transfection control to gauge baseline expression and toxicity.")
            add_q(_qc("Transfection efficiency", "24-48 h post-transfection",
                      ["% fluorescent producer cells"], ["Efficiency within expected range"],
                      ["Low efficiency"], "Re-check DNA quality/ratio and reagent; repeat."))
        if any(k in text for k in ("pcr", "cloning", "sequenc", "amplif")):
            add_control("No-template control (NTC) for every PCR to detect contamination.")
        if any(k in text for k in ("western", "blot", "immunoblot")):
            add_control("Western blot loading control (housekeeping protein) and a known-positive standard.")
        if any(k in text for k in ("scrna", "single cell", "10x", "single-cell")):
            add_q(_qc("Single-cell suspension QC", "Before loading",
                      ["Viability (%)", "Cell concentration", "Doublet/debris check"],
                      ["Viability and concentration meet platform targets"],
                      ["Low viability / clumping"], "Dead-cell removal; re-prepare suspension."))

        # --- convert review findings into actionable buckets ---
        for f in review.get("findings", []) or []:
            cat = (f.get("category") or "").lower()
            issue = f.get("issue", "")
            if not issue:
                continue
            if "control" in cat:
                add_control(issue)
            elif "qc" in cat:
                out["add_open_questions"].append(f"QC to add: {issue}")
            elif "over_invention" in cat:
                out["add_open_questions"].append(f"Confirm or mark uncertain: {issue}")
            elif "human_review" in cat:
                out["add_open_questions"].append(f"Flag for human review: {issue}")
            elif "safety" in cat:
                out["add_safety_notes"].append(issue)
            elif "completeness" in cat:
                if any(w in issue.lower() for w in ("conflict", "vs.", "vs ", "reconcil", "discrepan")):
                    out["reconcile_conflicts"].append(issue)
                else:
                    out["add_open_questions"].append(issue)
            else:
                out["add_open_questions"].append(issue)

        # de-dup open questions / reconcile / safety
        for key in ("add_open_questions", "reconcile_conflicts", "add_safety_notes"):
            seen, uniq = set(), []
            for x in out[key]:
                if x not in seen:
                    seen.add(x); uniq.append(x)
            out[key] = uniq

        n = sum(len(out[k]) for k in EMPTY)
        out["summary"] = (f"Proposed {len(out['add_controls'])} control(s), "
                          f"{len(out['add_qc_checkpoints'])} QC checkpoint(s), and "
                          f"{n - len(out['add_controls']) - len(out['add_qc_checkpoints'])} other "
                          "design item(s) from standard practice and the review findings.")
        return out
