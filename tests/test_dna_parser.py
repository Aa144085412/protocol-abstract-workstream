"""SnapGene .dna parser (pure stdlib) — sequence, features, primers, restriction sites."""
import struct
from tools import dna_parser as dp
from tools.document_parser import extract_text


def _block(btype, payload):
    return bytes([btype]) + struct.pack(">I", len(payload)) + payload


def _make_dna():
    header = _block(9, b"SnapGene\x00\x00\x00\x00")
    seq = b"GAATTCGGATCCAAAATTTT"           # EcoRI@1, BamHI@7
    dna = _block(0, bytes([0]) + seq)        # flags=0 -> linear
    feats = ('<Features><Feature name="EGFP" type="CDS" directionality="1">'
             '<Segment range="1-10"/></Feature></Features>').encode()
    fblock = _block(10, feats)
    prim = '<Primers><Primer name="F1" sequence="GAATTCAA"/></Primers>'.encode()
    pblock = _block(5, prim)
    return header + dna + fblock + pblock


def test_is_snapgene():
    assert dp.is_snapgene(_make_dna())
    assert not dp.is_snapgene(b"not a snapgene file")


def test_parse_sequence_and_features():
    p = dp.parse_snapgene(_make_dna())
    assert p["sequence"] == "GAATTCGGATCCAAAATTTT"
    assert p["topology"] == "linear"
    assert any(f["name"] == "EGFP" for f in p["features"])
    assert any(pr["name"] == "F1" for pr in p["primers"])


def test_restriction_sites_and_unique_cutters():
    p = dp.analyze(_make_dna())
    assert p["restriction_sites"]["EcoRI"] == [1]
    assert p["restriction_sites"]["BamHI"] == [7]
    assert "EcoRI" in p["unique_cutters"] and "BamHI" in p["unique_cutters"]


def test_summary_text():
    s = dp.summarize(_make_dna(), file_name="test.dna")
    assert "SNAPGENE MAP" in s and "EGFP" in s and "Unique cutters" in s


def test_extract_text_routes_dna():
    s = extract_text(path="", raw_bytes=_make_dna(), file_name="p.dna")
    assert "SNAPGENE MAP" in s and "20 bp" in s
