"""Capture DNA/oligo sequences embedded in uploaded documents."""
from tools import sequence_scan as ss


def test_inline_labelled_sequence():
    txt = "WT Skip oligo: ACGTACGTACGTACGTACGT\nMut Skip oligo: TTTTGGGGCCCCAAAATTTT"
    hits = ss.scan(txt)
    labels = {h["label"]: h["sequence"] for h in hits}
    assert "WT Skip oligo" in labels and labels["WT Skip oligo"] == "ACGTACGTACGTACGTACGT"
    assert "Mut Skip oligo" in labels


def test_fasta_multiline():
    txt = ">WT_Skip_insert\nACGTACGTACGTAC\nGTACGTACGTACGT\n>Primer_F\nGAATTCACGTACGTAC"
    hits = ss.scan(txt)
    seqs = {h["label"]: h["sequence"] for h in hits}
    assert seqs["WT_Skip_insert"] == "ACGTACGTACGTACGTACGTACGTACGT"
    assert any("primer" in h["kind"] for h in hits if h["label"] == "Primer_F")


def test_ignores_prose():
    assert ss.scan("This is a normal sentence with no sequences at all.") == []


def test_attach_to_materials():
    proto = {"materials": [{"item": "WT Skip dsDNA (synthesized)"},
                           {"item": "Q5 polymerase"}]}
    seqs = [{"label": "WT Skip oligo", "sequence": "ACGT" * 10, "length": 40, "kind": "oligo / primer"}]
    n = ss.attach_to_materials(proto, seqs)
    assert n == 1
    assert proto["materials"][0].get("sequence") == "ACGT" * 10
    assert "Sequence captured" in proto["materials"][0]["notes"]
    assert proto["sequences"] == seqs


def test_kind_classification():
    assert ss.scan("primer F: GAATTCACGTACGTACGT")[0]["kind"] == "primer"
    big = "insert: " + "ACGT" * 100
    assert "dsDNA" in ss.scan(big)[0]["kind"]
