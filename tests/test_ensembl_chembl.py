"""
Tests for the live Ensembl + ChEMBL providers (fixture-driven, no network).
Run: cd lab_agent_prototype && python -m pytest tests/test_ensembl_chembl.py -q
"""

import json
import os

import knowledge_sources as ks
from knowledge_sources import base_provider as bp
from knowledge_sources.models import EntityType, EvidenceLevel, ProviderStatus
from knowledge_sources.ensembl_provider import EnsemblProvider
from knowledge_sources.chembl_provider import ChEMBLProvider

_F = os.path.join(os.path.dirname(__file__), "fixtures")
_ENS = json.load(open(os.path.join(_F, "ensembl_sample.json"), encoding="utf-8"))
_CHE = json.load(open(os.path.join(_F, "chembl_sample.json"), encoding="utf-8"))


# ------------------------------- Ensembl ---------------------------------- #
def test_ensembl_parses_gene_with_provenance():
    p = EnsemblProvider(http_get=lambda url: json.dumps(_ENS["gene"]))
    res = p.query(EntityType.GENE, "TP53")
    assert res.status == ProviderStatus.AVAILABLE and res.records
    r = res.records[0]
    assert "TP53" in r.entity_name and "ENSG00000141510" in r.entity_name
    assert r.evidence_level == EvidenceLevel.AUTHORITATIVE_DB
    assert r.citation.identifier == "ENSG00000141510"
    assert "17:7661779-7687546" in r.notes and "GRCh38" in r.notes


def test_ensembl_network_guard(monkeypatch):
    monkeypatch.setattr(bp, "NETWORK_ENABLED", False)
    assert EnsemblProvider().health() == ProviderStatus.PLANNED


# -------------------------------- ChEMBL ---------------------------------- #
def test_chembl_parses_molecule_with_provenance():
    p = ChEMBLProvider(http_get=lambda url: json.dumps(_CHE["molecule_search"]))
    res = p.query(EntityType.SMALL_MOLECULE, "aspirin")
    assert res.records
    r = res.records[0]
    assert "ASPIRIN" in r.entity_name and "CHEMBL25" in r.entity_name
    assert r.evidence_level == EvidenceLevel.AUTHORITATIVE_DB
    assert "180.16" in r.notes and "C9H8O4" in r.notes
    assert r.citation.url.endswith("/CHEMBL25/")
    assert r.license == "CC-BY-SA 3.0"


def test_chembl_error_envelope():
    def boom(url):
        raise RuntimeError("down")
    res = ChEMBLProvider(http_get=boom).query(EntityType.SMALL_MOLECULE, "x")
    assert res.status == ProviderStatus.ERROR and res.records == []


# ------------------------------ registry ---------------------------------- #
def test_both_registered():
    assert "ensembl" in ks.REGISTRY and "chembl" in ks.REGISTRY
    assert ks.providers_for(EntityType.GENE)          # ensembl serves GENE
    assert ks.providers_for(EntityType.SMALL_MOLECULE)
