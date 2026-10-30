"""
Tests for the standard-default catalog + matcher (tools/standard_defaults).
Run: cd lab_agent_prototype && python -m pytest tests/test_standard_defaults.py -q
"""

from tools import standard_defaults as sd


def test_catalog_loads():
    d = sd.load_defaults()
    assert d and all("id" in e and "value" in e and "inference_basis" in e for e in d)


def test_restriction_digest_dna_input():
    e = sd.best("Digest the plasmid with EcoRI", expected_type="mass", intent="digest")
    assert e and e["id"] == "restriction_digestion_dna_input"
    assert "µg" in e["value"] and e["citation"]["company"] == "NEB"


def test_pcr_cleanup_elution_volume():
    e = sd.best("Clean up the PCR product on a column", expected_type="volume")
    assert e and e["id"] == "pcr_cleanup_elution"
    assert "µL" in e["value"]


def test_miniprep_culture_volume():
    e = sd.best("Miniprep the overnight culture", expected_type="volume")
    assert e and e["id"] == "miniprep_culture_volume"


def test_seeding_density_for_plating():
    e = sd.best("Seed cells into the plate", expected_type="cell_number", intent="seed")
    assert e and e["id"] == "cell_culture_seeding_density"
    assert e["risk_level"] == "medium"


def test_mammalian_incubation_temperature():
    e = sd.best("Incubate the cells in the CO2 incubator", expected_type="temperature",
                intent="incubate")
    assert e and e["id"] == "mammalian_incubation"
    assert "37" in e["value"]


def test_dimension_mismatch_excluded():
    # a temperature default must not match when we're asking for a volume
    hits = sd.match("Incubate the cells", expected_type="volume", intent="incubate")
    assert all(h["id"] != "mammalian_incubation" for h in hits)


def test_no_topic_no_match():
    assert sd.best("Label the tubes", expected_type="volume") is None


def test_every_entry_has_basis_and_risk():
    for e in sd.load_defaults():
        assert e.get("inference_basis")
        assert e.get("risk_level") in ("low", "medium", "high")
