"""
AuditAgent
==========
Audits uploaded/parsed protocol documents (or a built protocol) for problems a
naive merge would hide:

  - REDUNDANCY / repetition (the same step or content appearing more than once,
    across documents or within one),
  - CONTRADICTIONS / internal conflicts (two places stating incompatible things),
  - ILLOGICAL ORDER (a step depending on something that happens later),
  - UNSUPPORTED / FALSE LOGIC (claims that don't follow, or that conflict with the
    project's ground-truth notes).

It only FLAGS — it does not rewrite. Routes to the strong model (judgement); a
deterministic heuristic runs in DEMO_MODE. Honors any "ground-truth"/"STUDY NOTES"
document as the source of truth when judging contradictions.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

_STOP = {"the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "by", "step",
         "prepare", "perform", "using", "via", "from", "into", "at", "as", "is", "be"}

# keyword pairs that commonly signal a contradiction if BOTH appear prominently
_CONTRA_PAIRS = [
    ("atac-seq", "cut&tag"), ("atac seq", "cut and tag"),
    ("wild-type cas9", "espcas9"), ("wild type cas9", "espcas9"),
    ("nanocut&tag", "not bench"), ("free-tn5", "pa-tn5"),
    ("spear-atac capture", "grna2 capture"),
]


def _tok(s: str):
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


class AuditAgent(BaseAgent):
    name = "Consistency Auditor"
    tier = "strong"
    role = "audit"

    def audit(self, docs: List[Dict[str, Any]] | None = None,
              protocol: Dict[str, Any] | None = None,
              ground_truth: str = "") -> Dict[str, Any]:
        docs = docs or []
        if self.demo_mode:
            return self._demo(docs, protocol or {})
        slim_docs = [{"title": d.get("protocol_title") or d.get("title", ""),
                      "doc_type": d.get("doc_type", ""),
                      "major_steps": (d.get("major_steps") or [])[:30],
                      "summary": (d.get("summary", "") or "")[:600]} for d in docs]
        wf = [{"step_number": s.get("step_number"), "title": s.get("title"),
               "instructions": s.get("instructions")}
              for s in (protocol or {}).get("workflow", []) or []]
        prompt = self.load_prompt(
            "audit_agent.txt",
            documents=json.dumps(slim_docs, ensure_ascii=False)[:14000],
            workflow=json.dumps(wf, ensure_ascii=False)[:8000],
            ground_truth=(ground_truth or "(none)")[:4000],
        )
        try:
            data = self.extract_json(self.call(prompt, max_tokens=3000, temperature=0.1, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        data.setdefault("agent", self.name)
        data.setdefault("status", "success")
        data["mode"] = "live"
        data["timestamp"] = utc_timestamp()
        return data

    # ------------------------------------------------------------------ #
    def _demo(self, docs, protocol) -> Dict[str, Any]:
        findings: List[Dict[str, str]] = []

        # 1) redundancy across documents (heavy step overlap)
        steps_by_doc = {}
        for d in docs:
            title = d.get("protocol_title") or d.get("title", "doc")
            toks = set()
            for s in d.get("major_steps", []) or []:
                toks |= _tok(s)
            steps_by_doc[title] = toks
        names = list(steps_by_doc)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = steps_by_doc[names[i]], steps_by_doc[names[j]]
                if a and b:
                    ov = len(a & b) / min(len(a), len(b))
                    if ov >= 0.6:
                        findings.append({
                            "type": "redundancy", "severity": "medium",
                            "where": f"'{names[i]}' vs '{names[j]}'",
                            "issue": f"Documents overlap ~{int(ov*100)}% in their steps — likely "
                                     "redundant; design will merge, confirm which is authoritative.",
                            "suggested_fix": "Keep one as the protocol; mark the other reference/superseded."})

        # 2) repeated steps within a doc / protocol
        wf = protocol.get("workflow", []) or []
        seen = {}
        for s in wf:
            key = " ".join(sorted(_tok(s.get("title", ""))))
            if key and key in seen:
                findings.append({"type": "repetition", "severity": "low",
                                 "where": f"steps {seen[key]} & {s.get('step_number')}",
                                 "issue": f"Step '{s.get('title')}' looks repeated.",
                                 "suggested_fix": "Merge the duplicate steps."})
            elif key:
                seen[key] = s.get("step_number")

        # 3) contradiction keyword scan across all text
        blob = " ".join(
            [(d.get("summary", "") or "") + " " + " ".join(d.get("major_steps", []) or []) for d in docs]
            + [s.get("title", "") + " " + " ".join(s.get("instructions", []) or []) for s in wf]
        ).lower()
        for k1, k2 in _CONTRA_PAIRS:
            if k1 in blob and k2 in blob:
                findings.append({"type": "possible_contradiction", "severity": "high",
                                 "where": "across the uploaded content",
                                 "issue": f"Both '{k1}' and '{k2}' appear — check these aren't conflicting "
                                          "(e.g. assay/reagent described two incompatible ways).",
                                 "suggested_fix": "Reconcile against the ground-truth note."})

        by_sev = {"high": 0, "medium": 0, "low": 0}
        for f in findings:
            by_sev[f.get("severity", "low")] = by_sev.get(f.get("severity", "low"), 0) + 1
        return {
            "agent": self.name, "status": "success", "mode": "offline",
            "findings": findings,
            "counts": by_sev,
            "summary": (f"{len(findings)} flag(s): {by_sev['high']} high, {by_sev['medium']} medium, "
                        f"{by_sev['low']} low. Offline heuristic — run live for full contradiction/"
                        "logic checking against the ground-truth notes."),
            "timestamp": utc_timestamp(),
        }
