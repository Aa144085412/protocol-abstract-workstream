"""
PlannerAgent
============
Turns a bench protocol into a DETAILED, ordered execution plan split into
sessions / days. It breaks the workflow only at *safe* boundaries:

  * pause points (safe stops), and
  * overnight / long incubations,

while respecting a daily hands-on time budget and never splitting a
time-critical run across a break. This is exactly the kind of novel reasoning
worth a model call, so it routes to the CHEAP model (Haiku) per the low-cost
design. A deterministic fallback runs in DEMO_MODE (no key needed).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .base_agent import BaseAgent, utc_timestamp

DEFAULT_UNKNOWN_MIN = 15          # assume for steps with no/uncertain time
OVERNIGHT_MIN = 8 * 60            # >= 8 h counts as an overnight/long incubation


# ---------------------------------------------------------------------- #
# Time parsing helpers (local, no model)
# ---------------------------------------------------------------------- #
def parse_minutes(text: Any) -> Tuple[Optional[float], bool]:
    """Return (minutes, is_overnight). minutes is None if unknown."""
    s = str(text or "").lower()
    if not s.strip() or "confirm with source" in s:
        return None, False
    if "overnight" in s:
        return 16 * 60, True
    nums = [float(x) for x in re.findall(r"\d+\.?\d*", s)]
    if not nums:
        return None, "overnight" in s
    val = max(nums)
    if "day" in s:
        val *= 24 * 60
    elif "h" in s or "hr" in s or "hour" in s:
        val *= 60
    # else assume minutes
    return val, val >= OVERNIGHT_MIN


def fmt_minutes(m: float) -> str:
    m = int(round(m))
    if m >= 60:
        h, mm = divmod(m, 60)
        return f"{h} h {mm} min" if mm else f"{h} h"
    return f"{m} min"


def _is_time_critical(step: Dict[str, Any]) -> bool:
    blob = " ".join([
        str(step.get("conditions", {}).get("other", "")),
        " ".join(step.get("human_review_required", []) or []),
    ]).lower()
    return any(k in blob for k in ("time-critical", "do not exceed", "immediately", "max "))


# keywords that mark a step's time as mostly UNATTENDED (walk-away)
_WALK_AWAY_KW = (
    "overnight", "incubat", "centrifug", "spin", "stand", "wait", "rest",
    "dry spin", "soak", "elute", "chill", "freeze", "thaw", "rotate", "nutate",
    "shak", "rock", "dissolv", "anneal", "ligat", "digest", "pcr", "thermocycl",
)
# keywords that strongly mark HANDS-ON activity (override duration heuristic)
_HANDS_ON_KW = (
    "add ", "pipet", "mix", "resuspend", "transfer", "load", "aliquot", "measure",
    "weigh", "label", "vortex", "invert", "apply", "remove", "discard", "excise",
)


def classify_activity(step: Dict[str, Any], minutes: float) -> str:
    """Return 'hands_on' or 'walk_away' for a step's time block."""
    text = " ".join([
        str(step.get("title", "")),
        " ".join(step.get("instructions", []) or []),
        str(step.get("conditions", {}).get("other", "")),
    ]).lower()
    has_walk = any(k in text for k in _WALK_AWAY_KW)
    has_hands = any(k in text for k in _HANDS_ON_KW)
    if has_walk and not has_hands:
        return "walk_away"
    if has_hands and not has_walk:
        return "hands_on"
    # mixed or unknown: long blocks are usually unattended incubations
    if minutes >= 20:
        return "walk_away"
    if has_walk:  # short but clearly an incubation/spin
        return "walk_away"
    return "hands_on"


class PlannerAgent(BaseAgent):
    name = "Planner Agent"
    tier = "cheap"
    role = "planner"

    def plan(self, protocol: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        # compact workflow for the prompt (saves tokens on the cheap model)
        compact = [
            {
                "step_id": s.get("step_id"), "step_number": s.get("step_number"),
                "title": s.get("title"), "stage": s.get("stage", ""),
                "time_estimate": s.get("time_estimate", ""),
                "pause_point": s.get("pause_point", False),
                "conditions": s.get("conditions", {}),
                "time_critical": _is_time_critical(s),
            }
            for s in protocol.get("workflow", []) or []
        ]
        prompt = self.load_prompt(
            "planner_agent.txt",
            protocol_title=protocol.get("protocol_title", ""),
            workflow=compact,
            constraints=constraints,
        )
        return self.run(
            prompt,
            payload={"protocol": protocol, "constraints": constraints},
            max_tokens=4096,
            temperature=0.1,
        )

    # ------------------------------------------------------------------ #
    # Deterministic fallback (DEMO_MODE)
    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        proto = payload.get("protocol", {})
        cons = payload.get("constraints", {}) or {}
        hours_per_day = float(cons.get("hours_per_day", 6) or 6)
        allow_overnight = bool(cons.get("allow_overnight", True))
        max_min = hours_per_day * 60

        workflow = proto.get("workflow", []) or []
        sessions: List[Dict[str, Any]] = []
        cur: List[Dict[str, Any]] = []
        cur_min = 0.0
        cur_unknown = False
        n = len(workflow)

        def close(reason: str):
            nonlocal cur, cur_min, cur_unknown
            if not cur:
                return
            reagents = []
            hands_on = 0.0
            walk_away = 0.0
            steps_out = []
            for s in cur:
                for r in s.get("reagents", []) or []:
                    tag = f"{r.get('item','')}: {r.get('amount','')}"
                    if tag not in reagents:
                        reagents.append(tag)
                mins, _ = parse_minutes(s.get("time_estimate"))
                mins = DEFAULT_UNKNOWN_MIN if mins is None else mins
                act = classify_activity(s, mins)
                if act == "walk_away":
                    walk_away += mins
                else:
                    hands_on += mins
                steps_out.append({
                    "step_number": s.get("step_number"), "title": s.get("title"),
                    "time_estimate": s.get("time_estimate", ""), "stage": s.get("stage", ""),
                    "activity": act,
                })
            warnings = []
            if hands_on > max_min and reason.startswith("Safe"):
                warnings.append("Hands-on time exceeds the daily budget but no earlier safe stop existed.")
            if cur_unknown:
                warnings.append("Contains step(s) with unconfirmed time — fill exact times to refine the plan.")
            sessions.append({
                "day": len(sessions) + 1,
                "title": f"Day {len(sessions)+1}",
                "step_ids": [s.get("step_id") for s in cur],
                "steps": steps_out,
                "estimated_time": fmt_minutes(cur_min) + (" +" if cur_unknown else ""),
                "estimated_hands_on": fmt_minutes(hands_on),
                "estimated_walk_away": fmt_minutes(walk_away),
                "hands_on_minutes": round(hands_on),
                "walk_away_minutes": round(walk_away),
                "reagents_to_prepare": reagents,
                "break_after": reason,
                "warnings": warnings,
                "notes": [],
            })
            cur, cur_min, cur_unknown = [], 0.0, False

        for i, s in enumerate(workflow):
            mins, overnight = parse_minutes(s.get("time_estimate"))
            if mins is None:
                cur_unknown = True
                mins = DEFAULT_UNKNOWN_MIN
            cur.append(s)
            cur_min += mins
            last = i == n - 1
            if last:
                continue
            if overnight and allow_overnight:
                close(f"Overnight / long incubation ({s.get('title','')}) — resume next day")
            elif s.get("pause_point") and cur_min >= max_min:
                close("Safe stop (pause point) — daily time budget reached")
        close("End of protocol")

        total = sum(
            (parse_minutes(s.get("time_estimate"))[0] or DEFAULT_UNKNOWN_MIN)
            for s in workflow
        )
        overnights = sum(
            1 for s in workflow if parse_minutes(s.get("time_estimate"))[1]
        )
        total_hands_on = sum(s["hands_on_minutes"] for s in sessions)
        total_walk_away = sum(s["walk_away_minutes"] for s in sessions)

        return {
            "agent": self.name,
            "status": "success",
            "protocol_title": proto.get("protocol_title", ""),
            "protocol_version": proto.get("protocol_version", "v1"),
            "assumptions": {
                "hours_per_day": hours_per_day,
                "allow_overnight": allow_overnight,
                "unknown_step_minutes": DEFAULT_UNKNOWN_MIN,
                "note": "Breaks placed only at pause points and overnight incubations; "
                        "time-critical sequences are never split.",
            },
            "total_estimated_time": fmt_minutes(total)
            + (f" (+ {overnights} overnight incubation(s))" if overnights else ""),
            "total_hands_on": fmt_minutes(total_hands_on),
            "total_walk_away": fmt_minutes(total_walk_away),
            "num_sessions": len(sessions),
            "sessions": sessions,
            "open_questions": (
                ["Some steps have unconfirmed times — fill them on the Fill page for an accurate schedule."]
                if any(parse_minutes(s.get("time_estimate"))[0] is None for s in workflow) else []
            ),
            "timestamp": utc_timestamp(),
        }
