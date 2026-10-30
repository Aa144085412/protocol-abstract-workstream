"""
ProtocolAgent
=============
Converts parsed protocol facts + user context into a bench-ready protocol that
matches the required JSON schema (workflow steps, QC checkpoints, decision
points, failure branches, materials, revision log).

- ``generate`` -> strong model (novel synthesis).
- ``revise``   -> cheap model (surgical, structured edit of a few steps only).

DEMO_MODE returns a realistic, schema-complete mock so the whole app runs with
no API key.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def _bump_version(version: str) -> str:
    """v1 -> v2, v7 -> v8. Tolerates 'v1' or '1'."""
    m = re.search(r"(\d+)", version or "v1")
    n = int(m.group(1)) if m else 1
    return f"v{n + 1}"


class ProtocolAgent(BaseAgent):
    name = "Protocol Agent"
    tier = "strong"
    role = "protocol"

    # ------------------------------------------------------------------ #
    # Generate v1
    # ------------------------------------------------------------------ #
    def generate(self, parsed_document: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self.load_prompt(
            "protocol_agent.txt",
            parsed_document=parsed_document,
            user_context=user_context,
        )
        return self.run(
            prompt,
            payload={"parsed_document": parsed_document, "user_context": user_context},
            max_tokens=16000,
            temperature=0.2,
        )

    # ------------------------------------------------------------------ #
    # Revise -> v(n+1). Cheap model, surgical.
    # ------------------------------------------------------------------ #
    def revise(self, revision_request: Dict[str, Any]) -> Dict[str, Any]:
        prior = revision_request.get("prior_protocol", {}) or {}
        target = revision_request.get("target_version") or _bump_version(
            prior.get("protocol_version", "v1")
        )
        prompt = self.load_prompt(
            "protocol_revision.txt",
            prior_protocol=prior,
            troubleshooting_input=revision_request.get("troubleshooting_input", {}),
            user_constraints=revision_request.get("user_constraints", {}),
            target_version=target,
        )
        # Revision is a narrow structured edit -> route to the cheap model.
        original_tier = self.tier
        self.tier = "cheap"
        try:
            result = self.run(
                prompt,
                payload={"revision_request": revision_request, "target_version": target},
                max_tokens=8192,
                temperature=0.1,
            )
        finally:
            self.tier = original_tier
        return result

    # ------------------------------------------------------------------ #
    # Correction-driven revision -> v(n+1). Free-text correction from the
    # scientist (e.g. "this is scCUT&Tag, not ATAC-seq"). Strong model, because
    # it may rewrite/add steps and re-label the experiment, not just tweak one.
    # ------------------------------------------------------------------ #
    def revise_with_correction(self, protocol: Dict[str, Any], correction: str,
                               history: str = "", reference_text: str = "") -> Dict[str, Any]:
        prior = protocol or {}
        target = _bump_version(prior.get("protocol_version", "v1"))
        # Reference precedence: user-supplied text (pasted / uploaded file) is the
        # most reliable, used as-is. If none given but the correction cites link(s),
        # fetch their step detail via Anthropic web-search (best-effort).
        reference = (reference_text or "").strip()[:12000]
        used_fetch = False
        if not reference and not self.demo_mode:
            urls = _URL_RE.findall(correction or "")
            if urls:
                reference = self._fetch_reference(urls, correction)
                used_fetch = bool(reference)
        prompt = self.load_prompt(
            "protocol_correction.txt",
            prior_protocol=prior,
            history=history or "(none)",
            reference=reference or "(no link provided or retrieval unavailable)",
            correction=correction,
            target_version=target,
        )
        result = self.run(
            prompt,
            payload={"correction_request": {"prior_protocol": prior, "correction": correction},
                     "target_version": target},
            max_tokens=16000,
            temperature=0.2,
        )
        if isinstance(result, dict) and result.get("status") == "success":
            result["_retrieved_reference"] = bool(reference)
            result["_reference_source"] = (
                "pasted/uploaded" if (reference_text or "").strip()
                else ("web" if used_fetch else "none"))
        return result

    def _fetch_reference(self, urls: List[str], correction: str) -> str:
        """Pull step-by-step text from cited protocol URL(s) using the Anthropic
        web-search server tool. Works even when this agent is routed to OpenAI
        (web_search is Anthropic-only) as long as an Anthropic key is present.
        Returns plain text (truncated) or '' on any failure."""
        if not self.anthropic_key:
            return ""
        saved_provider, saved_client = self.provider, self._client
        self.provider, self._client = "anthropic", None
        try:
            q = (
                "Open the protocol page(s) below and extract the step-by-step "
                "procedure as plain text: ordered steps with any stated volumes, "
                "times, temperatures, speeds (xg/rpm), antibodies, reagents and "
                "kit steps. Quote exact numbers when present; do not invent any.\n"
                f"Pages: {' '.join(urls[:3])}\n"
                f"Focus on what this correction is about: {correction[:600]}"
            )
            txt = self.call(q, max_tokens=4096, temperature=0.0, tools=[WEB_SEARCH_TOOL])
            return (txt or "").strip()[:9000]
        except Exception:  # noqa: BLE001 - retrieval is best-effort
            return ""
        finally:
            self.provider, self._client = saved_provider, saved_client

    # ================================================================== #
    # DEMO RESPONSES
    # ================================================================== #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "correction_request" in payload:
            return self._demo_correction(payload["correction_request"], payload["target_version"])
        if "revision_request" in payload:
            return self._demo_revision(payload["revision_request"], payload["target_version"])
        return self._demo_generate(
            payload.get("parsed_document", {}), payload.get("user_context", {})
        )

    # ------------------------------------------------------------------ #
    def _demo_correction(self, req: Dict[str, Any], target_version: str) -> Dict[str, Any]:
        """Offline fallback. Cannot do the scientific rewrite a model does, so it
        records the correction as a tracked revision: bumps the version, appends
        the correction to the summary/log, and flags every step for human review
        so nothing is silently 'corrected'."""
        prior = copy.deepcopy(req.get("prior_protocol", {}) or {})
        correction = (req.get("correction") or "").strip()
        new_proto = copy.deepcopy(prior)
        new_proto["protocol_version"] = target_version

        changed_ids = [s.get("step_id") for s in new_proto.get("workflow", []) if s.get("step_id")]
        note = f"[Correction {target_version}] {correction}"
        for s in new_proto.get("workflow", []):
            s.setdefault("notes", [])
            s["notes"].append(note)
            hr = s.setdefault("human_review_required", [])
            hr.append(f"User correction pending review: {correction}")

        new_proto["revision_log"] = (prior.get("revision_log", []) or []) + [
            {"version": target_version, "reason": f"User correction: {correction}",
             "changed_step_ids": changed_ids},
        ]
        new_proto["agent"] = self.name
        new_proto["status"] = "success"
        new_proto["changed_step_ids"] = changed_ids
        new_proto["summary_of_changes"] = (
            f"Recorded user correction (offline mode — no model rewrite): \"{correction}\". "
            "Every step flagged for human review. Run with a live model "
            "(DEMO_MODE=false) to auto-rewrite the affected steps, labels, and QC.")
        new_proto["root_cause_diagnosis"] = (
            "Offline mode cannot perform the scientific rewrite; the correction is "
            "logged and surfaced so a human (or the live model) can apply it.")
        new_proto["confidence"] = "low"
        new_proto["timestamp"] = utc_timestamp()
        return new_proto

    # ------------------------------------------------------------------ #
    def _demo_generate(self, parsed: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        level = (ctx.get("experience_level") or "intermediate").lower()
        title = parsed.get("protocol_title") or ctx.get("experiment_name") or "Nucleic Acid Purification"
        assay = parsed.get("assay_type") or ctx.get("assay_type") or "Purification"
        beginner = level == "beginner"

        def beginner_notes(base: List[str]) -> List[str]:
            if beginner:
                return base + ["Beginner tip: work slowly, label every tube before you start, "
                               "and keep a written log of actual volumes/times used."]
            return base

        workflow = [
            {
                "step_id": "step_01",
                "step_number": 1,
                "title": "Prepare and pre-warm buffers",
                "purpose": "Ensure reagents are at working condition and fully dissolved before adding sample.",
                "instructions": beginner_notes([
                    f"Confirm all buffers from the materials list are present and unexpired.",
                    f"Pre-warm elution buffer to the temperature stated in the source protocol ({CONFIRM}).",
                    "Check that ethanol has been added to any concentrated wash buffer (first use only).",
                ]),
                "time_estimate": "5-10 min",
                "conditions": {"temperature": CONFIRM, "speed": "", "other": "Buffers fully dissolved, no precipitate"},
                "expected_observation": "Clear buffers, no visible precipitate; elution buffer warmed.",
                "checkpoint": "All required buffers present, labelled, and at correct temperature.",
                "pause_point": False,
                "human_review_required": [],
                "troubleshooting": [
                    {
                        "problem": "Precipitate visible in lysis/binding buffer",
                        "possible_causes": ["Cold storage caused salts to crash out"],
                        "actions": ["Warm buffer and mix gently until fully dissolved before use"],
                        "escalate_if": "Precipitate will not redissolve after warming.",
                    }
                ],
                "notes": [],
            },
            {
                "step_id": "step_02",
                "step_number": 2,
                "title": "Lyse / resuspend sample",
                "purpose": "Release target nucleic acid from cells while controlling degradation.",
                "instructions": beginner_notes([
                    f"Add lysis/resuspension buffer to sample (volume: {CONFIRM}).",
                    f"Mix as specified in source protocol; incubate for {CONFIRM} at {CONFIRM}.",
                    "Do not vortex if the source protocol specifies gentle inversion (shearing risk).",
                ]),
                "time_estimate": CONFIRM,
                "conditions": {"temperature": CONFIRM, "speed": "Gentle / per source", "other": ""},
                "expected_observation": "Lysate becomes clear/viscous (sample dependent).",
                "checkpoint": "Lysate homogeneous; no visible clumps remain.",
                "pause_point": False,
                "human_review_required": ["Sample handling step — confirm volumes/times against source before scaling."],
                "troubleshooting": [
                    {
                        "problem": "Incomplete lysis (clumps remain)",
                        "possible_causes": ["Too much input material", "Insufficient lysis time"],
                        "actions": ["Reduce input to within source range", f"Extend incubation per source ({CONFIRM})"],
                        "escalate_if": "Clumps persist after recommended maximum incubation.",
                    }
                ],
                "notes": [],
            },
            {
                "step_id": "step_03",
                "step_number": 3,
                "title": "Bind nucleic acid to column / beads",
                "purpose": "Capture the target onto the solid phase while contaminants stay in solution.",
                "instructions": beginner_notes([
                    "Apply lysate to column (or add beads) per source protocol.",
                    f"Centrifuge at {CONFIRM} for {CONFIRM}; discard flow-through.",
                ]),
                "time_estimate": CONFIRM,
                "conditions": {"temperature": "Room temp unless stated", "speed": CONFIRM, "other": ""},
                "expected_observation": "Flow-through passes cleanly; column not clogged.",
                "checkpoint": "Full lysate volume passed through column.",
                "pause_point": False,
                "human_review_required": [],
                "troubleshooting": [
                    {
                        "problem": "Column clogs / slow flow",
                        "possible_causes": ["Overloaded column", "Incomplete lysis"],
                        "actions": ["Spin longer at recommended speed", "Split lysate across two columns if overloaded"],
                        "escalate_if": "Column will not clear after extended spin.",
                    }
                ],
                "notes": [],
            },
            {
                "step_id": "step_04",
                "step_number": 4,
                "title": "Wash",
                "purpose": "Remove salts, proteins and other contaminants from the bound target.",
                "instructions": beginner_notes([
                    f"Add wash buffer ({CONFIRM} volume); centrifuge and discard flow-through.",
                    "Repeat washes for the number of cycles specified in the source protocol.",
                    "Perform a final dry spin to remove residual ethanol.",
                ]),
                "time_estimate": CONFIRM,
                "conditions": {"temperature": "Room temp", "speed": CONFIRM, "other": "Ethanol-based wash"},
                "expected_observation": "No liquid remains in column after final dry spin.",
                "checkpoint": "Residual ethanol removed (critical for downstream enzymatics).",
                "pause_point": False,
                "human_review_required": ["Purification/cleanup step — changes here affect downstream yield/purity."],
                "troubleshooting": [
                    {
                        "problem": "Residual ethanol carryover",
                        "possible_causes": ["Skipped dry spin", "Eluted too soon"],
                        "actions": ["Add an extra dry spin", "Let column air-dry briefly before eluting"],
                        "escalate_if": "Downstream reactions are inhibited.",
                    }
                ],
                "notes": [],
            },
            {
                "step_id": "step_05",
                "step_number": 5,
                "title": "Elute purified product",
                "purpose": "Recover purified nucleic acid in a defined buffer/volume.",
                "instructions": beginner_notes([
                    f"Add pre-warmed elution buffer/water ({CONFIRM} volume) to the centre of the membrane.",
                    f"Incubate {CONFIRM}, then centrifuge to collect eluate.",
                    "Keep eluate on ice; store per source protocol.",
                ]),
                "time_estimate": "2-5 min",
                "conditions": {"temperature": CONFIRM, "speed": CONFIRM, "other": ""},
                "expected_observation": "Clear eluate collected in a clean tube.",
                "checkpoint": "Eluate volume close to elution volume added.",
                "pause_point": True,
                "human_review_required": [],
                "troubleshooting": [
                    {
                        "problem": "Low elution volume recovered",
                        "possible_causes": ["Membrane absorbed buffer", "Spin too short"],
                        "actions": ["Re-spin briefly", "Add a second elution if yield is critical"],
                        "escalate_if": "Recovered volume is far below expected.",
                    }
                ],
                "notes": ["Safe stopping point — eluate can be stored before QC."],
            },
            {
                "step_id": "step_06",
                "step_number": 6,
                "title": "QC: concentration and purity",
                "purpose": "Verify yield and purity meet requirements before proceeding downstream.",
                "instructions": beginner_notes([
                    "Measure concentration (e.g., spectrophotometer/fluorometer).",
                    "Record A260/A280 and A260/A230 ratios.",
                    "Log yield = concentration x eluate volume.",
                ]),
                "time_estimate": "10 min",
                "conditions": {"temperature": "Room temp", "speed": "", "other": ""},
                "expected_observation": "Measurable concentration with ratios in expected range.",
                "checkpoint": "Yield and purity recorded and compared to pass criteria.",
                "pause_point": True,
                "human_review_required": [],
                "troubleshooting": [
                    {
                        "problem": "Low yield",
                        "possible_causes": ["Low input", "Incomplete lysis", "Over-washing", "Single elution"],
                        "actions": ["Increase input within source range", "Add second elution", "Review lysis completeness"],
                        "escalate_if": "Yield is below the minimum needed for the downstream assay.",
                    },
                    {
                        "problem": "Low A260/A230 (salt/organic contamination)",
                        "possible_causes": ["Insufficient washing", "Ethanol carryover"],
                        "actions": ["Add wash step", "Re-purify if downstream is sensitive"],
                        "escalate_if": "Contamination inhibits downstream enzymatic steps.",
                    },
                ],
                "notes": [],
            },
        ]

        return {
            "agent": self.name,
            "status": "success",
            "protocol_title": title,
            "protocol_version": "v1",
            "assay_type": assay,
            "objective": ctx.get("objective")
            or f"Produce purified, QC-passed product suitable for downstream {assay}.",
            "intended_user": level if level in ("beginner", "intermediate", "expert") else "mixed",
            "summary": (
                "Bench-ready protocol generated from parsed source facts and user context "
                "(DEMO MODE). Exact volumes/times/temperatures are marked "
                f"'{CONFIRM}' where the source document did not provide them — confirm "
                "before bench use. No catalog numbers were invented."
            ),
            "preconditions": {
                "sample_requirements": parsed.get("sample_requirements")
                or [f"Input type/amount: {CONFIRM}", f"Number of samples: {ctx.get('num_samples', CONFIRM)}"],
                "reagent_requirements": [m.get("item", "") for m in parsed.get("materials", [])]
                or ["Lysis buffer", "Wash buffer", "Elution buffer", "Column/beads"],
                "equipment_requirements": parsed.get("equipment")
                or ["Microcentrifuge", "Heat block", "Pipettes + tips", "Vortex"],
                "safety_notes": parsed.get("safety_notes")
                or ["Handle guanidine/ethanol buffers per SDS; never mix guanidine with bleach."],
                "lab_specific_fields_to_confirm": parsed.get("uncertain_fields")
                or ["Buffer volumes", "Incubation times/temperatures", "Centrifuge speeds", "Catalog numbers"],
            },
            "materials": (
                parsed.get("materials")
                or [
                    {"item": "Lysis buffer", "vendor": CONFIRM, "catalog_number": CONFIRM, "amount": CONFIRM, "required": True, "notes": ""},
                    {"item": "Wash buffer", "vendor": CONFIRM, "catalog_number": CONFIRM, "amount": CONFIRM, "required": True, "notes": "Add ethanol on first use"},
                    {"item": "Elution buffer / nuclease-free water", "vendor": CONFIRM, "catalog_number": CONFIRM, "amount": CONFIRM, "required": True, "notes": ""},
                    {"item": "Purification column or beads", "vendor": CONFIRM, "catalog_number": CONFIRM, "amount": "1 per sample", "required": True, "notes": ""},
                ]
            ),
            "workflow": workflow,
            "qc_checkpoints": [
                {
                    "checkpoint_name": "Post-elution yield & purity",
                    "when": "After step_06",
                    "measurements": ["Concentration (ng/uL)", "A260/A280", "A260/A230", "Total yield (ng)"],
                    "pass_criteria": [
                        f"Yield >= downstream requirement ({CONFIRM})",
                        "A260/A280 within expected range for the analyte",
                    ],
                    "fail_signals": ["Yield below threshold", "A260/A230 low (contamination)"],
                    "recommended_action_on_fail": "Trigger revision: review input amount, lysis completeness, wash/elution.",
                }
            ],
            "decision_points": [
                {
                    "decision": "Proceed downstream or re-purify?",
                    "when": "After QC (step_06)",
                    "options": [
                        "Pass -> proceed to downstream assay",
                        "Marginal -> concentrate / re-elute",
                        "Fail -> re-extract or trigger protocol revision",
                    ],
                }
            ],
            "failure_branches": [
                {
                    "condition": "Low yield at QC",
                    "step_ids_affected": ["step_02", "step_04", "step_05"],
                    "likely_causes": ["Low input", "Incomplete lysis", "Over-washing", "Single elution"],
                    "recommended_modifications": [
                        "Increase input within source range",
                        "Add a second elution with warmed buffer",
                        "Verify lysis time/temperature against source",
                    ],
                    "whether_to_repeat_or_stop": "Repeat purification with modifications; stop if input is exhausted.",
                },
                {
                    "condition": "Downstream inhibition / contamination",
                    "step_ids_affected": ["step_04"],
                    "likely_causes": ["Ethanol carryover", "Insufficient washing"],
                    "recommended_modifications": ["Add dry spin", "Add an extra wash cycle"],
                    "whether_to_repeat_or_stop": "Re-purify eluate or repeat from wash step.",
                },
            ],
            "artifact_outputs": ["protocol_v1.json", "protocol_v1.md", "protocol_bench_v1.md"],
            "revision_log": [
                {"version": "v1", "reason": "initial protocol", "changed_step_ids": []}
            ],
            "open_questions_for_human": [
                "Confirm all volumes/times/temperatures marked with the confirm tag against the source document.",
                "Confirm vendor catalog numbers for the kit being used.",
                f"Confirm minimum acceptable yield for the intended downstream {assay}.",
            ],
            "confidence": "medium",
            "timestamp": utc_timestamp(),
        }

    # ------------------------------------------------------------------ #
    def _demo_revision(self, req: Dict[str, Any], target_version: str) -> Dict[str, Any]:
        prior = copy.deepcopy(req.get("prior_protocol", {}) or {})
        ts_input = req.get("troubleshooting_input", {}) or {}
        flagged = ts_input.get("flagged_steps", []) or []
        flagged_ids = [f.get("step_id") for f in flagged if f.get("step_id")]
        notes = ts_input.get("additional_notes", "")

        new_proto = copy.deepcopy(prior)
        new_proto["protocol_version"] = target_version
        changed_ids: List[str] = []

        issue_summ = ", ".join(
            f"{f.get('step_id','?')} ({f.get('issue_type','issue')}: {f.get('observation','')})"
            for f in flagged
        ) or "general review"

        # Surgically modify ONLY flagged steps; preserve everything else exactly.
        for step in new_proto.get("workflow", []):
            if step.get("step_id") in flagged_ids:
                changed_ids.append(step["step_id"])
                flag = next((f for f in flagged if f.get("step_id") == step["step_id"]), {})
                issue_type = (flag.get("issue_type") or "issue").lower()

                rev_note = (
                    f"[Revised {target_version}] Addressing reported '{issue_type}': "
                    f"{flag.get('observation','')}."
                )
                step.setdefault("notes", [])
                step["notes"].append(rev_note)

                # Targeted, conservative modifications by issue type.
                mod_actions: List[str] = []
                if "yield" in issue_type:
                    mod_actions = [
                        "Add a second elution with pre-warmed buffer and a longer membrane soak.",
                        f"Re-confirm input amount is within source range ({CONFIRM}); increase only within range.",
                    ]
                elif "band" in issue_type or "fragment" in issue_type:
                    mod_actions = [
                        "Reduce shearing: switch vortexing to gentle inversion where source allows.",
                        "Confirm elution volume is not over-diluting the product.",
                    ]
                elif "background" in issue_type:
                    mod_actions = ["Add an additional wash cycle to reduce contamination/background."]
                elif "viability" in issue_type or "loss" in issue_type or "cell" in issue_type:
                    mod_actions = [
                        "Gentler resuspension and reduced spin speed within source-safe range.",
                        "Minimise time cells spend in lysis/handling buffers.",
                    ]
                elif "reagent" in issue_type or "equipment" in issue_type:
                    mod_actions = [
                        "Substitute only with a source-compatible equivalent; flag for human review.",
                    ]
                else:
                    mod_actions = ["Conservative adjustment; confirm against source protocol."]

                step["troubleshooting"] = step.get("troubleshooting", []) + [
                    {
                        "problem": f"Reported during run: {flag.get('observation','')}",
                        "possible_causes": ["See root cause diagnosis"],
                        "actions": mod_actions,
                        "escalate_if": "Issue recurs after this revision.",
                    }
                ]

                # Any change to sample handling / incubation / concentration / cleanup
                # or substitution requires explicit human review.
                hr = step.setdefault("human_review_required", [])
                hr.append(
                    f"Revision {target_version} altered this step due to '{issue_type}'. "
                    "Confirm the change is safe and within source-protocol limits before bench use."
                )

        new_proto["revision_log"] = (prior.get("revision_log", []) or []) + [
            {
                "version": target_version,
                "reason": f"Troubleshooting revision: {issue_summ}. {notes}".strip(),
                "changed_step_ids": changed_ids,
            }
        ]
        new_proto["artifact_outputs"] = list(
            dict.fromkeys(
                (prior.get("artifact_outputs", []) or [])
                + [f"protocol_{target_version}.json", f"protocol_{target_version}.md"]
            )
        )

        # Attach revision metadata at the top level (required by spec).
        new_proto["agent"] = self.name
        new_proto["status"] = "success"
        new_proto["changed_step_ids"] = changed_ids
        new_proto["summary_of_changes"] = (
            f"Revised {len(changed_ids)} step(s) ({', '.join(changed_ids) or 'none'}) to address "
            f"{issue_summ}. All other steps preserved unchanged."
        )
        new_proto["root_cause_diagnosis"] = self._diagnose(flagged, notes)
        new_proto["confidence"] = "medium"
        new_proto["timestamp"] = utc_timestamp()
        return new_proto

    @staticmethod
    def _diagnose(flagged: List[Dict[str, Any]], notes: str) -> str:
        if not flagged:
            return "No specific step flagged; general review requested."
        bits = []
        for f in flagged:
            it = (f.get("issue_type") or "issue").lower()
            if "yield" in it:
                bits.append("Low yield most often traces to input amount, incomplete lysis, over-washing, or single elution.")
            elif "band" in it:
                bits.append("Absent band suggests degradation, loss during cleanup, or insufficient template.")
            elif "background" in it:
                bits.append("High background usually indicates insufficient washing or carryover contamination.")
            elif "viability" in it or "loss" in it:
                bits.append("Cell loss/low viability points to harsh handling, excessive spin speed, or prolonged buffer exposure.")
            elif "fragment" in it:
                bits.append("Wrong fragment size suggests shearing or incomplete digestion/elution.")
            elif "reagent" in it or "equipment" in it:
                bits.append("A missing reagent/equipment constraint requires a validated substitution, flagged for human review.")
            else:
                bits.append(f"Reported issue '{it}': review the affected step against the source protocol.")
        if notes:
            bits.append(f"User notes considered: {notes}")
        return " ".join(bits)
