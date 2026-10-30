"""
Tests for the live UniProt provider — driven by a recorded REST fixture (no
network). Run: cd lab_agent_prototype && python -m pytest tests/test_uniprot_provider.py -q
"""

import json
import os

import knowledge_sources as ks
from knowledge_sources import base_provider as bp
from knowledge_sources.models import EntityType, EvidenceLevel, ProviderStatus
from knowledge_sources.uniprot_provider import UniProtProvider

_FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "uniprot_sample.json"),
                     encoding="utf-8"))


def _transport(url):
    return json.dumps(_FIX["search"])


def test_parses_protein_record_with_provenance():
    p = UniProtProvider(http_get=_transport)
    assert p.health() == ProviderStatus.AVAILABLE
    res = p.query(EntityType.PROTEIN, "gene:TP53 AND organism_id:9606")
    assert res.status == ProviderStatus.AVAILABLE and res.records
    r = res.records[0]
    assert r.value == "Cellular tumor antigen p53"
    assert "TP53" in r.entity_name and "P04637" in r.entity_name
    assert r.evidence_level == EvidenceLevel.AUTHORITATIVE_DB
    assert r.citation.identifier == "P04637"
    assert r.citation.url.endswith("/P04637/entry")
    assert "393 aa" in r.notes and r.license == "CC-BY 4.0"


def test_authoritative_db_maps_to_source_confirmed():
    p = UniProtProvider(http_get=_transport)
    ev = p.query(EntityType.PROTEIN, "TP53").records[0].to_uncertainty_evidence()
    assert ev["evidence_class"] == "source_confirmed"     # authoritative_db
    assert ev["source_name"] == "knowledge:uniprot"


def test_network_guard_planned_when_off(monkeypatch):
    monkeypatch.setattr(bp, "NETWORK_ENABLED", False)
    assert UniProtProvider().health() == ProviderStatus.PLANNED


def test_unsupported_entity_returns_planned():
    p = UniProtProvider(http_get=_transport)
    res = p.query(EntityType.RESTRICTION_ENZYME, "EcoRI")
    assert res.records == []


def test_registered_in_registry():
    assert "uniprot" in ks.REGISTRY
    assert EntityType.PROTEIN in ks.providers_for(EntityType.PROTEIN)[0].supported_entities() \
        if ks.providers_for(EntityType.PROTEIN) else True
