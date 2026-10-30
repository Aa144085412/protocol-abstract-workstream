"""
ExperimentDesignAgent
=====================
The missing *upstream* stage: turn a research question into an actual experimental
design — before any protocol exists. Three capabilities:

  • design()   — from a goal/hypothesis (+ optional context & reference docs), propose
                 arms/conditions, controls (positive / negative / non-targeting /
                 technical), cell models, perturbation modality, readouts, replicates
                 & a power note, confounds to control, a phased timeline, and a
                 high-level PROTOCOL OUTLINE that can flow into the execution pipeline.
  • critique() — design-review pass: flag missing controls, confounds, batch effects,
                 under-powering, portability gaps, with a one-line fix each.
  • guides()   — molecular design helper: gRNA / oligo / primer design *criteria* and
                 an ordering checklist, grounded in an uploaded library spreadsheet
                 (it reads how many genes / oligos are already designed).

Routes to the STRONG model (novel design reasoning). Deterministic scaffolds run in
DEMO_MODE so the stage is always usable offline. It never claims an experiment will
work and never invents specific guide sequences — it gives design criteria, not data.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp


def _norm_level(level: str) -> str:
    l = (level or "intermediate").lower()
    if any(k in l for k in ("begin", "novice", "undergrad")):
        return "beginner"
    if any(k in l for k in ("expert", "advanced", "senior", "scientist", "pi")):
        return "expert"
    return "intermediate"


class ExperimentDesignAgent(BaseAgent):
    name = "Experiment Designer"
    tier = "strong"
    role = "expdesign"

    # ------------------------------------------------------------------ #
    def design(self, goal: str, context: Dict[str, Any] | None = None,
               docs: List[Dict[str, Any]] | None = None,
               level: str = "intermediate") -> Dict[str, Any]:
        context = context or {}
        docs = docs or []
        if self.demo_mode:
            return self._demo_design(goal, context, docs)
        slim = [{"title": d.get("title", d.get("name", "")),
                 "doc_type": d.get("doc_type", ""),
                 "text": (d.get("text", "") or "")[:1200]} for d in docs[:10]]
        prompt = self.load_prompt(
            "experiment_design.txt",
            goal=goal or "(no goal given)",
            context=json.dumps(context, ensure_ascii=False)[:2000],
            documents=json.dumps(slim, ensure_ascii=False)[:20000],
            level=_norm_level(level),
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=6000, temperature=0.25, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            fb = self._demo_design(goal, context)
            fb["note"] = f"Live design unavailable ({exc}); showing a structured template."
            return fb
        if not isinstance(data, dict):
            return self._demo_design(goal, context)
        data.update({"agent": self.name, "status": "success", "mode": "live",
                     "timestamp": utc_timestamp()})
        return data

    # ------------------------------------------------------------------ #
    def critique(self, target: str, docs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        docs = docs or []
        if self.demo_mode:
            return self._demo_critique(target)
        slim = [{"title": d.get("title", d.get("name", "")),
                 "text": (d.get("text", "") or "")[:800]} for d in docs[:8]]
        prompt = self.load_prompt(
            "design_critique.txt",
            design=str(target)[:14000],
            documents=json.dumps(slim, ensure_ascii=False)[:8000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=3000, temperature=0.2, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self._demo_critique(target, note=f"Live critique unavailable ({exc}).")
        if not isinstance(data, dict):
            return self._demo_critique(target)
        data.update({"agent": self.name, "status": "success", "mode": "live",
                     "timestamp": utc_timestamp()})
        return data

    # ------------------------------------------------------------------ #
    def guides(self, targets: str, context: Dict[str, Any] | None = None,
               docs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        context = context or {}
        docs = docs or []
        lib = self._scan_library(docs)
        if self.demo_mode:
            return self._demo_guides(targets, context, lib)
        slim = [{"title": d.get("title", d.get("name", "")),
                 "text": (d.get("text", "") or "")[:1500]} for d in docs[:8]]
        prompt = self.load_prompt(
            "guide_design.txt",
            targets=targets or "(targets from uploaded library, if any)",
            context=json.dumps(context, ensure_ascii=False)[:1500],
            library=json.dumps(lib, ensure_ascii=False)[:2000],
            documents=json.dumps(slim, ensure_ascii=False)[:14000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=3500, temperature=0.2, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self._demo_guides(targets, context, lib, note=f"Live unavailable ({exc}).")
        if not isinstance(data, dict):
            return self._demo_guides(targets, context, lib)
        data["library_detected"] = lib
        data.update({"agent": self.name, "status": "success", "mode": "live",
                     "timestamp": utc_timestamp()})
        return data

    # ------------------------------------------------------------------ #
    @staticmethod
    def _scan_library(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pull gene/oligo counts + a gene list out of an uploaded library spreadsheet
        text (the [SPREADSHEET] dump emitted by document_parser)."""
        out: Dict[str, Any] = {"genes": [], "n_genes": 0, "n_oligos": None, "source": ""}
        for d in docs:
            txt = d.get("text", "") or ""
            if "[SPREADSHEET]" not in txt and "Targets in" not in txt:
                continue
            m = re.search(r"Targets in '[^']*' \(column '[^']*', n=(\d+)\):\s*(.+)", txt)
            if m:
                out["n_genes"] = int(m.group(1))
                out["genes"] = [g.strip() for g in m.group(2).split(",")][:300]
                out["source"] = d.get("title", d.get("name", ""))
            mo = re.search(r"(?:Total oligos|Total pairs \(oligos\))[:\s]+(\d+)", txt)
            if mo:
                out["n_oligos"] = int(mo.group(1))
            if out["genes"]:
                break
        return out

    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_validation_assays(goal: str, docs: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
        """Deterministic heuristic for the validating readout, grounded in the uploaded
        text first. Detects a self-cleaving-peptide reporter design (P2A/T2A + a fluorophore,
        WT vs mutant) and proposes the anti-reporter Western that proves cleavage by size."""
        docs = docs or []
        text = (str(goal or "") + " " + " ".join((d.get("text", "") or "")[:4000] for d in docs)).lower()
        # approximate monomer sizes (domain knowledge; labeled as such)
        reporters = {"mcherry": ("mCherry", "~28 kDa"), "mscarlet": ("mScarlet", "~27 kDa"),
                     "egfp": ("EGFP", "~27 kDa"), "gfp": ("GFP", "~27 kDa"),
                     "mneongreen": ("mNeonGreen", "~27 kDa"), "bfp": ("BFP", "~27 kDa"),
                     "mcitrine": ("mCitrine", "~27 kDa")}
        rep = next(((nm, sz) for key, (nm, sz) in reporters.items() if key in text), None)
        has_2a = any(k in text for k in ("p2a", "t2a", "e2a", "f2a", "2a peptide", "self-clea", "self clea"))
        has_mut = any(k in text for k in ("mutant", "mut ", "cleavage-dead", "cleavage dead",
                                          "non-cleav", "noncleav", "uncleav", " wt ", "wild-type", "wild type"))
        in_doc = bool(docs) and (has_2a or (rep is not None))
        prov = ("[from uploaded doc]" if in_doc else "[domain knowledge]")
        if rep and has_2a and has_mut:
            nm, sz = rep
            return [{
                "name": f"anti-{nm} Western blot (cleavage validation)",
                "rationale": (f"A 2A self-cleaving peptide makes WT skip into two separate proteins, "
                              f"so {nm} runs as a free protein; a cleavage-dead mutant fails to "
                              f"separate, giving a single fusion that runs LARGER. The size shift is "
                              f"the direct proof that WT and mutant 2A behave differently."),
                "method": (f"Lyse cells; SDS-PAGE; immunoblot with anti-{nm} (and a loading control). "
                           f"Run WT and mutant side by side; compare apparent molecular weight."),
                "expected_results": {
                    f"WT 2A": f"free {nm} band at {sz} (cleaved) {prov}",
                    f"mutant 2A": f"single higher-MW fusion band ( upstream protein + {nm}, no free {nm} )",
                },
                "distinguishes": (f"presence of a free-{nm} band (WT) vs a single larger fusion band "
                                  f"(mutant) — the size difference proves cleavage status."),
                "provenance": prov + " reporter identity; sizes [domain knowledge, verify by ladder]",
            }]
        if rep:
            nm, sz = rep
            return [{
                "name": f"anti-{nm} Western blot",
                "rationale": f"Confirm {nm} expression and size as the readout for this construct.",
                "method": f"SDS-PAGE + immunoblot with anti-{nm}; include a loading control.",
                "expected_results": {"expressing cells": f"{nm} band at {sz}",
                                     "negative control": "no band"},
                "distinguishes": "expression vs no expression / correct size",
                "provenance": prov + "; size [domain knowledge, verify by ladder]",
            }]
        return [{
            "name": "Primary validation assay (define the readout)",
            "rationale": "Choose the assay that directly measures the difference your hypothesis predicts.",
            "method": "Pick a readout (Western / qPCR / flow / sequencing) that resolves the conditions.",
            "expected_results": {"test condition": "predicted positive signal",
                                 "control": "baseline / no signal"},
            "distinguishes": "test vs control on the primary endpoint",
            "provenance": "[domain knowledge]",
        }]

    # ------------------------------------------------------------------ #
    # Offline deterministic scaffolds
    # ------------------------------------------------------------------ #
    def _demo_design(self, goal: str, ctx: Dict[str, Any],
                     docs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        docs = docs or []
        cells = ctx.get("cell_models") or ctx.get("sample_type") or "your model system"
        modality = ctx.get("perturbation_modality") or "perturbation (e.g. CRISPRi/KO)"
        # infer a core experiment from messy docs when no goal was typed
        titles = [d.get("title", "") for d in docs if d.get("title")]
        goal = (goal or "").strip()
        inferred = ""
        if not goal and docs:
            inferred = (f"Core experiment inferred from {len(docs)} uploaded document(s)"
                        + (f": {titles[0]}" if titles else "") + ".")
        title = goal[:80] if goal else (titles[0][:80] if titles else "Experimental design")
        validations = self._infer_validation_assays(goal, docs)
        val_stages = [{"stage": v["name"], "summary": v["rationale"]} for v in validations]
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "title": title,
            "research_question": goal or inferred or "(state the question this experiment answers)",
            "hypothesis": "(state a falsifiable hypothesis: perturbing X changes readout Y in Z)",
            "rationale": "Template scaffold — run live for a goal-specific design.",
            "system": {"cell_models": [c.strip() for c in str(cells).split(",")],
                       "perturbation_modality": modality,
                       "delivery": "(e.g. lentivirus)", "selection": "(e.g. antibiotic/FACS)"},
            "arms": [
                {"name": "Perturbation arm", "purpose": "test effect of each target perturbation"},
                {"name": "Comparator arm", "purpose": "matched cells without the perturbation"},
            ],
            "controls": {
                "positive": ["a target with a known, validated phenotype"],
                "negative": ["mock / untransduced cells"],
                "non_targeting": ["≥2–3 non-targeting (NT) guides"],
                "technical": ["spike-in / loading control for the readout"],
            },
            "variables": {
                "independent": ["which target is perturbed", "cell model"],
                "dependent_readouts": ["primary readout (e.g. H3K27ac, viability, expression)"],
                "controlled": ["passage #", "MOI", "selection time", "batch/day"],
            },
            "replicates": {"biological": "≥3", "technical": "≥2",
                           "power_note": "Size to your expected effect & readout noise; "
                                         "pilot to estimate variance before scaling."},
            "confounds_to_control": ["batch/day effects (randomize & include controls per batch)",
                                     "MOI / coverage differences", "selection-driven drift"],
            "phases": [
                {"phase": "1 · Design & build", "goal": "design guides/reagents and build the library/constructs"},
                {"phase": "2 · Deliver & select", "goal": "transduce/transfect and select"},
                {"phase": "3 · Perturb & read out", "goal": "run the assay and collect the primary readout"},
                {"phase": "4 · Analyze", "goal": "QC, link perturbation→readout, test the hypothesis"},
            ],
            "validation_assays": validations,
            "protocol_outline": [
                {"stage": "Reagent / library design", "summary": "design and order guides/oligos/primers"},
                {"stage": "Construct / library build", "summary": "clone and validate"},
                {"stage": "Delivery", "summary": "deliver to cell models; select"},
                {"stage": "Perturbation & assay", "summary": "run the perturbation and the readout assay"},
                {"stage": "Readout & QC", "summary": "collect data, QC, and quantify"},
            ] + val_stages,
            "readouts": [v["name"] for v in validations] or ["(primary)", "(secondary/QC)"],
            "open_questions": ["What effect size is biologically meaningful?",
                               "Is the comparator matched (isogenic / same passage)?"],
            "risks": ["Underpowered if variance is high", "Confounded if controls aren't per-batch"],
            "timestamp": utc_timestamp(),
        }

    def _demo_critique(self, target: str, note: str = "") -> Dict[str, Any]:
        t = (target or "").lower()
        findings = []
        if "non-targeting" not in t and "nt " not in t and "ntc" not in t:
            findings.append({"category": "controls", "severity": "high",
                             "issue": "No non-targeting (NT) control is described.",
                             "fix": "Add ≥2–3 NT guides as the baseline comparator."})
        if "replicat" not in t and "n=" not in t:
            findings.append({"category": "power", "severity": "high",
                             "issue": "Replication / sample size not stated.",
                             "fix": "Specify biological (≥3) and technical replicates; justify by effect size."})
        if "batch" not in t and "randomi" not in t:
            findings.append({"category": "confounds", "severity": "medium",
                             "issue": "Batch/day effects not addressed.",
                             "fix": "Randomize conditions across batches and include controls in each batch."})
        if "positive control" not in t and "known" not in t:
            findings.append({"category": "controls", "severity": "medium",
                             "issue": "No positive control with a known phenotype.",
                             "fix": "Include a target with a validated, expected effect to confirm the assay works."})
        return {"agent": self.name, "status": "success", "mode": "offline",
                "findings": findings,
                "strengths": [],
                "summary": (note or "Offline heuristic review — run live for a full critique. "
                            f"Flagged {len(findings)} common gap(s)."),
                "timestamp": utc_timestamp()}

    def _demo_guides(self, targets: str, ctx: Dict[str, Any], lib: Dict[str, Any],
                     note: str = "") -> Dict[str, Any]:
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "library_detected": lib,
            "criteria": [
                "Specificity: prefer GuideScan2 specificity ≥ 0.2 and minimal off-targets.",
                "On-target: favor higher predicted cutting/efficiency scores.",
                "For CRISPRi (dCas9-KRAB): tile near the TSS (≈ −50 to +300 bp).",
                "For CRISPR-KO: target early constitutive exons; avoid last exon.",
                "Avoid homopolymer runs (A/T/C ≥4–5, G ≥6) and extreme GC.",
            ],
            "position_rules": ["Pos1 (U6-transcribed) must start with G.",
                               "Pos2 in a tRNA dual-guide bypasses the U6 +1 rule (no G-start needed)."],
            "pairing_scheme": "3 guides/gene (A,B,C) → pairs AB, AC, CA so each appears at both "
                              "positions once (balanced representation).",
            "oligo_architecture": "Each oligo: PCR-F · BsmBI · Spacer1 · scaffold · capture · adapter · "
                                  "tRNA · scaffold · Spacer2 · BsmBI · PCR-R.",
            "off_target_checklist": ["Run genome-wide off-target check for every spacer.",
                                     "Confirm no perfect off-target in coding/regulatory regions."],
            "ordering_checklist": ["312-nt ssDNA → PAGE purification (desalting truncates).",
                                   "Pool as IDT oPools; record pool name.",
                                   "Include NT control oligos in the pool.",
                                   "Keep a spacer↔gene map for downstream assignment."],
            "notes": note or "Offline guidance — run live to tailor to your targets/library.",
            "timestamp": utc_timestamp(),
        }
