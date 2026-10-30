"""
SearchAgent
===========
Finds protocols beyond the bundled kit library.

- DEMO_MODE=true  -> no internet. Falls back to searching the LOCAL kit library
  and returns matching bundled kits, with a note on how to enable live search.
- DEMO_MODE=false -> uses the Anthropic web_search server tool to find an
  authoritative published protocol, then extracts structured facts (Document
  Agent schema) plus source URLs. It must not invent values; unknowns are tagged
  ``[confirm with source protocol]``.

Routes to the CHEAP model (retrieval + structured extraction).
"""

from __future__ import annotations

from typing import Any, Dict

from .base_agent import BaseAgent, utc_timestamp

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


class SearchAgent(BaseAgent):
    name = "Search Agent"
    tier = "cheap"
    role = "search"

    def search(self, query: str) -> Dict[str, Any]:
        # Live web search uses the Anthropic web_search server tool. In demo mode,
        # or with a non-Anthropic provider (e.g. OpenAI), fall back to the local
        # kit library rather than letting a model guess protocol values.
        if self.demo_mode or self.provider != "anthropic":
            res = self._finalize(self.demo_response({"query": query}))
            if self.provider != "anthropic" and not self.demo_mode:
                res["message"] = ("Live web search currently requires the Anthropic provider. "
                                  "Showing local kit-library matches instead.")
            return res
        prompt = self.load_prompt("search_agent.txt", query=query)
        try:
            raw = self.call(
                prompt, max_tokens=4096, temperature=0.0, tools=[WEB_SEARCH_TOOL]
            )
            result = self.extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        return self._finalize(result)

    def _finalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        result.setdefault("agent", self.name)
        result.setdefault("status", "success")
        result.setdefault("timestamp", utc_timestamp())
        result["_meta"] = {
            "model": "demo" if self.demo_mode else self.model,
            "demo_mode": self.demo_mode,
            "tier": self.tier,
        }
        return result

    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Local-library fallback (no internet in demo mode).
        from tools.kit_lookup import search_kits

        q = payload.get("query", "")
        hits = search_kits(q)[:6]
        return {
            "agent": self.name,
            "status": "success",
            "mode": "demo_local_library",
            "query": q,
            "found": bool(hits),
            "message": (
                "DEMO mode: live internet search is disabled. These matches come "
                "from the local kit library. To search the web for new protocols, "
                "set DEMO_MODE=false and provide ANTHROPIC_API_KEY."
            ),
            "results": [
                {
                    "title": h["title"], "vendor": h.get("vendor", ""),
                    "assay_type": h.get("assay_type", ""), "kit_id": h["id"],
                    "source": "local kit library",
                }
                for h in hits
            ],
            "sources": [],
            "parsed_document": None,
        }
