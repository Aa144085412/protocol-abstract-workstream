"""
reagent_placement
=================
Deterministic reagent-to-step validation. A parser often lists a reagent on the wrong step
(packaging plasmids psPAX2/pMD2.G on a *sequencing* step; a restriction enzyme on a *plating*
step). This classifies each reagent by KIND and each step by INTENT, and:

  - leaves a reagent alone if the step text names it, or its kind fits the step's intent;
  - else RELOCATES it to the step whose intent fits (de-duplicating);
  - if no fitting step exists, FLAGS it for the user.

It never invents reagents — it only moves/flags ones already present. Conservative: only
reagents whose kind is recognised are ever touched.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# --- reagent KIND -> recognising keywords (lowercase substring) ------------- #
_RESTRICTION = ("nhei", "pcii", "ecori", "bamhi", "hindiii", "xhoi", "noti", "ncoi", "xbai",
                "sali", "kpni", "saci", "spei", "psti", "bglii", "agei", "mlui", "bsrgi",
                "ecorv", "smai", "apai", "asci", "paci", "mfei", "bsmbi", "bsai", "esp3i",
                "restriction enzyme")
KIND_KW: Dict[str, tuple] = {
    "packaging_plasmid": ("pspax", "pmd2", "vsv-g", "vsvg", "pmdlg", "prre", "prev",
                          "packaging plasmid", "envelope plasmid"),
    "restriction_enzyme": _RESTRICTION,
    "ligase": ("ligase", "nebuilder", "gibson", "hifi assembly", "golden gate"),
    "phosphatase": ("rsap", "shrimp alkaline phosphatase", "antarctic phosphatase",
                    "calf intestinal", " cip"),
    "polymerase": ("polymerase", "q5", "phusion", " taq", "kapa", "platinum superfi"),
    "antibody": ("antibody", "anti-", " igg", "primary ab", "secondary ab"),
    "transfection_enhancer": ("polybrene", "protamine", "lipofectamine", "fugene", " pei"),
    "competent_cells": ("competent cells", "10-beta", "stbl", "dh5", "top10", "electrocompetent"),
    "selection_antibiotic": ("ampicillin", "kanamycin", "carbenicillin", "chloramphenicol",
                             "spectinomycin", "puromycin", "blasticidin", "hygromycin",
                             "geneticin", "g418"),
}

# --- step INTENT -> recognising keywords ------------------------------------ #
INTENT_KW: Dict[str, tuple] = {
    "pcr": ("pcr", "amplif"),
    "digest": ("digest", "restriction", "linearize"),
    "ligate": ("ligat", "assembly", "gibson", "nebuilder", "golden gate"),
    "transform": ("transform", "electroporat", "competent", "heat shock", "outgrowth", "recovery"),
    "plate": ("plate", "lb-amp", "agar", "colony", "colonies", "spread"),
    "miniprep": ("miniprep", "midiprep", "plasmid prep", "grow culture", "pick colon"),
    "sequence": ("sanger", "sequenc", "colony pcr"),
    "virus_prod": ("transfect", "packag", "harvest", "supernatant", "lenti-x", "produce virus",
                   "hek293", "viral"),
    "transduce": ("transduc", "infect", "polybrene", " moi"),
    "validate": ("western", "blot", "facs", "flow cytom", "immunoblot", "validate", "expression"),
    "culture": ("seed", "passage", "grow cells", "maintain"),
    "gel": ("gel", "electrophoresis", "excise", "extraction"),
}

# --- which step intents each reagent KIND legitimately belongs to ----------- #
ALLOWED: Dict[str, set] = {
    "packaging_plasmid": {"virus_prod"},
    "restriction_enzyme": {"digest"},
    "ligase": {"ligate"},
    "phosphatase": {"digest"},
    "polymerase": {"pcr"},
    "antibody": {"validate"},
    "transfection_enhancer": {"transduce", "virus_prod"},
    "competent_cells": {"transform"},
    "selection_antibiotic": {"plate", "miniprep", "transform", "culture"},
}


def reagent_kind(name: str) -> Optional[str]:
    it = str(name or "").lower()
    for kind, kws in KIND_KW.items():
        if any(k in it for k in kws):
            return kind
    return None


def step_intents(step: Dict[str, Any]) -> set:
    text = (str(step.get("title", "")) + " "
            + " ".join(str(i) for i in step.get("instructions", []) or [])).lower()
    return {intent for intent, kws in INTENT_KW.items() if any(k in text for k in kws)}


# generic words that must NOT count as "the step names this reagent" (too common)
_GENERIC = {"dna", "rna", "the", "and", "for", "kit", "plasmid", "plasmids", "lentivirus",
            "lentiviral", "vector", "vectors", "cell", "cells", "buffer", "reagent", "reagents",
            "enzyme", "enzymes", "gene", "genes", "protein", "mix", "solution", "medium", "media",
            "water", "with", "from", "into", "construct", "constructs", "insert", "inserts"}


def _names_in_text(step: Dict[str, Any], name: str) -> bool:
    text = (str(step.get("title", "")) + " "
            + " ".join(str(i) for i in step.get("instructions", []) or [])).lower()
    # require a DISTINCTIVE token (e.g. 'pspax2', 'nhei') to appear as a whole word — generic
    # words like 'plasmid'/'cells' don't count as naming the specific reagent.
    toks = [t for t in re.split(r"[^a-z0-9]+", str(name).lower())
            if len(t) > 2 and t not in _GENERIC]
    return any(re.search(r"\b" + re.escape(t) + r"\b", text) for t in toks)


def detect(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return [{item, kind, from_step_id, from_title, suggested_step_id, suggested_title}]
    for reagents that don't belong on their step (and where they should go, if known)."""
    wf = proto.get("workflow", []) or []
    intents = [step_intents(s) for s in wf]
    out: List[Dict[str, Any]] = []
    for si, s in enumerate(wf):
        for r in s.get("reagents", []) or []:
            name = r.get("item", "")
            kind = reagent_kind(name)
            if not kind:
                continue
            if _names_in_text(s, name):
                continue                      # the step explicitly uses it -> fine
            if intents[si] & ALLOWED.get(kind, set()):
                continue                      # kind fits this step's intent -> fine
            # misplaced — find a target step whose intent fits the kind
            target = next((tj for tj, it in enumerate(intents)
                           if it & ALLOWED.get(kind, set())), None)
            out.append({
                "item": name, "kind": kind,
                "from_step_id": s.get("step_id"), "from_title": s.get("title", ""),
                "suggested_step_id": (wf[target].get("step_id") if target is not None else None),
                "suggested_title": (wf[target].get("title", "") if target is not None else None),
            })
    return out


def apply(proto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Relocate misplaced reagents to the fitting step (de-duplicated); flag the rest. In place.
    Returns [{item, action, from_title, to_title}] for logging / the UI."""
    wf = proto.get("workflow", []) or []
    by_id = {s.get("step_id"): s for s in wf}
    changes: List[Dict[str, Any]] = []
    for d in detect(proto):
        src = by_id.get(d["from_step_id"])
        if not src:
            continue
        # remove the misplaced reagent from the source step
        src_reags = src.get("reagents", []) or []
        moved = next((r for r in src_reags if r.get("item") == d["item"]), None)
        if moved is None:
            continue
        tgt = by_id.get(d["suggested_step_id"])
        if tgt is not None:
            src["reagents"] = [r for r in src_reags if r is not moved]
            tgt.setdefault("reagents", [])
            if not any(r.get("item") == d["item"] for r in tgt["reagents"]):
                tgt["reagents"].append(moved)
            changes.append({"item": d["item"], "action": "moved",
                            "from_title": d["from_title"], "to_title": d["suggested_title"]})
        else:
            # no fitting step — leave it but flag for the user
            note = (f"'{d['item']}' ({d['kind'].replace('_',' ')}) doesn't fit this step — "
                    "check whether it belongs here.")
            src.setdefault("human_review_required", [])
            if note not in src["human_review_required"]:
                src["human_review_required"].append(note)
            changes.append({"item": d["item"], "action": "flagged",
                            "from_title": d["from_title"], "to_title": None})
    return changes
