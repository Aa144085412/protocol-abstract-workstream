"""
typical_values
==============
A deterministic, local knowledge base of TYPICAL lab values — given as RANGES with a
typical default and a short rationale, never as gold-standard absolutes. It exists so
that when a protocol leaves a value as "[confirm with source protocol]", the tool can
SUGGEST a sensible range (e.g. spin mammalian cells 300–500 × g; bacteria 3000–4000 × g;
after trypsin, gentler 200–300 × g) instead of just nagging.

Every suggestion is explicitly a SUGGESTION to confirm — these are starting points from
common practice, not values read from the user's source protocol. No model calls here.

Each suggestion dict:
  {kind, label, low, high, typical, unit, rationale, confidence: "suggestion"}
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _s(kind, label, low, high, typical, unit, rationale) -> Dict[str, Any]:
    # source = "reference": an auditable, deterministic rule from common practice
    # (NOT read from the user's protocol, NOT a model guess). Fully traceable.
    return {"kind": kind, "label": label, "low": low, "high": high, "typical": typical,
            "unit": unit, "rationale": rationale, "confidence": "suggestion",
            "source": "reference"}


# --------------------------------------------------------------------------- #
# Centrifugation — the user's core example: speed depends on what you're spinning
# and how delicate it is. Always × g (RCF), not rpm (rpm depends on rotor radius).
# --------------------------------------------------------------------------- #
def _centrifugation(txt: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    bacteria = any(k in txt for k in ("bacteri", "e. coli", "e.coli", "coli", "neb10",
                                      "dh5", "stbl", "overnight culture", "ldb", "lb culture",
                                      "miniprep", "plasmid prep", "colony"))
    yeast = "yeast" in txt or "s. cerevisiae" in txt
    debris = any(k in txt for k in ("debris", "precipitat", "insoluble", "max speed",
                                    "maximum speed", "microcentrifuge at full"))
    nuclei = "nuclei" in txt or "nuclear pellet" in txt
    after_trypsin = any(k in txt for k in ("trypsin", "tryple", "accutase", "detach",
                                           "dissociat", "single cell suspension"))
    fragile = any(k in txt for k in ("primary", "stem cell", "ipsc", "neuron", "delicate",
                                     "fragile", "gentle", "post-sort", "fixed cell"))
    mammalian = any(k in txt for k in ("cell", "k562", "hek", "mcf", "jurkat", "hela",
                                       "pbmc", "lymphocyte", "media", "pellet the cells",
                                       "resuspend the cells"))

    if bacteria:
        out.append(_s("centrifugation", "Bacterial pellet (E. coli)", 3000, 4000, 3220, "× g",
                      "Bacteria are robust: ~3000–4000 × g for 10 min (4°C) pellets them without "
                      "smearing. ~3220 × g ≈ 4000 rpm in a typical benchtop rotor."))
    elif yeast:
        out.append(_s("centrifugation", "Yeast pellet", 1000, 3000, 1500, "× g",
                      "Yeast: ~1000–3000 × g for 5 min."))
    elif debris:
        out.append(_s("centrifugation", "Clear debris / precipitate", 12000, 20000, 16000, "× g",
                      "Pelleting debris/precipitate (not living cells): ≥12,000 × g."))
    elif nuclei:
        out.append(_s("centrifugation", "Nuclei pellet", 500, 1000, 600, "× g",
                      "Nuclei: ~500–1000 × g for 5 min, 4°C; gentler than debris to avoid lysis."))
    elif mammalian or after_trypsin or fragile:
        if fragile:
            out.append(_s("centrifugation", "Fragile / primary cells", 200, 300, 250, "× g",
                          "Primary/stem/post-sort/fixed cells are fragile: 200–300 × g, 3–5 min, "
                          "low brake. Higher g lyses or stresses them."))
        elif after_trypsin:
            out.append(_s("centrifugation", "Cells after trypsin/dissociation", 200, 300, 300, "× g",
                          "Freshly dissociated/trypsinized cells are more fragile: 200–300 × g "
                          "(vs ~500 × g for hardy lines). 3–5 min."))
        else:
            out.append(_s("centrifugation", "Mammalian cells (standard)", 300, 500, 400, "× g",
                          "Suspension/hardy mammalian lines (K562, HEK, etc.): 300–500 × g for 5 min. "
                          "300 × g is gentle, 500 × g firmer pellet."))
        out.append(_s("centrifugation", "Spin time / temperature", 3, 5, 5, "min @ 4°C",
                      "5 min is standard; 3 min if gentle. 4°C if cells will be lysed/kept cold, "
                      "RT if going back to culture."))
    else:
        out.append(_s("centrifugation", "Generic spin (specify what's pelleted)", 300, 4000, 500, "× g",
                      "Depends on sample: mammalian cells 300–500 × g, bacteria 3000–4000 × g, "
                      "debris ≥12,000 × g. Name the sample to narrow it."))
    return out


# --------------------------------------------------------------------------- #
# PCR — temperatures are mostly determined by chemistry, not the user's lab.
# --------------------------------------------------------------------------- #
def _pcr(txt: str) -> List[Dict[str, Any]]:
    return [
        _s("pcr", "Initial denaturation", 95, 98, 98, "°C, 30 s–3 min",
           "98°C for high-fidelity polymerases (Q5/Phusion), 95°C for Taq."),
        _s("pcr", "Denaturation (per cycle)", 95, 98, 98, "°C, 10 s",
           "Keep short (10 s for Q5/Phusion, 15–30 s for Taq)."),
        _s("pcr", "Annealing temperature", 55, 65, 60, "°C, 15–30 s",
           "≈ primer Tm − 5°C. Compute from your primers; 60°C is a common start. "
           "For Q5, anneal can be near Tm. Run a gradient if unsure."),
        _s("pcr", "Extension", 72, 72, 72, "°C",
           "72°C. Time ≈ 1 min/kb for Taq; 15–30 s/kb for Q5/Phusion."),
        _s("pcr", "Final extension", 72, 72, 72, "°C, 2–5 min",
           "2 min (Q5) to 5 min (Taq, for A-tailing)."),
        _s("pcr", "Cycle number", 25, 35, 30, "cycles",
           "25–30 for plasmid template, up to 35 for low-input/genomic."),
    ]


# --------------------------------------------------------------------------- #
# Ligation & restriction digest & Gibson — molecular cloning ratios.
# --------------------------------------------------------------------------- #
def _ligation(txt: str) -> List[Dict[str, Any]]:
    blunt = "blunt" in txt
    return [
        _s("ligation", "Insert : vector molar ratio", 1, 7, 3, ": 1 (insert : vector)",
           ("Blunt-end: 5:1–7:1." if blunt else "Cohesive/sticky-end: 3:1 typical (range 1:1–7:1). ")
           + " Use NEBioCalculator to convert ng↔pmol by fragment length."),
        _s("ligation", "Total DNA (insert + vector)", 50, 100, 100, "ng",
           "~50–100 ng vector with insert at the molar ratio above in a 10–20 µL reaction."),
        _s("ligation", "T4 ligase incubation", 10, 16, 16, "min RT  /  °C overnight",
           "Quick: RT 10 min. Best yield: 16°C overnight. Heat-inactivate 65°C 10 min."),
    ]


def _digest(txt: str) -> List[Dict[str, Any]]:
    golden = any(k in txt for k in ("golden gate", "bsmbi", "bsai", "esp3i", "bbsi"))
    out = [
        _s("digest", "Enzyme amount per µg DNA", 5, 10, 10, "U/µg",
           "5–10 U per µg DNA for a 1 h digest. 1 U cuts 1 µg in 1 h at the enzyme's temp."),
        _s("digest", "Enzyme volume vs reaction", 1, 10, 10, "% of reaction (max)",
           "Keep enzyme ≤10% of reaction volume — glycerol carryover causes star activity."),
        _s("digest", "Digest time / temp", 1, 16, 1, "h @ 37°C (enzyme-dependent)",
           "1 h standard (37°C for most); some need other temps. Check NEB for star-activity risk."),
    ]
    if golden:
        out.append(_s("digest", "Golden Gate cycling", 16, 37, 37, "°C (cycle 37↔16)",
                      "Type IIS (BsmBI/BsaI): cycle 37°C (cut) ↔ 16°C (ligate) ×20–30, then "
                      "37°C 5 min, 60°C 5 min (heat-kill). Use T4 ligase + the enzyme together."))
    return out


def _gibson(txt: str) -> List[Dict[str, Any]]:
    return [
        _s("assembly", "Fragment amount (Gibson/HiFi)", 0.02, 0.5, 0.1, "pmol total",
           "0.02–0.5 pmol of fragments (2–3 fragments: ~0.05 pmol each, equimolar; "
           "more fragments → lower each)."),
        _s("assembly", "Incubation", 15, 60, 60, "min @ 50°C",
           "50°C for 15 min (2–3 fragments) up to 60 min (4–6 fragments)."),
    ]


def _transformation(txt: str) -> List[Dict[str, Any]]:
    return [
        _s("transformation", "Heat shock", 30, 45, 42, "s @ 42°C",
           "42°C for 30–45 s (chemically competent), then back on ice 2 min."),
        _s("transformation", "Recovery", 30, 60, 60, "min @ 37°C, 250 rpm in SOC",
           "Outgrow in SOC at 37°C, ~1 h shaking — needed for antibiotic resistance to express."),
    ]


# --------------------------------------------------------------------------- #
# Routine cell-culture defaults (common-practice; always labeled as suggestions)
# --------------------------------------------------------------------------- #
def _culture(txt: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    mammalian = any(k in txt for k in (
        "mcf", "hek", "k562", "hela", "u2os", "293", "mammalian", "adherent",
        "dmem", "rpmi", "fbs", "cell line", "cells", "culture"))
    if mammalian and any(k in txt for k in ("incubat", "culture", "grow", "recover", "plate", "seed")):
        out.append(_s("culture", "Mammalian incubation", 37, 37, 37, "°C",
                      "Standard mammalian adherent culture: 37 °C, 5% CO2 humidified incubator."))
    return out


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def suggest_for_text(text: str) -> List[Dict[str, Any]]:
    """Return typical-value suggestions relevant to a step's text (title+instructions)."""
    txt = (text or "").lower()
    out: List[Dict[str, Any]] = []
    if any(k in txt for k in ("spin", "centrifug", "pellet", "rcf", "× g", "x g", "rpm")):
        out += _centrifugation(txt)
    if any(k in txt for k in ("incubat", "culture", "grow", "recover", "plate", "seed")):
        out += _culture(txt)
    if "pcr" in txt or "amplif" in txt or "thermocycl" in txt or "anneal" in txt:
        out += _pcr(txt)
    if "ligat" in txt or "ligase" in txt:
        out += _ligation(txt)
    if any(k in txt for k in ("digest", "restriction", "bsmbi", "bsai", "ecori", "bamhi",
                              "golden gate")):
        out += _digest(txt)
    if "gibson" in txt or "hifi assembly" in txt or "in-fusion" in txt:
        out += _gibson(txt)
    if any(k in txt for k in ("transform", "heat shock", "electroporat", "competent cell")):
        out += _transformation(txt)
    return out


def suggest_for_query(query: str) -> List[Dict[str, Any]]:
    """Free-text helper, e.g. 'spin down K562 after trypsin' or 'ligation ratio'."""
    return suggest_for_text(query) or [_s(
        "general", "No specific match", None, None, None, "",
        "No built-in typical value matched. Try naming the operation and sample "
        "(e.g. 'spin mammalian cells', 'PCR annealing', 'ligation molar ratio').")]


def format_suggestion(s: Dict[str, Any]) -> str:
    """One-line human-readable rendering of a suggestion."""
    if s.get("low") is None:
        rng = ""
    elif s.get("low") == s.get("high"):
        rng = f"{s['low']} {s.get('unit','')}".strip()
    else:
        rng = f"{s['low']}–{s['high']} {s.get('unit','')}".strip()
    typ = f" (typical {s['typical']})" if s.get("typical") not in (None, s.get("low")) else ""
    return f"{s.get('label','')}: {rng}{typ}"
