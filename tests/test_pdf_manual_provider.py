"""
Tests for PDFManualProvider — vendor values from uploaded kit manuals (offline).
Run: cd lab_agent_prototype && python -m pytest tests/test_pdf_manual_provider.py -q
"""

from knowledge_sources.models import EntityType, EvidenceLevel, ProviderStatus
from knowledge_sources.pdf_manual_provider import PDFManualProvider

_MANUAL = (
    "QIAprep Spin Miniprep Kit. "
    "Resuspend the pelleted bacteria in 250 µL Buffer P1. "
    "Add 250 µL Buffer P2 and mix. "
    "To elute, add 50 µL Buffer EB to the column and centrifuge at 17,900 x g for 1 min."
)


def _provider():
    p = PDFManualProvider()
    p.add_manual(_MANUAL, title="QIAprep Spin Miniprep", company="QIAGEN",
                 product="QIAprep Spin Miniprep", catalog_number="27104",
                 version="2016", url="https://www.qiagen.com")
    return p


def test_planned_until_a_manual_is_added():
    assert PDFManualProvider().health() == ProviderStatus.PLANNED
    assert _provider().health() == ProviderStatus.AVAILABLE


def test_extracts_elution_volume_with_citation():
    p = _provider()
    res = p.query(EntityType.PROTOCOL, "elution volume Buffer EB", expected_type="volume")
    assert res.status == ProviderStatus.AVAILABLE and res.records
    vals = [r.value for r in res.records]
    assert any("50" in v and ("µl" in v.lower() or "ul" in v.lower()) for v in vals)
    r = res.records[0]
    assert r.evidence_level == EvidenceLevel.VENDOR_SPEC
    assert r.citation.company == "QIAGEN" and r.citation.catalog_number == "27104"
    assert r.notes                                   # supporting snippet preserved


def test_dimension_filter_speed_only():
    p = _provider()
    res = p.query(EntityType.PROTOCOL, "centrifuge spin column", expected_type="speed")
    assert res.records and all("g" in r.value.lower() or "rpm" in r.value.lower()
                               for r in res.records)
    assert any("17,900" in r.value for r in res.records)


def test_query_terms_must_match_window():
    p = _provider()
    # asking about a temperature that the manual never states -> no records
    res = p.query(EntityType.PROTOCOL, "incubation temperature", expected_type="temperature")
    assert res.records == []


def test_unsupported_entity_returns_no_records():
    p = _provider()
    res = p.query(EntityType.RESTRICTION_ENZYME, "EcoRI", expected_type="speed")
    assert res.records == []                          # provider doesn't serve enzymes


def test_to_uncertainty_evidence_is_kit_confirmed():
    p = _provider()
    rec = p.query(EntityType.PROTOCOL, "elute Buffer EB", expected_type="volume").records[0]
    ev = rec.to_uncertainty_evidence()
    assert ev["evidence_class"] == "kit_confirmed"   # vendor_spec -> kit_confirmed
    assert ev["source_name"] == "knowledge:pdf_manual"
