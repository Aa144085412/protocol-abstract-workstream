"""
standard_defaults
================
Loader + matcher for the curated standard-default catalog
(memory/standard_defaults.json): commonly-accepted STARTING values keyed by
operation, so the agent can prefill a sensible default with a basis + citation
instead of leaving a field blank.

These are generic suggestions (common practice / manufacturer guidance). They are
applied as suggested_default (typical_range) — never as if they came from the
user's source. A live knowledge-broker lookup for the user's specific kit
supersedes these. Pure-local, deterministic.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "memory", "standard_defaults.json")
_cache: Optional[List[Dict[str, Any]]] = None


def load_defaults() -> List[Dict[str, Any]]:
    global _cache
    if _cache is None:
        try:
            with open(_PATH, encoding="utf-8") as fh:
                _cache = json.load(fh).get("defaults", []) or []
        except Exception:
            _cache = []
    return _cache


def _score(entry: Dict[str, Any], text: str, expected_type: Optional[str],
           intent: Optional[str]) -> float:
    m = entry.get("match", {}) or {}
    score = 0.0
    if intent and intent in (m.get("intents") or []):
        score += 2.0
    for kw in m.get("keywords", []) or []:
        if kw in text:
            score += 1.0
    if expected_type and expected_type in (m.get("expected_types") or []):
        score += 1.0
    # an entry only matches if it shares the field dimension AND has a topical hit
    if expected_type and (m.get("expected_types") and expected_type not in m["expected_types"]):
        return 0.0
    has_topic = (intent and intent in (m.get("intents") or [])) or \
                any(kw in text for kw in (m.get("keywords") or []))
    return score if has_topic else 0.0


def match(step_text: str, expected_type: Optional[str] = None,
          intent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return catalog entries relevant to a step, best first."""
    text = str(step_text or "").lower()
    scored = []
    for e in load_defaults():
        s = _score(e, text, expected_type, intent)
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored]


def best(step_text: str, expected_type: Optional[str] = None,
         intent: Optional[str] = None) -> Optional[Dict[str, Any]]:
    hits = match(step_text, expected_type, intent)
    return hits[0] if hits else None
