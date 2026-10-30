"""
sequence_scan
=============
Find DNA/oligo sequences embedded in an uploaded document (a Twist order, a primer list,
a gene-fragment spec, a FASTA block) and capture them with a label — so the tool keeps the
actual sequences the experiment depends on (WT/Mut inserts, primers) instead of dropping
them when the protocol is parsed into structured steps.

Deterministic, stdlib only. Handles: FASTA (>header + multiline), "Name: ACGT…" inline,
and labelled multi-line sequence blocks. A label is the FASTA header or the nearest
preceding text line.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_DNA = set("ACGTUN")


def _seq_chars(line: str, minlen: int = 10) -> bool:
    """True if the line is 'mostly nucleotides' and at least minlen long (used for gathering
    multi-line FASTA where each wrapped line can be short)."""
    s = re.sub(r"[\s\d]", "", line).upper()
    if len(s) < minlen:
        return False
    good = sum(1 for c in s if c in _DNA)
    return good / len(s) >= 0.9


def _is_seq_line(line: str) -> bool:
    return _seq_chars(line, minlen=15)


def _clean(seq: str) -> str:
    return re.sub(r"[^ACGTUN]", "", seq.upper())


def _kind(label: str, seq: str) -> str:
    lab = (label or "").lower()
    if any(k in lab for k in ("primer", "fwd", "rev", "forward", "reverse", "_f", "_r", " f ", " r ")):
        return "primer"
    n = len(seq)
    if n <= 60:
        return "oligo / primer"
    if n <= 300:
        return "oligo / gBlock"
    return "dsDNA / gene fragment"


def scan(text: str) -> List[Dict[str, Any]]:
    """Return [{label, sequence, length, kind}] for sequences found in the text."""
    if not text:
        return []
    out: List[Dict[str, Any]] = []
    lines = str(text).splitlines()

    # 1) inline "Label: ACGT..." (sequence on the same line as its name)
    for ln in lines:
        m = re.match(r"\s*([^:>\t]{1,60}?)\s*[:\t]\s*([ACGTUNacgtun\s]{15,})\s*$", ln)
        if m and _is_seq_line(m.group(2)):
            seq = _clean(m.group(2))
            if len(seq) >= 15:
                out.append({"label": m.group(1).strip(), "sequence": seq,
                            "length": len(seq), "kind": _kind(m.group(1), seq)})

    # 2) FASTA / labelled blocks: a header or text line, then sequence line(s)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _seq_chars(ln) and not re.search(r"[:\t]", ln):   # not already caught inline
            # gather the contiguous run of sequence lines (each may be short when wrapped)
            j = i
            buf = []
            while j < len(lines) and _seq_chars(lines[j]) and not re.search(r"[:\t]", lines[j]):
                buf.append(lines[j])
                j += 1
            seq = _clean("".join(buf))
            # label = nearest preceding non-empty line that is itself TEXT (not another
            # sequence fragment), FASTA '>' stripped
            label = ""
            k = i - 1
            while k >= 0:
                prev = lines[k].strip()
                if prev and not _seq_chars(prev):
                    label = prev.lstrip(">").strip()
                    break
                k -= 1
            if len(seq) >= 15:
                out.append({"label": label, "sequence": seq, "length": len(seq),
                            "kind": _kind(label, seq)})
            i = j
        else:
            i += 1

    # de-duplicate by sequence (keep the first / most-labelled)
    seen, uniq = set(), []
    for s in out:
        key = s["sequence"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq


def scan_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scan a list of source documents ({text, title/name}) and tag each hit with its source."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for d in docs or []:
        for s in scan(d.get("text", "") or ""):
            if s["sequence"] in seen:
                continue
            seen.add(s["sequence"])
            s = dict(s)
            s["source"] = d.get("title") or d.get("name", "")
            out.append(s)
    return out


def _tokens(s: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if len(t) > 2}


def attach_to_materials(proto: Dict[str, Any], sequences: List[Dict[str, Any]]) -> int:
    """Attach each captured sequence to the material whose name best matches its label
    (token overlap). Stores proto['sequences'] (all) and a per-material 'sequence'. Returns
    how many were attached to a material."""
    proto["sequences"] = sequences
    mats = proto.get("materials", []) or []
    n = 0
    for s in sequences:
        lab_tok = _tokens(s.get("label", ""))
        best, best_score = None, 0
        for m in mats:
            score = len(lab_tok & _tokens(m.get("item", "")))
            if score > best_score:
                best, best_score = m, score
        if best is not None and best_score >= 1:
            best["sequence"] = s["sequence"]
            note = f"Sequence captured from upload ({s['length']} bp, {s['kind']})."
            best["notes"] = (str(best.get("notes", "")).strip() + " " + note).strip()
            n += 1
    return n
