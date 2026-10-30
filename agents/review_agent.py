"""
ReviewAgent
===========
Critiques a generated protocol for completeness, safety, missing controls,
missing QC, and over-invention (values that should have been marked uncertain).
Safety-critical -> routes to the STRONG model. Returns an approve/revise/reject
decision with itemised findings.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"


class ReviewAgent(BaseAgent):
    name = "Review Agent"
    tier = "strong"
    role = "review"

    def review(self, protocol: Dict[str, Any], parsed_document: Dict[str, Any] | None = None) -> Dict[str, Any]:
        prompt = self.load_prompt(
            "review_agent.txt",
            protocol=protocol,
            parsed_document=parsed_document or {},
        )
        return self.run(
            prompt,
            payload={"protocol": protocol, "parsed_document": parsed_document or {}},
            max_tokens=3072,
            temperature=0.1,
        )

    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        proto = payload.get("protocol", {}) or {}
        workflow = proto.get("workflow", []) or []
        qc = proto.get("qc_checkpoints", []) or []
        materials = proto.get("materials", []) or []

        findings: List[Dict[str, str]] = []

        # --- completeness checks ---
        if not workflow:
            findings.append({"severity": "high", "category": "completeness",
                             "issue": "Protocol has no workflow steps."})
        if not qc:
            findings.append({"severity": "high", "category": "missing_qc",
                             "issue": "No QC checkpoints defined; add at least a yield/purity gate."})
        if not materials:
            findings.append({"severity": "medium", "category": "completeness",
                             "issue": "Materials list is empty."})
        if not proto.get("preconditions", {}).get("safety_notes"):
            findings.append({"severity": "medium", "category": "safety",
                             "issue": "No safety_notes present; add SDS/handling notes for hazardous buffers."})

        # --- over-invention check: did the model invent catalog numbers? ---
        invented = [
            m.get("item", "?")
            for m in materials
            if m.get("catalog_number") and m["catalog_number"] != CONFIRM
            and not str(m["catalog_number"]).strip().lower().startswith("cat")
            and len(str(m["catalog_number"])) < 4
        ]
        if invented:
            findings.append({"severity": "high", "category": "over_invention",
                             "issue": f"Suspicious catalog numbers for: {', '.join(invented)}. Verify or mark uncertain."})

        # --- missing controls heuristic ---
        text_blob = " ".join(str(s.get("title", "")) for s in workflow).lower()
        if "control" not in text_blob and "no-template" not in text_blob:
            findings.append({"severity": "low", "category": "missing_controls",
                             "issue": "No explicit controls mentioned (e.g., no-template / positive control). Confirm whether the assay requires them."})

        # --- count unresolved confirm tags ---
        confirm_count = _count_confirm(proto)

        high = sum(1 for f in findings if f["severity"] == "high")
        if high > 0:
            decision = "revise"
            rationale = "Resolve high-severity gaps (QC/safety/over-invention) before bench use."
        elif findings:
            decision = "approve_with_caution"
            rationale = "Usable, but address the noted items and confirm all uncertain values first."
        else:
            decision = "approve"
            rationale = "No blocking issues found in DEMO review."

        return {
            "agent": self.name,
            "status": "success",
            "decision": decision,
            "rationale": rationale,
            "findings": findings,
            "strengths": [
                "Uncertain values are explicitly tagged rather than invented." if confirm_count else
                "All quantitative fields are specified.",
                "Includes troubleshooting and failure branches.",
            ],
            "unresolved_confirm_tags": confirm_count,
            "safety_review": {
                "human_review_steps": [
                    s.get("step_id") for s in workflow if s.get("human_review_required")
                ],
                "note": "Steps changing sample handling, incubation, concentration, or cleanup require human sign-off.",
            },
            "summary": (
                f"DEMO review: {len(findings)} finding(s), {confirm_count} unresolved "
                f"'{CONFIRM}' tag(s). Decision: {decision}."
            ),
            "timestamp": utc_timestamp(),
        }


def _count_confirm(obj: Any) -> int:
    """Recursively count occurrences of the confirm tag anywhere in the protocol."""
    if isinstance(obj, str):
        return 1 if CONFIRM in obj else 0
    if isinstance(obj, dict):
        return sum(_count_confirm(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_confirm(v) for v in obj)
    return 0
