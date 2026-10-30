"""
Tests for the live PubMed provider — driven by a recorded NCBI E-utilities fixture
(no network). Verifies parsing into cited KnowledgeRecords, the network guard, error
handling, and broker integration.

Run: cd lab_agent_prototype && python -m pytest tests/test_pubmed_provider.py -q
"""

import json
import os

import pytest

import knowledge_sources as ks
from knowledge_sources import base_provider as bp, cache
from knowledge_sources.models import EntityType, EvidenceLevel, ProviderStatus
from knowledge_sources.pubmed_provider import PubMedProvider

_FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "pubmed_sample.json"),
                     encoding="utf-8"))


def _fixture_transport(url: str) -> str:
    """Return the recorded esearch/esummary JSON based on the endpoint in the URL."""
    if "esearch" in url:
        return json.dumps(_FIX["esearch"])
    if "esummary" in url:
        return json.dumps(_FIX["esummary"])
    raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "_DIR", str(tmp_path / "kcache"))


# ------------------------------- parsing ---------------------------------- #
def test_parses_fixture_into_cited_records():
    p = PubMedProvider(http_get=_fixture_transport, email="me@lab.edu")
    assert p.health() == ProviderStatus.AVAILABLE
    res = p.query(EntityType.LITERATURE, "CUT&Tag H3K27ac")
    assert res.status == ProviderStatus.AVAILABLE and len(res.records) == 3
    r0 = res.records[0]
    assert "MLL3" in r0.entity_name
    assert r0.evidence_level == EvidenceLevel.PEER_REVIEWED
    assert r0.citation.identifier == "PMID:42327198"
    assert r0.citation.url == "https://pubmed.ncbi.nlm.nih.gov/42327198/"
    assert "10.64898" in r0.citation.catalog_number          # doi captured
    assert r0.citation.publisher.startswith("bioRxiv")
    assert r0.citation.publication_date.startswith("2026/06/08")
    assert r0.retrieved_time                                  # provenance timestamp


def test_to_uncertainty_evidence_is_literature_supported():
    p = PubMedProvider(http_get=_fixture_transport)
    rec = p.query(EntityType.LITERATURE, "x").records[0]
    ev = rec.to_uncertainty_evidence()
    assert ev["evidence_class"] == "literature_supported"
    assert ev["source_name"] == "knowledge:pubmed"
    assert ev["source_location"]["id"].startswith("PMID:")


# ----------------------------- network guard ------------------------------ #
def test_no_transport_and_network_off_is_planned(monkeypatch):
    monkeypatch.setattr(bp, "NETWORK_ENABLED", False)
    p = PubMedProvider()                       # no injected transport
    assert p.health() == ProviderStatus.PLANNED
    res = p.query(EntityType.LITERATURE, "x")
    assert res.status == ProviderStatus.PLANNED and res.records == []


def test_default_transport_blocked_when_network_off(monkeypatch):
    monkeypatch.setattr(bp, "NETWORK_ENABLED", False)
    # force the default (network) path; the guard must raise -> ERROR envelope, no crash
    p = PubMedProvider()
    monkeypatch.setattr(p, "health", lambda: ProviderStatus.AVAILABLE)
    res = p.query(EntityType.LITERATURE, "x")
    assert res.status == ProviderStatus.ERROR


# --------------------------- error handling ------------------------------- #
def test_transport_error_returns_error_envelope():
    def boom(url):
        raise RuntimeError("network down")
    p = PubMedProvider(http_get=boom)
    res = p.query(EntityType.LITERATURE, "x")
    assert res.status == ProviderStatus.ERROR and res.records == []


# --------------------------- broker integration --------------------------- #
def test_broker_retrieve_records_with_pubmed():
    p = PubMedProvider(http_get=_fixture_transport, email="me@lab.edu")
    broker = ks.KnowledgeBroker(providers=[p], enabled=True)
    recs = broker.retrieve_records(EntityType.LITERATURE, "CUT&Tag H3K27ac")
    assert len(recs) == 3
    assert all(r.evidence_level == EvidenceLevel.PEER_REVIEWED for r in recs)
    # second call served from cache even if the provider goes dark
    p._http = lambda url: (_ for _ in ()).throw(RuntimeError("offline"))
    again = broker.retrieve_records(EntityType.LITERATURE, "CUT&Tag H3K27ac")
    assert len(again) == 3
