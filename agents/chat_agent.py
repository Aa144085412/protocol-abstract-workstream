"""
ChatAgent
=========
A bench-side Q&A assistant scoped to the CURRENT protocol. Ask things like
"what volume of P2 in step 3?", "what's the spin speed?", "what do I do if low
yield?", "how many days will this take?".

- DEMO_MODE=true  -> offline, protocol-aware heuristic answers (no key needed).
- DEMO_MODE=false -> cheap model (Haiku) with the protocol + step as context.

It answers ONLY from the protocol (and general bench knowledge when live); it
must not invent missing numbers — it points to ``[confirm with source protocol]``
and the Fill page instead.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"

# Side-by-side guidance depth, matched to the user's experience level.
_LEVEL_GUIDE = {
    "beginner": ("The user is an UNDERGRADUATE / first-timer. Teach as you answer: define "
                 "terms and acronyms, explain the reasoning, and warn about common beginner "
                 "mistakes. Favour fuller, friendlier explanations."),
    "intermediate": ("The user is a MASTER'S / PhD student with bench experience. Be focused: "
                     "give the rationale, decision points and what to verify; skip basic "
                     "definitions unless asked."),
    "expert": ("The user is a SCIENTIST / PI. Be concise and technical; emphasize trade-offs, "
               "edge cases and deviations from convention. No basic explanation."),
}


def _norm_level(level: str) -> str:
    l = (level or "intermediate").lower()
    if any(k in l for k in ("begin", "novice", "undergrad")):
        return "beginner"
    if any(k in l for k in ("expert", "advanced", "senior", "scientist", "pi")):
        return "expert"
    return "intermediate"


class ChatAgent(BaseAgent):
    name = "Assistant"
    tier = "cheap"
    role = "chat"

    def ask(self, question: str, protocol: Dict[str, Any],
            history: Optional[List[Dict[str, str]]] = None,
            current_step: Optional[Dict[str, Any]] = None,
            level: str = "intermediate") -> Dict[str, Any]:
        if self.demo_mode:
            return {
                "agent": self.name, "status": "success",
                "answer": self._demo_answer(question, protocol, current_step),
                "mode": "offline", "timestamp": utc_timestamp(),
            }
        # live: Haiku with context
        context = self._context_blob(protocol, current_step)
        hist = ""
        for h in (history or [])[-6:]:
            hist += f"\n{h.get('role','user').upper()}: {h.get('content','')}"
        prompt = self.load_prompt(
            "chat_agent.txt", protocol_context=context, history=hist, question=question,
            level_directive=_LEVEL_GUIDE[_norm_level(level)],
        )
        try:
            answer = self.call(prompt, max_tokens=1024, temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        return {"agent": self.name, "status": "success", "answer": answer,
                "mode": "live", "timestamp": utc_timestamp()}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _context_blob(protocol: Dict[str, Any], current_step: Optional[Dict[str, Any]]) -> str:
        import json
        slim = {
            "protocol_title": protocol.get("protocol_title"),
            "protocol_version": protocol.get("protocol_version"),
            "materials": protocol.get("materials", []),
            "workflow": [
                {k: s.get(k) for k in ("step_id", "step_number", "title", "instructions",
                                       "time_estimate", "conditions", "reagents",
                                       "expected_observation", "checkpoint", "troubleshooting")}
                for s in protocol.get("workflow", []) or []
            ],
            "qc_checkpoints": protocol.get("qc_checkpoints", []),
            "failure_branches": protocol.get("failure_branches", []),
        }
        blob = json.dumps(slim, ensure_ascii=False)[:14000]
        if current_step:
            blob = f"CURRENT STEP: {current_step.get('step_id')} - {current_step.get('title')}\n" + blob
        return blob

    # ------------------------------------------------------------------ #
    # Offline heuristic answer
    # ------------------------------------------------------------------ #
    def _demo_answer(self, q: str, proto: Dict[str, Any],
                     current_step: Optional[Dict[str, Any]]) -> str:
        ql = q.lower().strip()
        wf = proto.get("workflow", []) or []

        # how long / days / time
        if any(k in ql for k in ("how long", "how many days", "how much time", "duration", "schedule")):
            n = len(wf)
            pauses = sum(1 for s in wf if s.get("pause_point"))
            return (f"This protocol has {n} steps with {pauses} safe stop(s). "
                    f"Open the **G. Plan** page to get a day-by-day schedule with "
                    f"hands-on vs walk-away time (set your hours/day there). "
                    f"(Offline mode — for a full conversational answer, run with DEMO_MODE=false.)")

        # how many steps / materials
        if "how many step" in ql:
            return f"There are {len(wf)} steps in {proto.get('protocol_title','this protocol')}."
        if "how many material" in ql or "what materials" in ql or "reagents do i need" in ql:
            mats = proto.get("materials", []) or []
            lines = [f"- {m.get('item','')}: {m.get('amount','')}" for m in mats[:20]]
            return "Materials:\n" + "\n".join(lines) if lines else "No materials listed."

        # step lookup: "step 3"
        m = re.search(r"step\s*0*(\d+)", ql)
        target = None
        if m:
            num = int(m.group(1))
            target = next((s for s in wf if s.get("step_number") == num), None)
        elif current_step and any(k in ql for k in ("this step", "current step", "here", "now")):
            target = current_step
        if target:
            return self._describe_step(target, ql)

        # troubleshooting keywords
        trouble = ("low yield", "no band", "background", "contamination", "viability",
                   "cell loss", "fragment", "smear", "degrad", "inhibit", "clog", "fail")
        if any(t in ql for t in trouble):
            return self._troubleshoot(proto, ql)

        # reagent / value lookup by name
        hit = self._find_reagent(proto, ql)
        if hit:
            return hit

        # generic
        return (
            "I can answer from this protocol. Try:\n"
            "- 'What do I do in step 3?' or 'spin speed for step 5?'\n"
            "- 'How much Buffer P2 do I add?'\n"
            "- 'What if I get low yield?'\n"
            "- 'How long will this take?' (then see the Plan page)\n\n"
            "_Offline mode: answers come from the loaded protocol. Set "
            "DEMO_MODE=false with an API key for full conversational Q&A (Haiku)._"
        )

    @staticmethod
    def _describe_step(s: Dict[str, Any], ql: str) -> str:
        cond = s.get("conditions", {}) or {}
        # targeted sub-questions
        if "speed" in ql or "rpm" in ql or "xg" in ql or "x g" in ql or "centrifug" in ql or "spin" in ql:
            return f"Step {s.get('step_number')} ({s.get('title')}) speed: **{cond.get('speed') or CONFIRM}**."
        if "temp" in ql or "°c" in ql or "degrees" in ql:
            return f"Step {s.get('step_number')} temperature: **{cond.get('temperature') or CONFIRM}**."
        if "how long" in ql or "time" in ql or "minutes" in ql:
            return f"Step {s.get('step_number')} time: **{s.get('time_estimate') or CONFIRM}**."
        if "volume" in ql or "how much" in ql:
            reag = s.get("reagents", []) or []
            if reag:
                return "Reagents for step {}:\n".format(s.get("step_number")) + \
                    "\n".join(f"- {r.get('item','')}: **{r.get('amount','')}**" for r in reag)
        # full description
        lines = [f"**Step {s.get('step_number')} — {s.get('title')}**"]
        if s.get("purpose"):
            lines.append(s["purpose"])
        for i in s.get("instructions", []) or []:
            lines.append(f"- {i}")
        meta = []
        if s.get("time_estimate"):
            meta.append(f"time {s['time_estimate']}")
        if cond.get("temperature"):
            meta.append(f"temp {cond['temperature']}")
        if cond.get("speed"):
            meta.append(f"speed {cond['speed']}")
        if meta:
            lines.append("_(" + ", ".join(meta) + ")_")
        if s.get("expected_observation"):
            lines.append(f"Expected: {s['expected_observation']}")
        if s.get("reagents"):
            lines.append("Reagents: " + ", ".join(f"{r.get('item','')} {r.get('amount','')}" for r in s["reagents"]))
        return "\n".join(lines)

    _STOP = {"what", "whats", "that", "this", "when", "with", "have", "does", "your",
             "from", "into", "about", "should", "would", "there", "here", "step", "steps"}

    @classmethod
    def _keywords(cls, ql: str) -> List[str]:
        return [w for w in re.split(r"[^a-z0-9]+", ql)
                if len(w) > 3 and w not in cls._STOP]

    @classmethod
    def _troubleshoot(cls, proto: Dict[str, Any], ql: str) -> str:
        kws = cls._keywords(ql)
        # always treat common failure words as keywords even if short
        for short in ("band", "loss", "low"):
            if short in ql and short not in kws:
                kws.append(short)
        out = []
        for s in proto.get("workflow", []) or []:
            for t in s.get("troubleshooting", []) or []:
                blob = (t.get("problem", "") + " " + " ".join(t.get("possible_causes", []))).lower()
                btok = set(re.split(r"[^a-z0-9]+", blob))
                if any(kw in btok for kw in kws):
                    out.append(f"- **{t.get('problem','')}** (step {s.get('step_number')}): "
                               f"{', '.join(t.get('actions', []))}")
        for b in proto.get("failure_branches", []) or []:
            ctok = set(re.split(r"[^a-z0-9]+", b.get("condition", "").lower()))
            if any(kw in ctok for kw in kws):
                out.append(f"- **{b.get('condition','')}**: "
                           f"{', '.join(b.get('recommended_modifications', []))} "
                           f"(steps {', '.join(b.get('step_ids_affected', []))})")
        # de-dup while preserving order
        seen, uniq = set(), []
        for o in out:
            if o not in seen:
                seen.add(o); uniq.append(o)
        if uniq:
            return "Here's what the protocol says:\n" + "\n".join(uniq[:8]) + \
                "\n\nIf it persists, use **E. Revision** to surgically adjust the affected step(s)."
        return ("I couldn't find a matching troubleshooting entry. You can flag the step in "
                "Bench Mode and trigger **E. Revision** to diagnose and fix it.")

    @staticmethod
    def _find_reagent(proto: Dict[str, Any], ql: str) -> Optional[str]:
        ql_tokens = set(t for t in re.split(r"[^a-z0-9]+", ql) if t)
        best, best_score = None, 0
        for m in proto.get("materials", []) or []:
            toks = [w for w in re.split(r"[^a-z0-9]+", m.get("item", "").lower()) if len(w) >= 2]
            # specific codes (p1/p2/n3/eb/b1...) and longer words score; generic
            # words like 'buffer' score less so 'P2' wins over a generic match.
            score = 0
            for t in toks:
                if t in ql_tokens:
                    score += 3 if (any(ch.isdigit() for ch in t) or len(t) > 6) else 1
            if score > best_score:
                best, best_score = m, score
        if best and best_score > 0:
            return (f"**{best.get('item','')}** — amount: **{best.get('amount','')}**"
                    + (f", vendor: {best.get('vendor','')}" if best.get('vendor') else "")
                    + (f", cat#: {best.get('catalog_number','')}" if best.get('catalog_number') else "")
                    + (f". Note: {best.get('notes','')}" if best.get('notes') else ""))
        return None
