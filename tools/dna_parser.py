"""
dna_parser
==========
Read SnapGene ``.dna`` plasmid maps WITHOUT any third-party dependency (pure stdlib), so
the tool can reason about a real construct: its sequence, topology (circular/linear),
annotated features (genes, promoters, tags, ORFs), primers, and which common restriction
enzymes cut it (and where). This lets the design/assay logic be concrete — e.g. pick a
unique cutter for cloning, confirm an insert/junction, or identify a reporter/tag.

SnapGene .dna is an undocumented binary of length-prefixed blocks:
    [1 byte block type][4 byte big-endian length][payload]
  - type 0  : DNA — payload[0] = flags (bit0 = circular), payload[1:] = ASCII sequence
  - type 5  : primers   (XML)
  - type 6  : notes     (XML)
  - type 10 : features  (XML)
We read tolerantly and skip anything we don't recognise.
"""

from __future__ import annotations

import re
import struct
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

# common cloning/screening enzymes -> recognition site (5'->3')
COMMON_ENZYMES: Dict[str, str] = {
    "EcoRI": "GAATTC", "BamHI": "GGATCC", "HindIII": "AAGCTT", "XhoI": "CTCGAG",
    "NotI": "GCGGCCGC", "NheI": "GCTAGC", "PciI": "ACATGT", "NcoI": "CCATGG",
    "XbaI": "TCTAGA", "SalI": "GTCGAC", "KpnI": "GGTACC", "SacI": "GAGCTC",
    "SpeI": "ACTAGT", "PstI": "CTGCAG", "BglII": "AGATCT", "AgeI": "ACCGGT",
    "MluI": "ACGCGT", "BsrGI": "TGTACA", "EcoRV": "GATATC", "SmaI": "CCCGGG",
    "ApaI": "GGGCCC", "AscI": "GGCGCGCC", "PacI": "TTAATTAA", "MfeI": "CAATTG",
}


def _blocks(raw: bytes):
    """Yield (block_type, payload) for each length-prefixed block."""
    i, n = 0, len(raw)
    while i + 5 <= n:
        btype = raw[i]
        (size,) = struct.unpack_from(">I", raw, i + 1)
        start = i + 5
        end = start + size
        if end > n:
            break
        yield btype, raw[start:end]
        i = end


def is_snapgene(raw: bytes) -> bool:
    return bool(raw) and raw[0] == 9 and b"SnapGene" in raw[:64]


def _xml(payload: bytes) -> Optional[ET.Element]:
    try:
        return ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return None


def parse_snapgene(raw: bytes) -> Dict[str, Any]:
    """Return {name, length, topology, sequence, features[], primers[], description}."""
    seq, circular = "", False
    features: List[Dict[str, Any]] = []
    primers: List[Dict[str, Any]] = []
    description = ""
    name = ""

    for btype, payload in _blocks(raw):
        if btype == 0 and payload:                       # DNA sequence
            circular = bool(payload[0] & 1)
            seq = re.sub(r"[^A-Za-z]", "", payload[1:].decode("ascii", errors="replace")).upper()
        elif btype == 10:                                # features
            root = _xml(payload)
            for feat in (root.findall(".//Feature") if root is not None else []):
                segs = feat.findall("Segment")
                rng = segs[0].get("range", "") if segs else feat.get("range", "")
                m = re.match(r"(\d+)-(\d+)", rng or "")
                features.append({
                    "name": feat.get("name", ""),
                    "type": feat.get("type", ""),
                    "start": int(m.group(1)) if m else None,
                    "end": int(m.group(2)) if m else None,
                    "directionality": feat.get("directionality", ""),
                })
        elif btype == 5:                                 # primers
            root = _xml(payload)
            for pr in (root.findall(".//Primer") if root is not None else []):
                primers.append({"name": pr.get("name", ""),
                                "sequence": (pr.get("sequence", "") or "").upper()})
        elif btype == 6:                                 # notes / description
            root = _xml(payload)
            if root is not None:
                d = root.find(".//Description")
                if d is not None and d.text:
                    description = d.text.strip()
                t = root.find(".//Title")
                if t is not None and t.text:
                    name = t.text.strip()

    return {"name": name, "length": len(seq), "topology": "circular" if circular else "linear",
            "sequence": seq, "features": features, "primers": primers, "description": description}


def restriction_sites(seq: str, enzymes: Optional[Dict[str, str]] = None,
                      circular: bool = False) -> Dict[str, List[int]]:
    """Map enzyme -> 1-based cut/recognition start positions found in the sequence."""
    enzymes = enzymes or COMMON_ENZYMES
    s = (seq or "").upper()
    scan = s + (s[:20] if circular else "")          # wrap a little for circular maps
    out: Dict[str, List[int]] = {}
    for enz, site in enzymes.items():
        pos, hits = 0, []
        while True:
            j = scan.find(site, pos)
            if j < 0 or j >= len(s):
                break
            hits.append(j + 1)
            pos = j + 1
        if hits:
            out[enz] = hits
    return out


def analyze(raw: bytes) -> Dict[str, Any]:
    """Full structured analysis: parse + restriction-site map + unique cutters."""
    p = parse_snapgene(raw)
    sites = restriction_sites(p["sequence"], circular=(p["topology"] == "circular"))
    p["restriction_sites"] = sites
    p["unique_cutters"] = sorted([e for e, h in sites.items() if len(h) == 1])
    return p


def summarize(raw: bytes, file_name: str = "") -> str:
    """A readable text summary for the document/agent context (fed into design/assay)."""
    p = analyze(raw)
    lines = [f"[SNAPGENE MAP] {file_name or p.get('name') or 'plasmid'}",
             f"Length: {p['length']} bp · Topology: {p['topology']}"]
    if p.get("description"):
        lines.append(f"Description: {p['description'][:400]}")
    feats = [f for f in p["features"] if f.get("name")]
    if feats:
        lines.append(f"Features ({len(feats)}):")
        for f in feats[:40]:
            loc = f"{f['start']}-{f['end']}" if f.get("start") else ""
            lines.append(f"  - {f['name']} [{f.get('type','')}] {loc}".rstrip())
    if p.get("primers"):
        lines.append(f"Primers ({len(p['primers'])}):")
        for pr in p["primers"][:20]:
            lines.append(f"  - {pr['name']}: {pr['sequence']}")
    uniq = p.get("unique_cutters", [])
    if uniq:
        lines.append("Unique cutters (good for cloning): "
                     + ", ".join(f"{e}@{p['restriction_sites'][e][0]}" for e in uniq))
    multi = [e for e, h in p.get("restriction_sites", {}).items() if len(h) > 1]
    if multi:
        lines.append("Multi-cutters: " + ", ".join(f"{e}×{len(p['restriction_sites'][e])}" for e in multi))
    return "\n".join(lines)
