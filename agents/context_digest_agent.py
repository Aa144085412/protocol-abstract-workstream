"""
ContextDigestAgent
==================
Route discovery BEFORE protocol generation. It does NOT write the final protocol.
Its job is to understand what a messy protocol / vague request could MEAN: it
detects procedural-shortcut phrases ("plate cells", "clean up reaction") that
hide multiple execution routes, proposes those routes, and asks the minimum
user-facing question needed to choose — separating ROUTE uncertainty from VALUE
uncertainty.

Routing: strong model (semantic reasoning). DEMO_MODE / offline falls back to the
deterministic tools/route_library detector so the stage always works without a key.
It never silently selects a route.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, utc_timestamp
from tools import route_library


class ContextDigestAgent(BaseAgent):
    name = "Context Digest Agent"
    tier = "strong"
    role = "digest"

    def digest(self, text: str = "", protocol: Optional[Dict[str, Any]] = None,
               context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return route-discovery output. `text` is a free request/phrase; or pass
        a parsed/draft `protocol` to scan its steps. Output shape:
          {protocol_goal, known_context, route_questions[],
           value_uncertainties_to_fill_later[], safe_to_generate_protocol_now,
           minimal_user_questions[]}"""
        protocol = protocol or {}
        context = context or {}
        if self.demo_mode:
            return self._demo(text, protocol, context)

        # Live: give the model the request + the library's known families as
        # grounded candidates, but let it map meaning semantically.
        lib = [{"route_family": f["route_family"], "ambiguity_type": f.get("ambiguity_type"),
                "route_question": f.get("route_question"),
                "blocking_level": f.get("blocking_level"),
                "routes": [{"route_id": r["route_id"], "label": r.get("label")}
                           for r in f.get("routes", [])]}
               for f in route_library.families()]
        steps = [{"step_id": s.get("step_id"), "title": s.get("title"),
                  "instructions": s.get("instructions")}
                 for s in protocol.get("workflow", []) or []]
        prompt = self.load_prompt(
            "context_digest_agent.txt",
            request=(text or "(none — use the protocol steps)"),
            protocol_steps=json.dumps(steps, ensure_ascii=False)[:8000],
            known_context=json.dumps(context, ensure_ascii=False)[:2000],
            route_library=json.dumps(lib, ensure_ascii=False)[:6000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=3500, temperature=0.1,
                                               json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        data.setdefault("agent", self.name)
        data.setdefault("status", "success")
        data["mode"] = "live"
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._demo(payload.get("text", ""), payload.get("protocol", {}),
                          payload.get("context", {}))

    def _demo(self, text: str, protocol: Dict[str, Any],
              context: Dict[str, Any]) -> Dict[str, Any]:
        if protocol.get("workflow"):
            hits = route_library.detect_in_protocol(protocol)
        else:
            hits = route_library.detect_in_text(text)

        route_questions: List[Dict[str, Any]] = []
        minimal: List[str] = []
        for h in hits:
            rq = {
                "question_id": "",  # assigned when stored via route_questions.build_from_hits
                "ambiguous_phrase": h.get("surface_phrase", ""),
                "step_id": h.get("step_id"),
                "ambiguity_type": h.get("ambiguity_type", ""),
                "route_family": h.get("route_family", ""),
                "question": h.get("route_question", ""),
                "why_needed": h.get("why_matched", ""),
                "blocking_level": h.get("blocking_level", "can_fill_later"),
                "match_confidence": h.get("match_confidence", 0.0),
                "options": [{"option_id": r.get("route_id", ""), "label": r.get("label", ""),
                             "when_to_use": r.get("when_to_use", ""),
                             "route_summary": r.get("route_summary", []),
                             "risk_if_wrong": r.get("risk_if_wrong", "")}
                            for r in h.get("routes", [])],
                "recommended_default": None,
                "source": "route_library",
            }
            route_questions.append(rq)
            if h.get("blocking_level") == "must_ask_before_generation":
                minimal.append(h.get("route_question", ""))

        safe = not any(rq["blocking_level"] == "must_ask_before_generation"
                       for rq in route_questions)
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "protocol_goal": (text or protocol.get("protocol_title", "")).strip(),
            "known_context": context or {},
            "route_questions": route_questions,
            "value_uncertainties_to_fill_later": [],
            "safe_to_generate_protocol_now": safe,
            "minimal_user_questions": minimal,
            "note": "Offline route discovery from the local route library. Run live "
                    "(DEMO_MODE=false) for richer semantic matching.",
            "timestamp": utc_timestamp(),
        }
