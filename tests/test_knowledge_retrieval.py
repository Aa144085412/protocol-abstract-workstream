"""
Tests for knowledge retrieval: cache, broker ranking, cached merged retrieval.
Uses a stub provider — no network. Run:
  cd lab_agent_prototype && python -m pytest tests/test_knowledge_retrieval.py -q
"""

import pytest

import knowledge_sources as ks
from knowledge_sources import cache
from knowledge_sources.base_provider import KnowledgeProvider
from knowledge_sources.models import (
    Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult,
)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    # isolate the on-disk cache into a writable temp dir (the repo mount may be read-only)
    monkeypatch.setattr(cache, "_DIR", str(tmp_path / "kcache"))


def _rec(name, level, conf=0.5, catalog="", product="", pubdate=""):
    return KnowledgeRecord(
        source="stub", entity_type=EntityType.RESTRICTION_ENZYME, entity_name=name,
        value=name, confidence=conf, evidence_level=level,
        citation=Citation(title=name, catalog_number=catalog, product=product,
                          publication_date=pubdate))


# --------------------------------- cache ---------------------------------- #
def test_cache_roundtrip_and_clear():
    cache.clear()
    key = cache.cache_key("restriction_enzyme", "EcoRI")
    assert cache.get(key) is None
    cache.put(key, [{"source": "x", "value": "G^AATTC"}])
    got = cache.get(key)
    assert got and got[0]["value"] == "G^AATTC"
    assert cache.clear() >= 1
    assert cache.get(key) is None


def test_cache_staleness():
    cache.clear()
    key = cache.cache_key("x", "y")
    cache.put(key, [{"v": 1}])
    assert cache.get(key, max_age_days=10) is not None
    assert cache.get(key, max_age_days=0) is None      # treat as stale
    cache.clear()


# -------------------------------- ranking --------------------------------- #
def test_rank_by_authority():
    b = ks.KnowledgeBroker(providers=[], enabled=True)
    recs = [_rec("ai", EvidenceLevel.AI_INFERRED), _rec("db", EvidenceLevel.AUTHORITATIVE_DB),
            _rec("vendor", EvidenceLevel.VENDOR_SPEC), _rec("paper", EvidenceLevel.PEER_REVIEWED)]
    ranked = b.rank(recs)
    assert [r.entity_name for r in ranked] == ["db", "vendor", "paper", "ai"]


def test_rank_specificity_catalog_match():
    b = ks.KnowledgeBroker(providers=[], enabled=True)
    generic = _rec("generic", EvidenceLevel.VENDOR_SPEC, catalog="R9999")
    exact = _rec("exact", EvidenceLevel.VENDOR_SPEC, catalog="R0101")
    ranked = b.rank([generic, exact], context={"catalog_number": "R0101"})
    assert ranked[0].entity_name == "exact"          # exact catalog match wins within a tier


def test_rank_recency_tiebreak():
    b = ks.KnowledgeBroker(providers=[], enabled=True)
    old = _rec("old", EvidenceLevel.PEER_REVIEWED, pubdate="2019-01-01")
    new = _rec("new", EvidenceLevel.PEER_REVIEWED, pubdate="2024-01-01")
    assert b.rank([old, new])[0].entity_name == "new"


# ----------------------- cached merged retrieval -------------------------- #
class _StubProvider(KnowledgeProvider):
    slug = "stub"
    name = "Stub"
    homepage = "https://example.org"
    status = ProviderStatus.AVAILABLE
    entity_types = (EntityType.RESTRICTION_ENZYME,)

    def __init__(self, records):
        self._records = records

    def health(self):
        return ProviderStatus.AVAILABLE

    def query(self, entity_type, query, **ctx):
        return QueryResult(provider=self.slug, entity_type=entity_type, query=query,
                           status=ProviderStatus.AVAILABLE, records=list(self._records))


def test_retrieve_records_disabled_returns_empty():
    b = ks.KnowledgeBroker(providers=[_StubProvider([_rec("x", EvidenceLevel.VENDOR_SPEC)])],
                           enabled=False)
    assert b.retrieve_records(EntityType.RESTRICTION_ENZYME, "EcoRI") == []


def test_retrieve_records_ranks_and_caches():
    cache.clear()
    prov = _StubProvider([_rec("ai", EvidenceLevel.AI_INFERRED),
                          _rec("db", EvidenceLevel.AUTHORITATIVE_DB)])
    b = ks.KnowledgeBroker(providers=[prov], enabled=True)
    out = b.retrieve_records(EntityType.RESTRICTION_ENZYME, "BsaI")
    assert [r.entity_name for r in out] == ["db", "ai"]     # ranked
    # second call: provider now returns nothing, but cache serves the original
    prov._records = []
    cached = b.retrieve_records(EntityType.RESTRICTION_ENZYME, "BsaI")
    assert [r.entity_name for r in cached] == ["db", "ai"]
    cache.clear()
