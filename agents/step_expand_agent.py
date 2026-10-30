"""
StepExpandAgent
===============
Rewrites a single sparse protocol step into detailed, self-contained, ordered
bench instructions — so the user can follow it in-app without the external
manufacturer guide. Routes by the ``expand`` role.

Honesty: it makes the *procedure* richer (sub-steps, technique, what to watch
for) but does NOT invent exact volumes/times/temperatures/speeds or catalog
numbers — anything unknown stays "[confirm with source protocol]".
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

# How verbose the rewritten step should be, per user experience level.
_LEVEL_DETAIL = {
    "beginner": ("AUDIENCE: undergraduate / first time at the bench. Write the LONGEST, most "
                 "detailed version: break every action into small numbered sub-steps, define "
                 "techniques and acronyms inline, and add a brief why-it-matters plus a "
                 "common-mistake/safety note. Aim for thorough, nothing assumed."),
    "intermediate": ("AUDIENCE: master's / PhD student with bench experience. Write standard "
                     "detail: clear ordered sub-steps with the key rationale and critical "
                     "checkpoints. Skip definitions of routine techniques; flag non-obvious choices."),
    "expert": ("AUDIENCE: scientist / PI. Write the SHORTEST useful version: terse, technical "
               "sub-steps, exact parameters only, no basic explanation. Surface only non-standard, "
               "risky or decision-critical points."),
}


def _norm_level(level: str) -> str:
    l = (level or "intermediate").lower()
    if any(k in l for k in ("begin", "novice", "undergrad")):
        return "beginner"
    if any(k in l for k in ("expert", "advanced", "senior", "scientist", "pi")):
        return "expert"
    return "intermediate"


class StepExpandAgent(BaseAgent):
    name = "Step Detailer"
    tier = "strong"
    role = "expand"

    def expand(self, protocol: Dict[str, Any], step: Dict[str, Any],
               level: str = "intermediate") -> Dict[str, Any]:
        if self.demo_mode:
            return {"agent": self.name, "status": "success", "mode": "offline",
                    "instructions": self._demo_expand(step, level),
                    "notes": ["[Expanded offline — generic guidance added. For full "
                              "detail + manufacturer values set DEMO_MODE=false.]"],
                    "timestamp": utc_timestamp()}
        use_web = self.provider == "anthropic"
        mats = ", ".join(m.get("item", "") for m in protocol.get("materials", []) or [])[:400]
        slim_step = {k: step.get(k) for k in
                     ("step_number", "title", "purpose", "instructions",
                      "time_estimate", "conditions", "reagents", "expected_observation")}
        prompt = self.load_prompt(
            "step_expand_agent.txt",
            protocol_title=protocol.get("protocol_title", ""),
            assay_type=protocol.get("assay_type", ""),
            materials=mats,
            web_hint=("Use web search to find the named kit/manufacturer's published "
                      "protocol and use its EXACT values (volumes, speeds, times) instead "
                      "of placeholders." if use_web else
                      "Use your knowledge of the named kit's published protocol for exact values."),
            level=level,
            level_directive=_LEVEL_DETAIL[_norm_level(level)],
            step=json.dumps(slim_step, ensure_ascii=False)[:6000],
        )
        try:
            data = self.extract_json(self.call(
                prompt, max_tokens=3072, temperature=0.2, json_mode=True,
                tools=[WEB_SEARCH_TOOL] if use_web else None))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        instr = data.get("instructions") if isinstance(data, dict) else None
        if not isinstance(instr, list) or not instr:
            return self.error("model did not return an instructions list")
        notes = [str(x) for x in (data.get("notes") or [])]
        for src in (data.get("sources") or []):
            url = src.get("url", "") if isinstance(src, dict) else str(src)
            if url:
                notes.append(f"Source: {url}")
        return {"agent": self.name, "status": "success", "mode": "live_web" if use_web else "live",
                "instructions": [str(x) for x in instr], "notes": notes,
                "timestamp": utc_timestamp()}

    # ------------------------------------------------------------------ #
    def _demo_expand(self, step: Dict[str, Any], level: str) -> List[str]:
        base = list(step.get("instructions", []) or [])
        title = (step.get("title", "") + " " + " ".join(base)).lower()
        tips: List[str] = []
        tips.append("Lay out and label all tubes/plates before starting; keep an "
                    "open log of the actual volumes and times you use.")
        if any(k in title for k in ("cell", "transduc", "transfect", "viab", "scrna", "k562", "hek")):
            tips.append("Work gently and minimise the time cells spend out of the incubator; "
                        "pre-warm media unless the source says otherwise.")
        if any(k in title for k in ("centrifug", "spin", "pellet")):
            tips.append("Balance the centrifuge; after the spin, note pellet appearance "
                        "before removing supernatant so you don't disturb it.")
        if any(k in title for k in ("wash", "elut", "bind", "column")):
            tips.append("Pipette to the side of the column/well to avoid disturbing the "
                        "membrane/pellet; discard flow-through to the correct waste.")
        if any(k in title for k in ("lys", "incubat")):
            tips.append("Time the incubation precisely and do not exceed any stated maximum; "
                        "set a timer.")
        if any(k in title for k in ("virus", "lentivir", "bsl")):
            tips.append("Handle in a BSL-2 cabinet with appropriate PPE; treat all "
                        "virus-contacted plasticware/liquids as biohazard waste.")
        tips.append(f"Confirm any value still shown as '{CONFIRM}' against your source "
                    "protocol or fill it on the Fill page before bench use.")
        # length scales with experience: experts get only the must-do confirm note,
        # beginners get the full set of guidance sub-steps.
        lvl = _norm_level(level)
        if lvl == "expert":
            tips = tips[-1:]
        elif lvl == "intermediate":
            tips = tips[:1] + tips[-1:] if len(tips) > 2 else tips
        # interleave: keep originals, append guidance as sub-steps
        return base + [f"(Guidance) {t}" for t in tips]
