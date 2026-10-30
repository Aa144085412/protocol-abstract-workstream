"""Known raw-reagent working concentrations (raw reagents only, no products/plasmids)."""
from tools import known_reagents as kr


def test_polybrene_working_conc():
    s = kr.suggest("Polybrene (TR-1003-G)")
    assert s and "µg/mL" in s["value"] and s["proposed_status"] == "typical_range"


def test_antibiotics():
    assert "100 µg/mL" in kr.suggest("Ampicillin")["value"]
    assert "50 µg/mL" in kr.suggest("Kanamycin sulfate")["value"]


def test_not_a_known_reagent():
    assert kr.lookup("pcg2.0-GFP lentivirus vector") is None
    assert kr.suggest("Q5 Hotstart DNA polymerase") is None   # enzyme, not a working-conc reagent
