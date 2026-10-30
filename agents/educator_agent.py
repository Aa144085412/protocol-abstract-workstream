"""
EducatorAgent
=============
Teaches the experiment at a depth matched to the user's experience level
(beginner / intermediate / expert). For each stage it explains WHY it is done,
the concept behind it, what commonly goes wrong, and (for beginners) defines
jargon. This is training/education — not new design, not hypotheses.

Depth is taken from the project/protocol experience level. Routes to the cheap
model; a deterministic outline runs in DEMO_MODE.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

_DEPTH = {
    "beginner": "Assume little prior knowledge. Define every technique and acronym, "
                "explain the purpose of each step in plain language, and give concrete "
                "do/don't tips. Short sentences.",
    "intermediate": "Assume working bench experience. Focus on the rationale, the "
                    "critical control points, and why parameters matter. Define only "
                    "specialized jargon.",
    "expert": "Assume an experienced scientist. Be concise and technical; emphasize "
              "design rationale, failure modes, and subtle pitfalls. Skip basics.",
}


def _norm_level(level: str) -> str:
    l = (level or "").lower()
    if "begin" in l or "novice" in l:
        return "beginner"
    if "expert" in l or "advanced" in l or "senior" in l:
        return "expert"
    return "intermediate"


class EducatorAgent(BaseAgent):
    name = "Experiment Educator"
    tier = "cheap"
    role = "educator"

    def teach(self, protocol: Dict[str, Any], experience_level: str = "intermediate",
              source_docs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        protocol = protocol or {}
        level = _norm_level(experience_level)
        source_docs = source_docs or []
        if self.demo_mode:
            return self._demo(protocol, level)
        wf = [{"step_number": s.get("step_number"), "title": s.get("title"),
               "purpose": s.get("purpose"), "instructions": s.get("instructions")}
              for s in protocol.get("workflow", []) or []]
        prompt = self.load_prompt(
            "educator_agent.txt",
            level=level, level_guidance=_DEPTH[level],
            protocol_title=protocol.get("protocol_title", "this protocol"),
            core_experiment=protocol.get("core_experiment", "") or protocol.get("objective", ""),
            workflow=json.dumps(wf, ensure_ascii=False)[:9000],
            notes=json.dumps([{"title": d.get("title", ""), "text": (d.get("text", "") or "")[:800]}
                              for d in source_docs[:6]], ensure_ascii=False)[:5000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=3500, temperature=0.2, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        data.setdefault("agent", self.name)
        data.setdefault("status", "success")
        data["level"] = level
        data["mode"] = "live"
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def _demo(self, proto, level) -> Dict[str, Any]:
        wf = proto.get("workflow", []) or []
        lessons = []
        for s in wf:
            lessons.append({
                "step_number": s.get("step_number"),
                "title": s.get("title"),
                "why_it_matters": s.get("purpose") or "Purpose: see protocol step.",
                "concept": "Key concept for this step (run live for a full explanation).",
                "common_pitfalls": [t.get("problem") for t in (s.get("troubleshooting") or [])][:3],
            })
        return {
            "agent": self.name, "status": "success", "mode": "offline", "level": level,
            "overview": (f"Education outline at '{level}' depth for "
                         f"{proto.get('protocol_title','this protocol')} "
                         f"({len(wf)} steps). Run live (DEMO_MODE=false) for full explanations, "
                         "concept teaching, and a glossary."),
            "lessons": lessons,
            "glossary": [],
            "timestamp": utc_timestamp(),
        }
