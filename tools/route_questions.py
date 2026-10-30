"""
route_questions
==============
The ROUTE-uncertainty object layer — the sibling of uncertainty_slots, but for
"which workflow does this vague phrase mean?" instead of "what is this missing
value?".

A route_question is stored under ``proto["route_questions"][question_id]`` and
asks the user to choose between execution routes BEFORE the protocol is expanded.
Blocking questions (blocking_level == "must_ask_before_generation") gate protocol
generation; lower levels can branch or be filled later.

Every state change is provenance-logged (reusing provenance_tracker). No model
calls here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import provenance_tracker as prov

OBJECT_TYPE = "route_question"
BLOCKING = "must_ask_before_generation"
LEVELS = ("must_ask_before_generation", "can_branch_and_continue", "can_fill_later")
STATUSES = ("needs_user_choice", "selected", "dismissed")


def registry(proto: Dict[str, Any]) -> Dict[str, Any]:
    return proto.setdefault("route_questions", {})


def get(proto: Dict[str, Any], qid: str) -> Optional[Dict[str, Any]]:
    return registry(proto).get(qid)


def _next_qid(reg: Dict[str, Any]) -> str:
    n = 1
    while f"route:q{n:03d}" in reg:
        n += 1
    return f"route:q{n:03d}"


def _options_from_routes(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opts = []
    for r in routes or []:
        opts.append({
            "option_id": r.get("route_id", ""),
            "label": r.get("label", r.get("route_id", "")),
            "route_template": r.get("route_id", ""),
            "when_to_use": r.get("when_to_use", ""),
            "route_summary": r.get("route_summary", []),
            "creates_value_uncertainties": r.get("creates_value_uncertainties", []),
            "risk_if_wrong": r.get("risk_if_wrong", ""),
        })
    return opts


def add_question(proto: Dict[str, Any], *, surface_phrase: str, route_family: str,
                 ambiguity_type: str, question: str, why_needed: str,
                 blocking_level: str, options: List[Dict[str, Any]],
                 step_id: Optional[str] = None, match_confidence: float = 0.0,
                 source: str = "route_library", qid: Optional[str] = None) -> Dict[str, Any]:
    reg = registry(proto)
    qid = qid or _next_qid(reg)
    obj = {
        "question_id": qid,
        "object_type": OBJECT_TYPE,
        "status": "needs_user_choice",
        "surface_phrase": surface_phrase,
        "step_id": step_id,
        "route_family": route_family,
        "ambiguity_type": ambiguity_type,
        "question": question,
        "why_needed": why_needed,
        "blocking_level": blocking_level if blocking_level in LEVELS else "can_fill_later",
        "match_confidence": match_confidence,
        "options": options,
        "selected_option": None,
        "source": source,
        "audit_trail": [],
    }
    prov.append(obj, f"system:{source}", "created", None, "needs_user_choice",
                note=f"route ambiguity: {surface_phrase}")
    reg[qid] = obj
    return obj


def build_from_hits(proto: Dict[str, Any], hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create route_question objects from route_library detection hits.
    Idempotent per route_family: a family already present is not duplicated."""
    existing = {o.get("route_family") for o in registry(proto).values()}
    made = []
    for h in hits:
        if h.get("route_family") in existing:
            continue
        obj = add_question(
            proto,
            surface_phrase=h.get("surface_phrase", ""),
            route_family=h.get("route_family", ""),
            ambiguity_type=h.get("ambiguity_type", ""),
            question=h.get("route_question", "Which route applies here?"),
            why_needed=h.get("why_matched", ""),
            blocking_level=h.get("blocking_level", "can_fill_later"),
            options=_options_from_routes(h.get("routes", [])),
            step_id=h.get("step_id"),
            match_confidence=h.get("match_confidence", 0.0),
            source=h.get("source", "route_library"),
        )
        existing.add(obj["route_family"])
        made.append(obj)
    return made


def select_option(proto: Dict[str, Any], qid: str, option_id: str, user_email: str) -> Dict[str, Any]:
    obj = registry(proto)[qid]
    valid = {o["option_id"] for o in obj.get("options", [])}
    if option_id not in valid:
        raise ValueError(f"unknown option '{option_id}' for {qid}")
    frm = obj["status"]
    obj["selected_option"] = option_id
    obj["status"] = "selected"
    prov.append(obj, f"user:{user_email}", "selected", frm, "selected", option_id,
                note=f"chose route '{option_id}'")
    return obj


def dismiss(proto: Dict[str, Any], qid: str, user_email: str) -> Dict[str, Any]:
    obj = registry(proto)[qid]
    frm = obj["status"]
    obj["status"] = "dismissed"
    prov.append(obj, f"user:{user_email}", "dismissed", frm, "dismissed",
                note="not route-ambiguous / not applicable")
    return obj


def selected_route(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if obj.get("selected_option") is None:
        return None
    for o in obj.get("options", []):
        if o["option_id"] == obj["selected_option"]:
            return o
    return None


def blocking_unanswered(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Must-ask route questions the user has not yet resolved."""
    return [o for o in registry(proto).values()
            if o.get("blocking_level") == BLOCKING and o.get("status") == "needs_user_choice"]


def safe_to_generate(proto: Dict[str, Any]) -> bool:
    """True when no blocking route question is still awaiting a user choice."""
    return not blocking_unanswered(proto)


def summary(proto: Dict[str, Any]) -> Dict[str, Any]:
    reg = registry(proto)
    return {
        "total": len(reg),
        "needs_choice": sum(1 for o in reg.values() if o["status"] == "needs_user_choice"),
        "selected": sum(1 for o in reg.values() if o["status"] == "selected"),
        "blocking_open": len(blocking_unanswered(proto)),
        "safe_to_generate": safe_to_generate(proto),
    }
