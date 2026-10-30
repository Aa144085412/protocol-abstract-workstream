"""
LiteratureAgent
===============
Background literature search + summarization for a project. Given the experiment's
targets, assay, and context, it finds relevant published work and returns curated
citations with short summaries and a synthesis of the background — so a lab member
can get up to speed on the science.

IMPORTANT: this agent does NOT generate hypotheses or propose experiments. It only
searches and summarizes existing literature.

- DEMO_MODE / non-Anthropic provider: no web access; summarizes from the project's
  own reference documents and returns a clear note on enabling live search.
- Live (Anthropic): uses the web_search server tool to find authoritative papers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


class LiteratureAgent(BaseAgent):
    name = "Literature Agent"
    tier = "cheap"
    role = "literature"

    def review_literature(self, topic: str, context: Dict[str, Any] | None = None,
                          source_docs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        context = context or {}
        source_docs = source_docs or []
        if self.demo_mode or self.provider != "anthropic":
            res = self._demo(topic, context, source_docs)
            if self.provider != "anthropic" and not self.demo_mode:
                res["note"] = ("Live literature search needs the Anthropic provider. "
                               "Summarized from this project's reference documents instead.")
            return res
        prompt = self.load_prompt(
            "literature_agent.txt", topic=topic,
            context=json.dumps(context, ensure_ascii=False)[:2000],
            local_docs=json.dumps(
                [{"title": d.get("title", ""), "summary": (d.get("text", "") or "")[:600]}
                 for d in source_docs[:8]], ensure_ascii=False)[:6000],
        )
        try:
            raw = self.call(prompt, max_tokens=4096, temperature=0.1, tools=[WEB_SEARCH_TOOL])
            data = self.extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        data.setdefault("agent", self.name)
        data.setdefault("status", "success")
        data["mode"] = "live"
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def _demo(self, topic: str, context: Dict[str, Any],
              source_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        lit = [d for d in source_docs if d.get("doc_type") in ("literature", "reference", "background")]
        papers = [{"title": d.get("title", ""), "source": "project reference doc",
                   "summary": (d.get("text", "") or "")[:300], "url": ""}
                  for d in lit[:10]]
        themes = sorted({t for d in lit for t in _keywords(d.get("title", ""))})[:12]
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "topic": topic,
            "summary": (
                f"Offline literature view for '{topic}': drawn from {len(papers)} project "
                "reference document(s). Enable live search (DEMO_MODE=false + Anthropic key) "
                "to pull current external papers with citations and links."),
            "papers": papers,
            "themes": themes,
            "note": "Offline mode — no external web search performed.",
            "timestamp": utc_timestamp(),
        }


def _keywords(s: str) -> List[str]:
    import re
    stop = {"the", "and", "for", "with", "from", "this", "that", "using", "single", "cell"}
    return [w for w in re.split(r"[^A-Za-z0-9]+", (s or "").lower())
            if len(w) > 3 and w not in stop]
