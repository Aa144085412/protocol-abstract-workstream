"""
FillAgent
=========
Suggests values for a protocol's unconfirmed fields ("slots") so the user can
review, edit, and apply them interactively.

- DEMO_MODE=true (or no key) -> grounded suggestions from the bundled kit
  library (no guessing).
- DEMO_MODE=false -> model proposes values for each slot from the protocol
  context + standard published protocols. Routes by the ``fill`` role (so it can
  be pointed at GPT-4o via FILL_PROVIDER/FILL_MODEL).

Suggestions are ALWAYS shown to the user for confirmation/editing before being
applied — the model output is a draft, not an authority. Catalog numbers and
vendors are never suggested.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


class FillAgent(BaseAgent):
    name = "Fill Assistant"
    tier = "cheap"
    role = "fill"

    def suggest(self, protocol: Dict[str, Any], slots: List[Dict[str, str]],
                context: str = "", source_text: str = "") -> Dict[str, Any]:
        if not slots:
            return {"agent": self.name, "status": "success", "suggestions": {},
                    "mode": "none", "timestamp": utc_timestamp()}

        valid_all = {s["id"] for s in slots}
        if self.demo_mode:
            from tools.fill_slots import kit_suggestions, scan_vendors
            sugg = kit_suggestions(protocol, slots)
            # extract vendors that appear in the uploaded source document
            sugg.update(scan_vendors(source_text, protocol.get("materials", []) or []))
            sugg = {k: v for k, v in sugg.items() if k in valid_all}
            return {"agent": self.name, "status": "success", "suggestions": sugg,
                    "mode": "offline_kit_library",
                    "note": ("Offline: values from bundled kits + vendors scanned from your "
                             "uploaded document. For web-retrieved values, run live."),
                    "timestamp": utc_timestamp()}

        # Vendor slots are only fillable if the source document states the vendor;
        # otherwise they stay for manual entry (never invent a vendor).
        has_source = bool(source_text and source_text.strip())
        askable = [s for s in slots if (not s["id"].endswith(":vendor")) or has_source]
        if not askable:
            return {"agent": self.name, "status": "success", "suggestions": {},
                    "mode": "manual_only",
                    "note": "Remaining fields are vendor names — enter those manually.",
                    "timestamp": utc_timestamp()}

        # On Anthropic, web-search the manufacturer's published protocol; otherwise
        # use model knowledge (e.g. gpt-4o-mini knows standard kit values).
        use_web = self.provider == "anthropic"
        mats = ", ".join(m.get("item", "") for m in protocol.get("materials", []) or [])[:600]
        web_hint = ("Use web search to find the named kit/manufacturer's published protocol "
                    "and read the EXACT values from it." if use_web else
                    "Use your knowledge of the named kit's published standard protocol.")

        # Batch so large protocols (100+ fields) don't overflow one call.
        BATCH = 25
        merged: Dict[str, str] = {}
        proposals: Dict[str, Any] = {}
        sources: List[Any] = []
        valid_ids = {s["id"] for s in askable}
        for i in range(0, len(askable), BATCH):
            batch = askable[i:i + BATCH]
            prompt = self.load_prompt(
                "fill_agent.txt",
                protocol_title=protocol.get("protocol_title", ""),
                assay_type=protocol.get("assay_type", ""),
                materials=mats, web_hint=web_hint,
                context=(context.strip() or "none provided"),
                source_document=(source_text[:8000] if source_text else "none provided"),
                slots=json.dumps(batch, ensure_ascii=False),
            )
            try:
                raw = self.call(prompt, max_tokens=3000, temperature=0.1, json_mode=True,
                                tools=[WEB_SEARCH_TOOL] if use_web else None)
                data = self.extract_json(raw)
            except Exception:
                continue  # skip a failed batch; keep partial results
            for k, v in (data.get("suggestions", {}) or {}).items():
                if k not in valid_ids:
                    continue
                # New contract: each suggestion is a PROPOSAL OBJECT
                # {value, evidence_class, confidence, rationale, source_quote}.
                # Stay backward-compatible with a bare string value.
                if isinstance(v, dict):
                    val = v.get("value")
                    if val is None or not str(val).strip():
                        continue
                    ec = v.get("evidence_class", "ai_suggested")
                    quote = v.get("source_quote")
                    # a model may NOT self-certify source_confirmed without a quote;
                    # downgrade an unquoted "confirmed" claim to a suggestion.
                    if ec in ("source_confirmed", "kit_confirmed", "calculated") and not (quote and str(quote).strip()):
                        ec = "ai_suggested"
                    merged[k] = str(val)
                    proposals[k] = {"value": str(val), "evidence_class": ec,
                                    "confidence": v.get("confidence", 0.35),
                                    "rationale": v.get("rationale", ""),
                                    "source_quote": quote}
                elif isinstance(v, (str, int, float)) and str(v).strip():
                    merged[k] = str(v)
                    proposals[k] = {"value": str(v), "evidence_class": "ai_suggested",
                                    "confidence": 0.35, "rationale": "", "source_quote": None}
            sources.extend(data.get("sources", []) or [])

        # de-dup sources by url
        seen, uniq = set(), []
        for s in sources:
            key = s.get("url") if isinstance(s, dict) else str(s)
            if key and key not in seen:
                seen.add(key); uniq.append(s)

        if not merged:
            return {"agent": self.name, "status": "success", "suggestions": {},
                    "proposals": {}, "sources": uniq,
                    "mode": "live_web" if use_web else "live",
                    "note": ("No values returned. Try routing Fill to a stronger/known model "
                             "(e.g. FILL_PROVIDER=openai, FILL_MODEL=gpt-4o-mini), or use "
                             "'Auto-fill from kit(s)' for bundled exact values."),
                    "timestamp": utc_timestamp()}
        return {"agent": self.name, "status": "success", "suggestions": merged,
                "proposals": proposals, "sources": uniq,
                "mode": "live_web" if use_web else "live",
                "note": ("Values from the manufacturer's published protocol (web search) — "
                         "verify against your kit lot." if use_web else
                         "Model-proposed values — verify against your source."),
                "timestamp": utc_timestamp()}
