"""
flow_check
==========
Deterministic experimental-LOGIC review. Where the rest of the app fills values, this
asks whether the *steps connect* — does each stage's input come from a prior stage's
output, and are the enabling steps present? It encodes a handful of high-value molecular-
biology flow rules so the tool stops "just filling steps" and flags the gaps a thinking
bench scientist would catch:

  - ligation without a step that DIGESTS THE VECTOR (you can't ligate into an uncut vector)
  - transduction/infection without LENTIVIRUS PRODUCTION (transfect packaging cells →
    harvest → concentrate) before it
  - transduction that adds the cloning PLASMID/VECTOR instead of harvested virus
  - a VALIDATION step (Western / FACS) that isn't actually designed (no antibody, no
    sample prep, no expected result)
  - downstream use of a construct with no SEQUENCE VERIFICATION after miniprep

Flags only — it never edits the protocol. Pairs with the AI improve pass, which can turn
a flag into the missing step.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _text(step: Dict[str, Any]) -> str:
    return (str(step.get("title", "")) + " "
            + " ".join(str(i) for i in step.get("instructions", []) or []) + " "
            + " ".join(str(r.get("item", "")) for r in step.get("reagents", []) or [])
            ).lower()


def _any(steps_text: List[str], *kw: str) -> bool:
    return any(any(k in t for k in kw) for t in steps_text)


def detect(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return [{issue, fix, where}] for experimental-logic gaps. Empty = no gaps found."""
    wf = proto.get("workflow", []) or []
    if not wf:
        return []
    texts = [_text(s) for s in wf]
    title_of = {i: (wf[i].get("title") or f"step {i+1}") for i in range(len(wf))}
    out: List[Dict[str, Any]] = []

    has_ligation = _any(texts, "ligat")
    has_transduce = _any(texts, "transduc", "infect", "polybrene", " moi")
    has_virus_prod = _any(texts, "transfect", "packaging", "pspax", "pmd2", "psp", "envelope",
                          "harvest", "viral supernatant", "produce virus", "lenti-x", "concentrator")
    has_seq = _any(texts, "sanger", "sequenc", "sequence-verif", "verify the sequence", "colony pcr")
    has_miniprep = _any(texts, "miniprep", "midiprep", "plasmid prep")

    # 1) ligation but the vector was never digested
    if has_ligation:
        # a real digest step (not the ligation step's "cut vector" wording) that acts on the vector
        vector_digested = any(("digest" in t or "restrict" in t or "linearize" in t)
                              and "ligat" not in t
                              and ("vector" in t or "backbone" in t or "plasmid" in t)
                              for t in texts)
        if not vector_digested:
            i = next((j for j, t in enumerate(texts) if "ligat" in t), 0)
            out.append({
                "kind": "vector_digest", "anchor_idx": i, "insert": "before",
                "issue": "Ligation step has no matching VECTOR digestion — you can't ligate an "
                         "insert into an uncut vector.",
                "fix": "Add a step that digests the vector/backbone with the SAME enzymes (and "
                       "dephosphorylates it, e.g. rSAP) before ligation.",
                "where": title_of[i]})

    # 2) transduction without virus production beforehand
    if has_transduce and not has_virus_prod:
        i = next((j for j, t in enumerate(texts) if any(k in t for k in
                 ("transduc", "infect", "polybrene"))), len(wf) - 1)
        out.append({
            "kind": "virus_prod", "anchor_idx": i, "insert": "before",
            "issue": "Transduction/infection step but no LENTIVIRUS PRODUCTION beforehand — there "
                     "is no virus to add yet.",
            "fix": "Insert virus production before transduction: transfect packaging cells "
                   "(e.g. HEK293T with transfer plasmid + psPAX2 + pMD2.G), harvest the viral "
                   "supernatant, then (optionally) concentrate it.",
            "where": title_of[i]})

    # 3) transduction adds the cloning plasmid/vector instead of harvested virus
    for j, s in enumerate(wf):
        t = texts[j]
        if not any(k in t for k in ("transduc", "infect", "polybrene")):
            continue
        reagent_items = " ".join(str(r.get("item", "")) for r in s.get("reagents", []) or []).lower()
        if ("vector" in reagent_items or "plasmid" in reagent_items) and "virus" not in reagent_items:
            out.append({
                "kind": "wrong_input", "anchor_idx": j, "insert": "flag",
                "issue": "Transduction step lists the cloning VECTOR/PLASMID as the input, not the "
                         "harvested virus — the input flow is wrong.",
                "fix": "The input to transduction should be the (concentrated) viral supernatant "
                       "produced from the sequence-verified construct, not the plasmid itself.",
                "where": title_of[j]})
            break

    # 4) validation step (Western/FACS) that isn't actually designed
    for j, s in enumerate(wf):
        t = texts[j]
        if not any(k in t for k in ("western", "blot", "facs", "flow cytom", "immunoblot")):
            continue
        has_reagents = bool(s.get("reagents"))
        has_detail = any(k in t for k in ("antibody", "anti-", "lysis", "lyse", "sds-page",
                                          "gel", "kda", "dilution", "1:"))
        if not (has_reagents and has_detail):
            out.append({
                "kind": "validation_undesigned", "anchor_idx": j, "insert": "augment",
                "issue": f"'{title_of[j]}' names a validation assay but isn't designed — no "
                         "antibody, sample prep, or expected result.",
                "fix": "Design the assay: antibody (e.g. anti-mCherry/anti-tag) + dilution, lysis "
                       "& sample prep, gel %, and the EXPECTED result per condition (e.g. band "
                       "size: free reporter vs larger uncleaved fusion).",
                "where": title_of[j]})
            break

    # 5) downstream use of the construct with no sequence verification
    if has_miniprep and (has_transduce or has_virus_prod) and not has_seq:
        i = next((j for j, t in enumerate(texts) if "miniprep" in t or "plasmid prep" in t), 0)
        out.append({
            "kind": "seq_verify", "anchor_idx": i, "insert": "after",
            "issue": "Construct is used downstream (virus/transduction) without SEQUENCE "
                     "VERIFICATION after miniprep.",
            "fix": "Add Sanger sequencing (or colony PCR + sequencing) to confirm correct insertion "
                   "before producing virus or transducing cells.",
            "where": title_of[i]})

    return out


# --------------------------------------------------------------------------- #
# Auto-repair: turn detected gaps into drafted steps, run during parse → design
# --------------------------------------------------------------------------- #
CONFIRM = "[confirm with source protocol]"


def _scaffold(kind: str) -> Dict[str, Any]:
    """A drafted step for an insertable gap. Conditions left to confirm; flagged for review
    and marked auto-added so the user knows the agent reasoned it in (not from the source)."""
    specs = {
        "vector_digest": (
            "Digest and dephosphorylate the vector",
            "To linearize the vector with the same enzymes as the inserts so the inserts can ligate in.",
            ["Digest the vector/backbone with the SAME restriction enzymes used for the inserts.",
             "Dephosphorylate the linearized vector (e.g. rSAP) to prevent re-circularization.",
             "Heat-inactivate or column/gel clean-up the cut, dephosphorylated vector."],
            {"temperature": "37 °C", "speed": "", "other": ""}),
        "virus_prod": (
            "Produce and harvest lentivirus",
            "To generate the virus that will be used to transduce the target cells.",
            ["Transfect packaging cells (e.g. HEK293T) with transfer plasmid + psPAX2 + pMD2.G.",
             "Replace medium 6–16 h post-transfection; harvest viral supernatant at 48 and 72 h.",
             "Filter through 0.45 µm and concentrate (e.g. Lenti-X Concentrator); titre if possible."],
            {"temperature": "37 °C", "speed": "", "other": ""}),
        "seq_verify": (
            "Sequence-verify the construct",
            "To confirm the insert is present, correct, and in-frame before downstream use.",
            ["Sanger sequence the miniprep across the insert and both junctions (or colony PCR + sequencing).",
             "Align to the expected construct; proceed only with fully correct clones."],
            {"temperature": "", "speed": "", "other": ""}),
    }
    title, purpose, instr, cond = specs[kind]
    return {"step_id": None, "step_number": None, "title": title, "purpose": purpose,
            "instructions": instr, "time_estimate": CONFIRM, "conditions": cond,
            "reagents": [], "expected_observation": "", "checkpoint": "",
            "pause_point": False,
            "human_review_required": ["Auto-added to close a logic gap — confirm details against your source."],
            "troubleshooting": [],
            "notes": ["Auto-added by the logic/flow check (reasoned, not from the source) — review & edit."]}


_VALIDATION_DESIGN = [
    "Lyse the cells and run SDS-PAGE.",
    "Immunoblot with an antibody against the reporter/tag (e.g. anti-mCherry).",
    "Compare band size across conditions — a self-cleaving (WT) construct gives free reporter; "
    "a cleavage-dead mutant gives a single LARGER uncleaved fusion.",
]


def apply_fixes(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Insert/augment the missing steps for detected gaps, in place. Runs during generation
    so the protocol that reaches Design is already logically connected. Renumbers steps and
    clears the (not-yet-built) uncertainty registry so it re-enumerates over the new steps.
    Returns a list of {kind, title, action} for logging/notes."""
    wf = proto.get("workflow", []) or []
    if not wf:
        return []
    gaps = detect(proto)
    if not gaps:
        return []
    changes: List[Dict[str, Any]] = []
    # work back-to-front so earlier anchor indices stay valid as we insert
    for g in sorted(gaps, key=lambda x: x.get("anchor_idx", 0), reverse=True):
        kind, idx, mode = g.get("kind"), g.get("anchor_idx", 0), g.get("insert")
        if mode in ("before", "after") and kind in ("vector_digest", "virus_prod", "seq_verify"):
            step = _scaffold(kind)
            at = idx if mode == "before" else idx + 1
            wf.insert(at, step)
            changes.append({"kind": kind, "title": step["title"], "action": f"inserted {mode} step {idx+1}"})
        elif mode == "augment" and kind == "validation_undesigned" and 0 <= idx < len(wf):
            s = wf[idx]
            instr = list(s.get("instructions", []) or [])
            for line in _VALIDATION_DESIGN:
                if line not in instr:
                    instr.append(line)
            s["instructions"] = instr
            if not s.get("expected_observation"):
                s["expected_observation"] = ("Reporter detected at expected size; size shift "
                                             "distinguishes the conditions (e.g. WT vs mutant).")
            s.setdefault("human_review_required", []).append(
                "Validation assay drafted by the logic check — set antibody, dilution and expected sizes.")
            changes.append({"kind": kind, "title": s.get("title", ""), "action": "designed validation in place"})
        elif mode == "flag" and kind == "wrong_input" and 0 <= idx < len(wf):
            s = wf[idx]
            s.setdefault("human_review_required", []).append(
                "Input flow: transduce with the harvested VIRUS, not the cloning plasmid/vector.")
            oq = proto.setdefault("open_questions_for_human", [])
            note = "[Logic] " + g["issue"] + " " + g["fix"]
            if note not in oq:
                oq.append(note)
            changes.append({"kind": kind, "title": s.get("title", ""), "action": "flagged wrong input"})
    if not changes:
        return []
    # renumber by position; reassign step_ids (safe: registry is rebuilt below)
    for i, s in enumerate(wf, 1):
        s["step_number"] = i
        s["step_id"] = f"step_{i:02d}"
    proto["workflow"] = wf
    proto.pop("uncertainty", None)   # force a fresh enumeration over the new step set
    return changes
