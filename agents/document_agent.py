"""
DocumentAgent
=============
Parses raw protocol text (already extracted from PDF/DOCX/TXT/MD) into
structured *protocol facts*. This is a narrow, structured extraction task, so it
routes to the CHEAP model. It must NOT invent missing values; uncertain fields
are marked ``[confirm with source protocol]``.
"""

from __future__ import annotations

from typing import Any, Dict

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"


def classify_doc(text: str, title: str = "") -> str:
    """Heuristically classify an uploaded document into:
    'protocol' (executable steps), 'background' (onboarding/project context),
    'literature' (paper/reference to study), or 'reference'. Local, no model."""
    t = (title + " " + (text or "")[:4000]).lower()
    if any(k in t for k in ("onboarding", "handoff", "project overview", "project background",
                            "getting started", "team guide", "lab notebook")):
        return "background"
    # paper / literature cues
    lit_cues = ("abstract", "we report", "we present", "doi:", "et al", "introduction\n",
                "references\n", "biorxiv", "biorxiv", "supplementary", "supplement")
    paperish_title = (":" in title and len(title) > 45 and
                      any(w in t for w in ("linking", "screen", "profiling", "analysis", "recovery", "compatible")))
    if sum(1 for c in lit_cues if c in t) >= 2 or paperish_title:
        return "literature"
    # protocol cues
    proto_cues = ("protocol", "prep", "preparation", "extraction", "kit", "reagent",
                  "incubate", "centrifuge", "resuspend", "elute", "pipette", "step ",
                  "user guide", "transfection", "ligation", "digest", "pcr")
    if sum(1 for c in proto_cues if c in t) >= 2:
        return "protocol"
    return "reference"


class DocumentAgent(BaseAgent):
    name = "Document Agent"
    tier = "cheap"
    role = "document"

    def parse(self, raw_text: str, file_name: str = "") -> Dict[str, Any]:
        prompt = self.load_prompt(
            "document_agent.txt",
            document_text=raw_text[:60000],
            file_name=file_name or "uploaded_protocol",
        )
        result = self.run(
            prompt,
            payload={"raw_text": raw_text, "file_name": file_name},
            max_tokens=8192,
            temperature=0.0,
        )
        # guarantee a document-type classification regardless of provider
        if isinstance(result, dict) and result.get("status") == "success" \
                and not result.get("doc_type"):
            result["doc_type"] = classify_doc(raw_text, result.get("protocol_title", ""))
        return result

    # ------------------------------------------------------------------ #
    def demo_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = (payload.get("raw_text") or "").lower()
        # crude heuristic so the demo feels responsive to the upload
        if "maxiprep" in text or "plasmid" in text:
            title = "Plasmid Maxiprep (alkaline lysis + column)"
            assay = "Plasmid DNA purification"
        elif "cut&tag" in text or "cut and tag" in text or "cut_tag" in text:
            title = "Single-cell CUT&Tag"
            assay = "Chromatin profiling (CUT&Tag)"
        elif "rna" in text and "extract" in text:
            title = "Total RNA Extraction"
            assay = "RNA purification"
        else:
            title = "Genomic DNA Extraction"
            assay = "DNA purification"

        return {
            "agent": self.name,
            "status": "success",
            "source_file": payload.get("file_name") or "uploaded_protocol",
            "doc_type": classify_doc(payload.get("raw_text") or "", title),
            "protocol_title": title,
            "assay_type": assay,
            "summary": (
                "Parsed protocol facts (DEMO MODE). Values shown are illustrative; "
                "exact volumes/times/temperatures must be confirmed against the "
                "source document before bench use."
            ),
            "materials": [
                {"item": "Lysis buffer", "amount": CONFIRM, "vendor": CONFIRM, "catalog_number": CONFIRM},
                {"item": "Wash buffer", "amount": CONFIRM, "vendor": CONFIRM, "catalog_number": CONFIRM},
                {"item": "Elution buffer / nuclease-free water", "amount": CONFIRM, "vendor": CONFIRM, "catalog_number": CONFIRM},
                {"item": "Spin / purification column", "amount": "1 per sample", "vendor": CONFIRM, "catalog_number": CONFIRM},
            ],
            "equipment": [
                "Microcentrifuge (rated for column spins)",
                "Heat block or water bath",
                "Pipettes + filter tips",
                "Vortex mixer",
            ],
            "sample_requirements": [
                f"Input sample type and amount: {CONFIRM}",
                f"Starting cell/material count: {CONFIRM}",
            ],
            "major_steps": [
                "Prepare and pre-warm buffers",
                "Lyse / resuspend sample",
                "Bind nucleic acid to column or beads",
                "Wash to remove contaminants",
                "Elute purified product",
                "QC: concentration and purity",
            ],
            "qc_mentions": [
                "A260/A280 and A260/A230 ratios",
                "Yield (ng/uL x volume)",
            ],
            "safety_notes": [
                "Some lysis/wash buffers contain guanidine salts and/or ethanol "
                "— do not mix guanidine with bleach. Handle per SDS.",
            ],
            "uncertain_fields": [
                "Exact buffer volumes",
                "Incubation times and temperatures",
                "Centrifugation speeds (xg) and durations",
                "Vendor catalog numbers",
            ],
            "raw_text_chars": len(payload.get("raw_text") or ""),
            "timestamp": utc_timestamp(),
        }
