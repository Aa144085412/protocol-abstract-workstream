"""
SlotTriageAgent
==============
A decision-tree agent that decides, for each uncertainty flag, whether the field
actually APPLIES to its step — so flags that are schema artifacts (a centrifuge
speed on a plating step) can be retired with a reason instead of being asked of
the human. It decides APPLICABILITY only; it never invents a value.

Routing: cheap model (a classification task). DEMO/offline falls back to the
deterministic decision tree in tools/slot_triage, so the behavior is auditable
and works with no API key. Batches all slots into ONE call.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, utc_timestamp
from tools import slot_triage


class SlotTriageAgent(BaseAgent):
    name = "Slot Triage Agent"
    tier = "cheap"
    role = "triage"

    def triage(self, protocol: Dict[str, Any],
               slots: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Return {"decisions": {slot_id: {decision, reason, confidence, auto_safe}}}.
        decision in {applicable, not_applicable}."""
        # candidate slots = unresolved condition slots (what the tree triages)
        triaged = slot_triage.triage_protocol(protocol, only_unresolved=True)
        if self.demo_mode or not triaged:
            return self._demo(triaged)

        payload = [{"slot_id": t["slot_id"], "step_id": t["step_id"],
                    "field": t["expected_type"],
                    "step": self._step_brief(protocol, t["step_id"])} for t in triaged]
        prompt = self.load_prompt("slot_triage_agent.txt",
                                  slots=json.dumps(payload, ensure_ascii=False)[:8000])
        try:
            data = self.extract_json(self.call(prompt, max_tokens=2000, temperature=0.0,
                                               json_mode=True))
        except Exception:
            return self._demo(triaged)   # fall back to the deterministic tree
        decisions = {}
        valid = {t["slot_id"] for t in triaged}
        for d in data.get("decisions", []) or []:
            sid = d.get("slot_id")
            if sid not in valid:
                continue
            decision = d.get("decision", "applicable")
            decisions[sid] = {
                "decision": "not_applicable" if decision == "not_applicable" else "applicable",
                "reason": d.get("reason", ""),
                "confidence": float(d.get("confidence", 0.6)),
                # only auto-apply a model N/A when it is confident
                "auto_safe": decision == "not_applicable" and float(d.get("confidence", 0)) >= 0.8,
            }
        # keep deterministic decisions for any slot the model skipped
        for t in triaged:
            decisions.setdefault(t["slot_id"], {k: t[k] for k in
                                                ("decision", "reason", "confidence", "auto_safe")})
        return {"agent": self.name, "status": "success", "mode": "live",
                "decisions": decisions, "timestamp": utc_timestamp()}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _step_brief(protocol, step_id):
        for s in protocol.get("workflow", []) or []:
            if s.get("step_id") == step_id:
                return {"title": s.get("title", ""),
                        "instructions": (s.get("instructions", []) or [])[:4]}
        return {}

    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._demo(payload.get("triaged", []))

    def _demo(self, triaged: List[Dict[str, Any]]) -> Dict[str, Any]:
        decisions = {t["slot_id"]: {k: t[k] for k in
                                    ("decision", "reason", "confidence", "auto_safe")}
                     for t in triaged}
        return {"agent": self.name, "status": "success", "mode": "offline",
                "decisions": decisions, "timestamp": utc_timestamp()}
