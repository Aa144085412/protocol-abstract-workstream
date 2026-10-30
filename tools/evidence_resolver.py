"""
evidence_resolver
=================
Find EXACT values for an uncertainty slot from genuine evidence — never a guess.
Covers the strict source/evidence hierarchy tiers 1-3 and 5:

  Tier 1  uploaded source protocol, exact quote            -> source_confirmed
  Tier 2  local verified kit library                       -> kit_confirmed
  Tier 3  deterministic calculator (inputs confirmed)      -> calculated
  Tier 5  reference / literature text, with quote          -> literature_supported

(Tiers 4 = user confirmation, and 6-7 = typical/AI suggestions, live elsewhere:
 value_promoter handles user confirmation; suggest_value handles 6-7.)

Every function is READ-ONLY: it returns *proposals*, it never writes to the
protocol. A proposal is shaped for ``value_promoter.auto_resolve``:

    {"value": "...", "proposed_status": "source_confirmed",
     "evidence": {"evidence_class", "source_name", "source_quote",
                  "source_location", "confidence"}}

No model calls here — pure-local, deterministic, auditable.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from . import fill_slots
from . import uncertainty_slots as us
from .protocol_check import _VOLUME, _MASS, _TEMP, _SPEED, _TIME

# expected_type -> the dimension regex(es) a real value must match
_TYPE_RE: Dict[str, List[Any]] = {
    "volume": [_VOLUME], "mass": [_MASS], "material_amount": [_VOLUME, _MASS],
    "temperature": [_TEMP], "speed": [_SPEED], "time": [_TIME],
}

_STOP = {"the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "by", "at",
         "step", "prepare", "perform", "using", "via", "from", "into", "as", "is", "be",
         "then", "add", "place", "this", "that", "each", "per", "min", "sec"}


def _proposal(value: str, status: str, source_name: str,
              quote: Optional[str] = None, loc: Optional[dict] = None,
              conf: float = 0.0) -> Dict[str, Any]:
    return {
        "value": str(value).strip(),
        "proposed_status": status,
        "evidence": {
            "evidence_class": status,
            "source_name": source_name,
            "source_quote": quote,
            "source_location": loc,
            "confidence": conf,
        },
    }


def _step(proto: Dict[str, Any], obj: Dict[str, Any]) -> Dict[str, Any]:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == obj.get("step_id"):
            return s
    return {}


def _context_terms(proto: Dict[str, Any], obj: Dict[str, Any]) -> set:
    """Distinctive words from the slot's step (title + instructions) used to make
    sure a regex match in free text is actually about THIS step."""
    s = _step(proto, obj)
    text = (str(s.get("title", "")) + " "
            + " ".join(str(i) for i in s.get("instructions", []) or [])).lower()
    toks = {t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 4 and t not in _STOP}
    # allow OPERATION words implied by the field type — but never UNIT tokens
    # (rpm/rcf/g), which would always sit next to the value and cause false matches.
    if obj.get("expected_type") == "speed":
        toks |= {"spin", "centrifuge", "centrifug", "pellet"}
    if obj.get("expected_type") == "temperature":
        toks |= {"incubate", "incubat", "heat", "ice", "chill", "warm"}
    return toks


# --------------------------------------------------------------------------- #
# Tier 1 / 5 — value quoted in a body of text
# --------------------------------------------------------------------------- #
def _find_in_text(text: str, proto: Dict[str, Any], obj: Dict[str, Any],
                  status: str, source_name: str, conf: float) -> List[Dict[str, Any]]:
    rxs = _TYPE_RE.get(obj.get("expected_type"))
    if not text or not rxs:
        return []
    ctx = _context_terms(proto, obj)
    out: List[Dict[str, Any]] = []
    seen = set()
    for rx in rxs:
        for m in rx.finditer(text):
            window = text[max(0, m.start() - 120): m.end() + 40]
            if not any(t in window.lower() for t in ctx):
                continue
            val = m.group(0).strip()
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(_proposal(
                val, status, source_name,
                quote=" ".join(window.split()),
                loc={"char": m.start(), "line": text[:m.start()].count("\n") + 1},
                conf=conf))
    return out


def from_source(proto, obj, source_text: str) -> List[Dict[str, Any]]:
    return _find_in_text(source_text, proto, obj, "source_confirmed", "uploaded:source", 0.95)


def from_reference(proto, obj, reference_text: str) -> List[Dict[str, Any]]:
    return _find_in_text(reference_text, proto, obj, "literature_supported", "reference", 0.6)


def from_parsed_docs(proto, obj, parsed_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in parsed_docs or []:
        text = d.get("text") or d.get("raw_text") or ""
        name = d.get("title") or d.get("protocol_title") or "parsed_doc"
        out += _find_in_text(text, proto, obj, "source_confirmed", f"uploaded:{name}", 0.9)
    return out


# --------------------------------------------------------------------------- #
# Tier 2 — local verified kit library
# --------------------------------------------------------------------------- #
def from_kit(proto, obj) -> List[Dict[str, Any]]:
    """If a best-matching library kit specifies this slot's value, return it as
    kit_confirmed. Applies the kit to a CLONE and reads the slot back."""
    try:
        from . import kit_lookup
    except Exception:
        return []
    query = (proto.get("protocol_title", "") + " " + proto.get("assay_type", "")).strip()
    if not query:
        return []
    try:
        hits = kit_lookup.search_kits(query)[:3]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for h in hits:
        try:
            clone = copy.deepcopy(proto)
            clone, _ = kit_lookup.apply_kit(clone, kit_lookup.get_kit(h["id"]))
            v = fill_slots.read_slot(clone, obj["slot_id"])
        except Exception:
            continue
        if v and us._looks_filled(v):
            out.append(_proposal(v, "kit_confirmed", f"kit:{h['id']}",
                                 quote=f"{h.get('name', h['id'])} library value",
                                 loc={"kit": h["id"]}, conf=0.85))
            break  # the top matching kit is enough
    return out


# --------------------------------------------------------------------------- #
# Tier 3 — deterministic calculation (hook)
# --------------------------------------------------------------------------- #
def from_calculation(proto, obj) -> List[Dict[str, Any]]:
    """Deterministic calculation tier. Only fires when a value is genuinely
    derivable from OTHER, already-confirmed inputs (e.g. PCR annealing temp from
    confirmed primer Tm, or an extension time from a confirmed amplicon length).

    Left as a conservative hook: it returns nothing until a calculator is wired
    for the specific protocol schema, because calculating from an *unconfirmed*
    input would smuggle a guess into a 'calculated' status. See pcr_design /
    mol_tools for the math to plug in here.
    """
    return []


# --------------------------------------------------------------------------- #
# Knowledge-sources tier (live, when a broker is supplied + enabled)
# --------------------------------------------------------------------------- #
def from_knowledge_sources(proto: Dict[str, Any], obj: Dict[str, Any],
                           broker: Any, context: Optional[dict] = None) -> List[Dict[str, Any]]:
    """Query the knowledge broker (PDF manuals, PubMed, …) for a value for this
    slot. Inert unless ``broker`` is supplied and enabled. Each retrieved record
    maps to a proposal via its own provenance (vendor_spec -> kit_confirmed, etc.)."""
    if broker is None or not getattr(broker, "enabled", False):
        return []
    try:
        import knowledge_sources as ks
    except Exception:
        return []
    etype = obj.get("expected_type")
    step = _step(proto, obj)
    query = (str(step.get("title", "")) + " " + str(obj.get("field_name", ""))).strip()
    ctx = {"expected_type": etype, **(context or {})}
    out: List[Dict[str, Any]] = []
    for ent in (ks.EntityType.PROTOCOL, ks.EntityType.REAGENT_KIT):
        for r in broker.retrieve_records(ent, query, context=ctx):
            if us.dimension_ok(etype, r.value) is False:
                continue
            ev = r.to_uncertainty_evidence()
            out.append({"value": r.value, "proposed_status": ev["evidence_class"],
                        "evidence": ev})
        if out:
            break
    return out


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
def resolve_slot(obj: Dict[str, Any], proto: Dict[str, Any],
                 sources: Optional[Dict[str, Any]] = None,
                 broker: Any = None) -> List[Dict[str, Any]]:
    """Return all evidence proposals for a slot, ordered best-tier first
    (source -> kit -> knowledge sources -> calc -> reference). Pure read-only.
    The knowledge-sources tier is inert unless a broker is supplied + enabled."""
    sources = sources or {}
    # vendor / catalog / reagent-identity are not resolvable by dimension scan
    if obj.get("expected_type") in us.NON_SUGGESTABLE_TYPES:
        return []
    proposals: List[Dict[str, Any]] = []
    proposals += from_source(proto, obj, sources.get("source_text", "") or "")
    proposals += from_parsed_docs(proto, obj, sources.get("parsed_docs", []) or [])
    proposals += from_kit(proto, obj)
    proposals += from_knowledge_sources(proto, obj, broker, sources.get("knowledge_context"))
    proposals += from_calculation(proto, obj)
    proposals += from_reference(proto, obj, sources.get("reference_text", "") or "")

    tier = {"source_confirmed": 0, "kit_confirmed": 1, "calculated": 2, "literature_supported": 3,
            "ai_suggested": 8}
    proposals.sort(key=lambda p: tier.get(p["proposed_status"], 9))
    return proposals


def best_proposal(obj: Dict[str, Any], proto: Dict[str, Any],
                  sources: Optional[Dict[str, Any]] = None,
                  broker: Any = None) -> Optional[Dict[str, Any]]:
    props = resolve_slot(obj, proto, sources, broker)
    return props[0] if props else None
