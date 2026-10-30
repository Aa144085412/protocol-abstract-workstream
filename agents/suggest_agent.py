"""
SuggestAgent
============
Turns a missing/unconfirmed value into a SUGGESTED TYPICAL RANGE with a short rationale
— never a single gold-standard number. e.g. "spin mammalian cells 300–500 × g (gentler
200–300 × g right after trypsin); bacteria 3000–4000 × g". Backed by a local knowledge
base (tools/typical_values) so it works offline; live, it can refine/extend ranges and is
routable to whichever model you prefer for biology (role = "suggest", e.g.
SUGGEST_PROVIDER=openai SUGGEST_MODEL=gpt-4o).

Output is explicitly advisory: ranges to confirm, not values read from your protocol.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp
from tools.typical_values import suggest_for_text, suggest_for_query


class SuggestAgent(BaseAgent):
    name = "Value Suggester"
    tier = "cheap"
    role = "suggest"

    def suggest_step(self, step: Dict[str, Any], context: str = "",
                     level: str = "intermediate") -> Dict[str, Any]:
        text = (str(step.get("title", "")) + ". "
                + " ".join(str(i) for i in step.get("instructions", []) or []))
        base = suggest_for_text(text)
        if self.demo_mode:
            return {"agent": self.name, "status": "success", "mode": "offline",
                    "suggestions": base,
                    "note": "Typical ranges from common practice — confirm against your protocol.",
                    "timestamp": utc_timestamp()}
        return self._live(text, context, level, base)

    def suggest_query(self, query: str, context: str = "",
                      level: str = "intermediate") -> Dict[str, Any]:
        base = suggest_for_query(query)
        if self.demo_mode:
            return {"agent": self.name, "status": "success", "mode": "offline",
                    "suggestions": base, "timestamp": utc_timestamp()}
        return self._live(query, context, level, base)

    # ------------------------------------------------------------------ #
    def _live(self, text: str, context: str, level: str,
              base: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt = self.load_prompt(
            "suggest_agent.txt",
            operation=text[:2000],
            context=(context.strip() or "none"),
            level=level,
            baseline=json.dumps(base, ensure_ascii=False)[:3000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=1800, temperature=0.2, json_mode=True))
            model_sugg = data.get("suggestions") if isinstance(data, dict) else None
            if not isinstance(model_sugg, list):
                model_sugg = []
            # PROVENANCE: keep the auditable built-in ranges (source="reference") AND add
            # model proposals as a clearly separate, "verify" tier — never silently swap
            # a traceable rule for a model guess.
            have = {str(s.get("label", "")).lower() for s in base}
            merged = list(base)
            for s in model_sugg:
                if str(s.get("label", "")).lower() in have:
                    continue
                s["confidence"] = "suggestion"
                s["source"] = "ai"
                merged.append(s)
            return {"agent": self.name, "status": "success", "mode": "live",
                    "suggestions": merged,
                    "sources": (data.get("sources") if isinstance(data, dict) else None) or [],
                    "note": "Built-in reference ranges + AI-proposed additions (tagged) — "
                            "confirm against your source protocol / kit.",
                    "timestamp": utc_timestamp()}
        except Exception as exc:  # noqa: BLE001
            # fall back to the deterministic knowledge base
            return {"agent": self.name, "status": "success", "mode": "offline",
                    "suggestions": base,
                    "note": f"Live suggester unavailable ({exc}); showing built-in typical ranges.",
                    "timestamp": utc_timestamp()}
