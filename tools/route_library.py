"""
route_library
=============
Deterministic, local knowledge base + detector for ROUTE uncertainty — the kind
where one vague bench phrase ("plate cells", "clean up reaction") hides several
real execution routes. This is distinct from VALUE uncertainty (a missing
volume/speed), which lives in uncertainty_slots.

This module is the auditable offline layer: it loads memory/route_library.json
and detects route-ambiguous phrases by phrase substring + verb/noun
co-occurrence (a light semantic match, not just exact keywords). The live
ContextDigestAgent does the richer semantic mapping; in DEMO mode it falls back
to this detector so the stage always works offline.

No model calls here.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

_MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")
_LIBRARY_PATH = os.path.join(_MEMORY_DIR, "route_library.json")

_STOP = {"the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "by", "at",
         "into", "from", "then", "this", "that", "my", "our", "your", "tomorrow",
         "today", "please", "some", "any"}

_cache: Optional[Dict[str, Any]] = None


def load_library() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            with open(_LIBRARY_PATH, encoding="utf-8") as fh:
                _cache = json.load(fh)
        except Exception:
            _cache = {"version": 0, "route_families": []}
    return _cache


def families() -> List[Dict[str, Any]]:
    return load_library().get("route_families", []) or []


def get_family(route_family: str) -> Optional[Dict[str, Any]]:
    for f in families():
        if f.get("route_family") == route_family:
            return f
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", _norm(text)) if t and t not in _STOP}


def detect_in_text(text: str, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
    """Return route-ambiguity hits for a phrase / request / step text.

    Each hit: {surface_phrase, route_family, ambiguity_type, route_question,
               blocking_level, match_confidence, why_matched, routes}.
    Conservative: requires either an example-phrase substring (high confidence)
    or a family verb AND noun co-occurring (medium), so plain executable steps
    ('incubate at 37C', 'vortex') do not trigger."""
    norm = _norm(text)
    toks = _tokens(text)
    hits: List[Dict[str, Any]] = []
    for fam in families():
        conf = 0.0
        why = ""
        # 1) exact-ish: a known surface phrase appears verbatim
        for ph in fam.get("example_phrases", []):
            if _norm(ph) in norm:
                conf, why = 0.9, f"matched known phrase '{ph}'"
                break
        # 2) semantic-ish: a family action verb AND a family object noun co-occur
        if conf == 0.0:
            m = fam.get("match", {}) or {}
            verbs = set(m.get("verbs", []))
            nouns = set(m.get("nouns", []))
            v_hit = toks & verbs
            n_hit = toks & nouns
            # require TWO distinct trigger tokens, so an ambiguous word that is both
            # a verb and a noun (e.g. "plate" the vessel in "incubate the plate")
            # cannot satisfy both roles by itself.
            if v_hit and n_hit and len(v_hit | n_hit) >= 2:
                verb_tok = sorted(v_hit - n_hit) or sorted(v_hit)
                noun_tok = sorted(n_hit - v_hit) or sorted(n_hit)
                conf = 0.6
                why = f"action '{verb_tok[0]}' + object '{noun_tok[0]}' imply {fam['route_family']}"
        if conf >= min_confidence:
            hits.append({
                "surface_phrase": _norm(text)[:120],
                "route_family": fam["route_family"],
                "ambiguity_type": fam.get("ambiguity_type", ""),
                "route_question": fam.get("route_question", ""),
                "blocking_level": fam.get("blocking_level", "can_fill_later"),
                "match_confidence": conf,
                "why_matched": why,
                "routes": fam.get("routes", []),
            })
    hits.sort(key=lambda h: h["match_confidence"], reverse=True)
    return hits


def detect_in_protocol(proto: Dict[str, Any], min_confidence: float = 0.5) -> List[Dict[str, Any]]:
    """Scan a protocol's step titles + instructions for route-ambiguous phrases.
    De-duplicates by (route_family) keeping the first/strongest step hit, and
    attaches step_id."""
    seen_families = set()
    out: List[Dict[str, Any]] = []
    for s in proto.get("workflow", []) or []:
        text = (str(s.get("title", "")) + ". "
                + " ".join(str(i) for i in s.get("instructions", []) or []))
        for h in detect_in_text(text, min_confidence):
            if h["route_family"] in seen_families:
                continue
            seen_families.add(h["route_family"])
            h = dict(h)
            h["step_id"] = s.get("step_id")
            h["surface_phrase"] = str(s.get("title", "")) or h["surface_phrase"]
            out.append(h)
    return out
