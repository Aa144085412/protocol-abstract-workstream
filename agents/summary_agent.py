"""
SummaryAgent
============
Project summarization / onboarding. Turns a project's protocol(s) + reference
documents into a concise "get up to speed" brief: the goal, the experimental
design logic, the arms/conditions, a stage-by-stage overview, and current status.

Reads only what's on file — it does not invent results or hypotheses. Routes to
the cheap model; a deterministic brief runs in DEMO_MODE.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp


class SummaryAgent(BaseAgent):
    name = "Project Summarizer"
    tier = "cheap"
    role = "summary"

    def summarize(self, protocol: Dict[str, Any], source_docs: List[Dict[str, Any]] | None = None,
                  experiments: List[Dict[str, Any]] | None = None,
                  project_name: str = "") -> Dict[str, Any]:
        protocol = protocol or {}
        source_docs = source_docs or []
        experiments = experiments or []
        if self.demo_mode:
            return self._demo(protocol, source_docs, experiments, project_name)
        slim_docs = [{"title": d.get("title", ""), "doc_type": d.get("doc_type", ""),
                      "text": (d.get("text", "") or "")[:1500]} for d in source_docs[:12]]
        slim_proto = {k: protocol.get(k) for k in
                      ("protocol_title", "core_experiment", "objective", "assay_type",
                       "summary", "workflow")}
        if isinstance(slim_proto.get("workflow"), list):
            slim_proto["workflow"] = [{"step_number": s.get("step_number"), "title": s.get("title")}
                                      for s in slim_proto["workflow"]]
        prompt = self.load_prompt(
            "summary_agent.txt", project_name=project_name or "this project",
            protocol=json.dumps(slim_proto, ensure_ascii=False)[:6000],
            documents=json.dumps(slim_docs, ensure_ascii=False)[:30000],
            experiments=json.dumps(
                [{"title": e.get("title"), "status": e.get("status"), "notes": e.get("notes")}
                 for e in experiments], ensure_ascii=False)[:3000],
        )
        try:
            raw = self.call(prompt, max_tokens=2500, temperature=0.2, json_mode=True)
            data = self.extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            # fall back to the deterministic brief instead of erroring out
            fb = self._demo(protocol, source_docs, experiments, project_name)
            fb["note"] = f"Live summary unavailable ({exc}); showing a structured brief instead."
            return fb
        if not isinstance(data, dict):
            return self._demo(protocol, source_docs, experiments, project_name)
        # the model must not override our status to a non-success sentinel
        data["agent"] = self.name
        data["status"] = "success"
        data["mode"] = "live"
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def _demo(self, proto, docs, exps, project_name) -> Dict[str, Any]:
        wf = proto.get("workflow", []) or []
        by_type: Dict[str, int] = {}
        for d in docs:
            by_type[d.get("doc_type", "other")] = by_type.get(d.get("doc_type", "other"), 0) + 1
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "project_name": project_name,
            "one_liner": proto.get("core_experiment") or proto.get("objective")
            or proto.get("protocol_title", "Project"),
            "goal": proto.get("objective", "") or "(see protocol objective)",
            "design_logic": proto.get("design_rationale", "")
            or "Stage-ordered protocol; see workflow below.",
            "stages": [f"Step {s.get('step_number')}: {s.get('title')}" for s in wf],
            "documents_on_file": by_type,
            "status_of_experiments": [
                {"title": e.get("title"), "status": e.get("status")} for e in exps],
            "summary": (
                f"{project_name or 'This project'} — {len(wf)} workflow step(s), "
                f"{sum(by_type.values())} reference document(s) on file. "
                "Offline brief built from the protocol structure; run live for a narrative synthesis."),
            "timestamp": utc_timestamp(),
        }
