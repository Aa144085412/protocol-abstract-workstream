"""
readiness
=========
Compute a protocol's *readiness* (a confidence proxy) from objective signals, so
the displayed confidence rises as the user fills values, adds controls/QC, and
reconciles conflicts. Pure-local, no model.

Returns a 0-100 score, a level (low/medium/high), the contributing factors
(met / unmet with detail), and concrete tips to raise it.
"""

from __future__ import annotations

from typing import Any, Dict, List

CONFIRM = "[confirm with source protocol]"


def _count_confirm(obj: Any) -> int:
    if isinstance(obj, str):
        return 1 if CONFIRM in obj else 0
    if isinstance(obj, dict):
        return sum(_count_confirm(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_confirm(v) for v in obj)
    return 0


# --------------------------------------------------------------------------- #
# Factor 1 — "Exact values filled" (40 pts)
# --------------------------------------------------------------------------- #
def _factor1_legacy(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Original formula: linear decay on the count of CONFIRM placeholders.
    Used for protocols that have not been migrated to the uncertainty registry."""
    n_confirm = _count_confirm(proto)
    pct = max(0.0, 1.0 - min(n_confirm, 30) / 30.0)
    pts = round(40 * pct)
    return {
        "label": "Exact values filled", "ok": n_confirm == 0, "points": pts, "max": 40,
        "detail": ("All quantitative values are filled." if n_confirm == 0
                   else f"{n_confirm} value(s) still '[confirm with source protocol]'."),
        "tip": "Open F. Fill details (AI-assisted fill, kit auto-fill, or manual) to enter exact volumes/speeds/times.",
    }


# per-status credit (kept local to avoid an import cycle with uncertainty_slots)
_STATUS_WEIGHT = {
    "source_confirmed": 1.0, "kit_confirmed": 1.0, "calculated": 1.0, "user_confirmed": 1.0,
    "literature_supported": 0.5, "typical_range": 0.2, "ai_suggested": 0.05,
    "unresolved": 0.0, "conflict": 0.0, "not_applicable": 0.0,
}
_CONFIRMED_STATUSES = {"source_confirmed", "kit_confirmed", "calculated", "user_confirmed"}
_CONFLICT_PENALTY = {"high": 6, "medium": 4, "low": 2}


def _factor1_evidence(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Evidence-weighted completeness. Confirmed values earn full credit; AI/typical
    suggestions earn little; conflicts and high-risk gaps subtract. Bins are
    unchanged, so an all-AI-suggested protocol stays 'low'."""
    reg = proto.get("uncertainty", {}) or {}
    counted = [o for o in reg.values() if o.get("status") != "not_applicable"]
    if not counted:
        return {"label": "Exact values filled", "ok": True, "points": 40, "max": 40,
                "detail": "No quantitative slots to confirm.", "tip": ""}

    credit = sum(_STATUS_WEIGHT.get(o.get("status"), 0.0) for o in counted)
    base = 40.0 * credit / len(counted)

    penalty = 0
    for o in counted:
        st, risk = o.get("status"), o.get("risk_level", "medium")
        if st == "conflict":
            penalty += _CONFLICT_PENALTY.get(risk, 4)
        elif st == "unresolved" and risk == "high":
            penalty += 2
        elif st in ("ai_suggested", "typical_range") and risk == "high":
            penalty += 1

    pts = max(0, round(base - penalty))
    n_conf = sum(1 for o in counted if o.get("status") in _CONFIRMED_STATUSES)
    n_guess = sum(1 for o in counted if o.get("status") in ("ai_suggested", "typical_range"))
    n_conflict = sum(1 for o in counted if o.get("status") == "conflict")
    n_unres = sum(1 for o in counted if o.get("status") == "unresolved")
    ok = n_conf == len(counted)
    detail = (f"{n_conf}/{len(counted)} evidence-confirmed; {n_guess} AI/typical only; "
              f"{n_unres} unresolved; {n_conflict} conflict(s).")
    return {"label": "Exact values filled", "ok": ok, "points": pts, "max": 40,
            "detail": detail,
            "tip": "Confirm AI/typical suggestions against your source, kit, calculator, or bench to earn credit."}


_PARTIAL_STATUSES = {"literature_supported", "typical_range", "ai_suggested"}


def completeness(proto: Dict[str, Any]) -> Dict[str, Any]:
    """Bench-readiness / fill completeness — counts EVERY filled value (confirmed OR
    suggested) so a fully-filled protocol can read 'ready to start'. Distinct from
    compute_readiness, which credits evidence only. >=90% (and no conflicts) => ready,
    with the count of still-to-confirm values surfaced for verification at the bench."""
    reg = proto.get("uncertainty") or {}
    counted = [o for o in reg.values() if o.get("status") != "not_applicable"]
    if not counted:
        return {"score": 100, "filled": 0, "total": 0, "confirmed": 0,
                "to_confirm": 0, "conflicts": 0, "ready": True}
    filled = sum(1 for o in counted if o.get("status") not in ("unresolved", "conflict"))
    confirmed = sum(1 for o in counted if o.get("status") in _CONFIRMED_STATUSES)
    conflicts = sum(1 for o in counted if o.get("status") == "conflict")
    score = round(100 * filled / len(counted))
    return {"score": score, "filled": filled, "total": len(counted), "confirmed": confirmed,
            "to_confirm": len(counted) - confirmed, "conflicts": conflicts,
            "ready": score >= 90 and conflicts == 0}


def compute_readiness(proto: Dict[str, Any]) -> Dict[str, Any]:
    wf = proto.get("workflow", []) or []
    qc = proto.get("qc_checkpoints", []) or []
    mats = proto.get("materials", []) or []
    decisions = proto.get("decision_points", []) or []
    branches = proto.get("failure_branches", []) or []
    oqs = proto.get("open_questions_for_human", []) or []

    factors: List[Dict[str, Any]] = []
    score = 0.0

    # 1. Quantitative completeness (40) — evidence-weighted when an uncertainty
    #    registry is present, else the legacy placeholder-count formula.
    f1 = _factor1_evidence(proto) if proto.get("uncertainty") else _factor1_legacy(proto)
    score += f1["points"]
    factors.append(f1)

    # 2. QC quality (20)
    if qc:
        good = sum(1 for q in qc if q.get("pass_criteria") and q.get("recommended_action_on_fail"))
        pts = 20 * (good / len(qc))
        ok = good == len(qc)
        detail = f"{good}/{len(qc)} QC checkpoints have pass criteria + an action on fail."
    else:
        pts, ok, detail = 0, False, "No QC checkpoints defined."
    score += pts
    factors.append({"label": "QC gates with pass/fail criteria", "ok": ok, "points": round(pts),
                    "max": 20, "detail": detail,
                    "tip": "Use '🧠 Suggest design improvements' to add QC checkpoints with criteria."})

    # 3. Controls (15)
    blob = " ".join([
        " ".join(str(s.get("title", "")) for s in wf),
        " ".join(o for o in oqs),
        " ".join(opt for d in decisions for opt in d.get("options", [])),
    ]).lower()
    has_controls = "control" in blob or "no-template" in blob or "untransduced" in blob or "mock" in blob
    score += 15 if has_controls else 0
    factors.append({"label": "Experimental controls included", "ok": has_controls,
                    "points": 15 if has_controls else 0, "max": 15,
                    "detail": "Controls referenced." if has_controls else "No explicit controls found.",
                    "tip": "Use '🧠 Suggest design improvements' to add the right controls for your assay."})

    # 4. Failure branches (10)
    score += 10 if branches else 0
    factors.append({"label": "Failure / troubleshooting logic", "ok": bool(branches),
                    "points": 10 if branches else 0, "max": 10,
                    "detail": f"{len(branches)} failure branch(es)." if branches else "No failure branches.",
                    "tip": "Add failure branches via design improvements, or run E. Revision when a step fails."})

    # 5. Decision points (5)
    score += 5 if decisions else 0
    factors.append({"label": "Decision points", "ok": bool(decisions),
                    "points": 5 if decisions else 0, "max": 5,
                    "detail": f"{len(decisions)} decision point(s)." if decisions else "No decision points.",
                    "tip": "Add go/no-go decisions at key checkpoints."})

    # 6. Human-review coverage (5)
    flagged = any(s.get("human_review_required") for s in wf)
    score += 5 if flagged else 0
    factors.append({"label": "Human-review flags on critical steps", "ok": flagged,
                    "points": 5 if flagged else 0, "max": 5,
                    "detail": "Critical steps flagged." if flagged else "No human-review flags.",
                    "tip": "Flag steps that change sample handling/incubation/concentration/cleanup."})

    # 7. Materials amounts (5)
    if mats:
        filled = sum(1 for m in mats if m.get("amount") and CONFIRM not in str(m.get("amount")))
        pts = 5 * (filled / len(mats))
        ok = filled == len(mats)
        detail = f"{filled}/{len(mats)} materials have amounts."
    else:
        pts, ok, detail = 0, False, "No materials listed."
    score += pts
    factors.append({"label": "Material amounts specified", "ok": ok, "points": round(pts),
                    "max": 5, "detail": detail,
                    "tip": "Fill material amounts on the Fill page or via kit auto-fill."})

    score = round(score)
    level = "high" if score >= 75 else ("medium" if score >= 45 else "low")
    tips = [f["tip"] for f in factors if not f["ok"]]
    return {"score": score, "level": level, "factors": factors, "tips": tips}
