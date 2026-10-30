"""
MethodsAgent
============
Drafts a paper-ready **Methods** section from one or more saved experiments in a
project. Routes to the CHEAP model (Haiku) when live; a deterministic writer
runs in DEMO_MODE.

It composes prose strictly from the protocol's recorded values. It does NOT
invent numbers — any value left as ``[confirm with source protocol]`` is written
as "(specify)" so the author fills it in. It never claims results.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base_agent import BaseAgent, utc_timestamp

CONFIRM = "[confirm with source protocol]"


def _clean(v: Any) -> str:
    s = str(v or "").strip()
    return "(specify)" if (not s or CONFIRM in s) else s


def _scrub(md: str) -> str:
    """Tidy leaked placeholders from live output: drop any stray confirm tags,
    collapse repeated '(specify)' and clean the parentheses they leave behind."""
    import re
    s = md or ""
    s = s.replace(CONFIRM, "[author: confirm]")
    # "(, [author: confirm], )" style debris -> remove empty/placeholder parens
    s = re.sub(r"\(\s*(?:\[author: confirm\]|\(specify\)|specify)\s*\)", "", s)
    s = re.sub(r"\(\s*,\s*", "(", s)
    s = re.sub(r"\s*,\s*\)", ")", s)
    s = re.sub(r"\(\s*\)", "", s)          # empty parens
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s+([.,;:])", r"\1", s)   # stray space before punctuation
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class MethodsAgent(BaseAgent):
    name = "Methods Writer"
    tier = "cheap"
    role = "methods"

    def write(self, experiments: List[Dict[str, Any]], project_name: str = "",
              style: str = "", length: str = "",
              extra_documents: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        style = style or "Generic high-impact journal (e.g. Nature/Cell) Methods voice."
        length = length or "Concise but complete — enough to reproduce, no padding."
        if self.demo_mode:
            return {
                "agent": self.name, "status": "success", "mode": "offline",
                "markdown": self._demo_methods(experiments, project_name),
                "timestamp": utc_timestamp(),
            }
        # live: model polish. Give it the experimental logic, not just steps.
        import json
        slim = [
            {
                "title": e.get("title"), "status": e.get("status"),
                "notes": e.get("notes"),
                "core_experiment": e.get("protocol", {}).get("core_experiment"),
                "objective": e.get("protocol", {}).get("objective"),
                "assay_type": e.get("protocol", {}).get("assay_type"),
                "materials": e.get("protocol", {}).get("materials", []),
                "workflow": [
                    {k: s.get(k) for k in ("step_number", "title", "purpose",
                                           "instructions", "time_estimate",
                                           "conditions", "reagents")}
                    for s in e.get("protocol", {}).get("workflow", []) or []
                ],
                "qc_checkpoints": e.get("protocol", {}).get("qc_checkpoints", []),
            }
            for e in experiments
        ]
        # All uploaded source documents (protocols + background + literature) so
        # the writer can verify details and pull recorded context — e.g. a
        # parental cell-line genotype — that the structured protocol may omit.
        source_docs = []
        for e in experiments:
            for d in e.get("source_documents", []) or []:
                source_docs.append({
                    "title": d.get("title") or d.get("name", ""),
                    "doc_type": d.get("doc_type", ""),
                    "text": (d.get("text") or "")[:6000],
                })
        for d in extra_documents or []:   # project-level / just-uploaded docs
            source_docs.append({
                "title": d.get("title") or d.get("name", ""),
                "doc_type": d.get("doc_type", ""),
                "text": (d.get("text") or "")[:6000],
            })
        # dedup by (title, first 200 chars)
        seen, deduped = set(), []
        for d in source_docs:
            k = (d["title"], d["text"][:200])
            if k not in seen:
                seen.add(k); deduped.append(d)
        source_docs = deduped
        # Prioritize so the budget is spent on the most authoritative docs:
        # author ground-truth notes first, then protocols, then everything else.
        def _prio(d):
            t = (d.get("title", "") + " " + d.get("doc_type", "")).lower()
            if any(k in t for k in ("ground-truth", "study notes", "cross_check",
                                    "arm assignment", "backbone", "library map",
                                    "gene panel")):
                return 0
            if d.get("doc_type") == "protocol":
                return 1
            if d.get("doc_type") == "background":
                return 2
            return 3
        source_docs.sort(key=_prio)
        prompt = self.load_prompt(
            "methods_agent.txt", project_name=project_name or "this study",
            style=style, length=length,
            experiments=json.dumps(slim, ensure_ascii=False)[:16000],
            source_documents=(json.dumps(source_docs, ensure_ascii=False)[:45000]
                              if source_docs else "(none provided)"),
        )
        try:
            md = self.call(prompt, max_tokens=3000, temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            return self.error(str(exc))
        return {"agent": self.name, "status": "success", "mode": "live",
                "markdown": _scrub(md), "timestamp": utc_timestamp()}

    # ------------------------------------------------------------------ #
    def _demo_methods(self, experiments: List[Dict[str, Any]], project_name: str) -> str:
        lines: List[str] = []
        lines.append(f"# Methods — {project_name or 'Project'}")
        lines.append("")
        lines.append("_Draft generated from recorded protocols. Replace every "
                     "\"(specify)\" with the exact value used, and verify against your "
                     "source protocol before submission._")
        lines.append("")
        worked = [e for e in experiments if e.get("status") == "worked"]
        used = worked or experiments
        for idx, e in enumerate(used, 1):
            proto = e.get("protocol", {})
            lines.append(f"## {idx}. {proto.get('protocol_title', e.get('title','Protocol'))}")
            if e.get("status"):
                lines.append(f"_Outcome on record: {e.get('status')}._"
                             + (f" {e.get('notes')}" if e.get("notes") else ""))
            lines.append("")
            # materials sentence
            mats = proto.get("materials", []) or []
            if mats:
                mtxt = "; ".join(
                    f"{m.get('item','')} ({_clean(m.get('amount'))}"
                    + (f", {m.get('vendor')}" if m.get('vendor') and CONFIRM not in str(m.get('vendor')) else "")
                    + (f", cat. {m.get('catalog_number')}" if m.get('catalog_number') and CONFIRM not in str(m.get('catalog_number')) else "")
                    + ")"
                    for m in mats
                )
                lines.append(f"**Materials.** {mtxt}.")
                lines.append("")
            # procedure as prose
            steps = proto.get("workflow", []) or []
            if steps:
                lines.append("**Procedure.** " + self._procedure_prose(steps))
                lines.append("")
            # QC
            qc = proto.get("qc_checkpoints", []) or []
            if qc:
                qtxt = " ".join(
                    f"{q.get('checkpoint_name','QC')} was assessed by "
                    f"{', '.join(q.get('measurements', [])) or 'standard measures'} "
                    f"(pass criteria: {', '.join(q.get('pass_criteria', [])) or 'as specified'})."
                    for q in qc
                )
                lines.append(f"**Quality control.** {qtxt}")
                lines.append("")
        lines.append("---")
        lines.append("_Generated by the Lab Experimental Agent (offline draft). "
                     "For a polished narrative, run with DEMO_MODE=false (Haiku)._")
        return "\n".join(lines)

    @staticmethod
    def _procedure_prose(steps: List[Dict[str, Any]]) -> str:
        sentences = []
        for s in steps:
            cond = s.get("conditions", {}) or {}
            bits = []
            instr = "; ".join(s.get("instructions", []) or []) or s.get("title", "")
            bits.append(instr.rstrip("."))
            extras = []
            if s.get("time_estimate") and CONFIRM not in str(s["time_estimate"]):
                extras.append(f"for {s['time_estimate']}")
            if cond.get("temperature") and CONFIRM not in str(cond["temperature"]):
                extras.append(f"at {cond['temperature']}")
            if cond.get("speed") and CONFIRM not in str(cond["speed"]):
                extras.append(f"({cond['speed']})")
            sentence = " ".join([bits[0]] + extras).strip()
            if sentence:
                sentences.append(sentence[0].upper() + sentence[1:] + ".")
        return " ".join(sentences)
