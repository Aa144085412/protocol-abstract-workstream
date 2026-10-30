"""
DesignAgent
===========
Synthesizes ONE coherent, non-redundant experiment from many heterogeneous
documents (protocols + background + literature), instead of naively concatenating
them. It:

  1. identifies the CORE biological experiment / objective,
  2. de-duplicates overlapping protocol variants (e.g. several lentivirus
     transduction versions) into a single logical path,
  3. emits the actual non-redundant workflow steps, with provenance and a
     rationale for the design choices.

Routes to the STRONG model (novel experimental-design reasoning). A deterministic
de-duplicating outline runs in DEMO_MODE.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"
_STOP = {"the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "by",
         "step", "prepare", "perform", "using", "via", "from", "into"}


def _tok(s: str):
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


class DesignAgent(BaseAgent):
    name = "Design Agent"
    tier = "strong"
    role = "design"

    def design(self, docs: List[Dict[str, Any]], user_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.demo_mode:
            return self._demo_design(docs, user_context)
        slim = [
            {"title": d.get("protocol_title", ""), "assay_type": d.get("assay_type", ""),
             "summary": d.get("summary", "")[:400],
             "major_steps": d.get("major_steps", [])[:25],
             "materials": [m.get("item", "") for m in d.get("materials", [])][:25]}
            for d in docs
        ]
        prompt = self.load_prompt(
            "design_agent.txt",
            user_context=json.dumps(user_context, ensure_ascii=False),
            documents=json.dumps(slim, ensure_ascii=False)[:14000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=16000, temperature=0.2, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        data.setdefault("agent", self.name)
        data.setdefault("status", "success")
        data.setdefault("protocol_version", "v1")
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def _demo_design(self, docs: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
        # 1. core experiment from the most common assay / the user goal
        assays = [d.get("assay_type", "") for d in docs if d.get("assay_type")]
        core = ctx.get("experiment_name") or (max(set(assays), key=assays.count) if assays else "Experiment")

        # 2. collect candidate steps with provenance, de-duplicating near-identical ones
        merged: List[Dict[str, Any]] = []
        for d in docs:
            for ms in d.get("major_steps", []) or []:
                toks = _tok(ms)
                if not toks:
                    continue
                hit = None
                for s in merged:
                    inter = toks & s["tokens"]
                    if inter and len(inter) / min(len(toks), len(s["tokens"])) >= 0.6:
                        hit = s
                        break
                if hit:
                    hit["sources"].add(d.get("protocol_title", ""))
                    if len(ms) > len(hit["title"]):
                        hit["title"] = ms
                else:
                    merged.append({"title": ms, "tokens": toks,
                                   "sources": {d.get("protocol_title", "")}})

        # 3. redundancies: documents that overlap heavily in their steps
        redundancies = []
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                a = set().union(*[_tok(s) for s in docs[i].get("major_steps", [])]) if docs[i].get("major_steps") else set()
                b = set().union(*[_tok(s) for s in docs[j].get("major_steps", [])]) if docs[j].get("major_steps") else set()
                if a and b and len(a & b) / min(len(a), len(b)) >= 0.6:
                    redundancies.append(
                        f"'{docs[i].get('protocol_title','')}' and "
                        f"'{docs[j].get('protocol_title','')}' overlap heavily — merged into one path.")

        # 4. build a non-redundant workflow
        workflow = []
        for i, s in enumerate(merged, 1):
            srcs = ", ".join(sorted(x for x in s["sources"] if x))
            workflow.append({
                "step_id": f"step_{i:02d}", "step_number": i, "title": s["title"],
                "purpose": "", "instructions": [s["title"]],
                "time_estimate": CONFIRM,
                "conditions": {"temperature": CONFIRM, "speed": "", "other": ""},
                "reagents": [], "expected_observation": "",
                "checkpoint": "", "pause_point": False,
                "human_review_required": [], "troubleshooting": [],
                "notes": [f"Source(s): {srcs}"] if srcs else [],
            })

        # 5. de-duplicate materials across all docs
        seen, materials = set(), []
        for d in docs:
            for m in d.get("materials", []) or []:
                key = m.get("item", "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    materials.append(m)

        return {
            "agent": self.name, "status": "success",
            "protocol_title": f"Designed experiment: {core}",
            "protocol_version": "v1", "assay_type": core,
            "core_experiment": core,
            "objective": f"Run the core {core} experiment as one logical, non-redundant workflow "
                         f"synthesized from {len(docs)} source document(s).",
            "intended_user": ctx.get("experience_level", "mixed"),
            "summary": (f"Synthesized a single non-redundant protocol from {len(docs)} documents, "
                        f"merging {sum(len(d.get('major_steps',[])) for d in docs)} candidate steps "
                        f"into {len(workflow)} logical steps."),
            "design_rationale": (
                f"Identified the core experiment as '{core}'. Overlapping steps across documents "
                "were merged so each logical operation appears once; review the source notes on "
                "each step and fill exact values."),
            "redundancies_resolved": redundancies,
            "preconditions": {"sample_requirements": [], "reagent_requirements": [m.get("item", "") for m in materials],
                              "equipment_requirements": [], "safety_notes": [],
                              "lab_specific_fields_to_confirm": []},
            "materials": materials, "workflow": workflow,
            "qc_checkpoints": [], "decision_points": [], "failure_branches": [],
            "artifact_outputs": [],
            "revision_log": [{"version": "v1", "reason": "designed from documents", "changed_step_ids": []}],
            "open_questions_for_human": [
                "Confirm the merged path matches your intended experiment; fill exact values per step.",
            ],
            "confidence": "low", "mode": "offline", "timestamp": utc_timestamp(),
        }
