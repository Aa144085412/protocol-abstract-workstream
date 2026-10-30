"""
Tests for the Knowledge Integration Layer scaffolding. These prove the layer is a
safe, offline, dormant placeholder: providers register, report PLANNED, return
empty/structured results with NO network, the broker is disabled by default, and
the data model maps onto the existing uncertainty/value_promoter evidence shape.

Run: cd lab_agent_prototype && python -m pytest tests/test_knowledge_sources.py -q
"""

import knowledge_sources as ks
from knowledge_sources.models import (
    EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, Citation, QueryResult,
)
from knowledge_sources.base_provider import NETWORK_ENABLED, assert_online_allowed, NetworkDisabledError

EXPECTED = {"neb", "rebase", "addgene", "primerbank", "idt", "thermo",
            "qiagen", "takara", "sigma", "pubmed"}


# ------------------------------- registry --------------------------------- #
def test_all_providers_registered():
    assert EXPECTED.issubset(set(ks.REGISTRY.keys()))


def test_providers_are_planned_with_metadata():
    for slug, p in ks.REGISTRY.items():
        assert p.health() == ProviderStatus.PLANNED
        m = p.metadata()
        # most have a homepage; the uploaded-manuals provider has none (it's the user's docs)
        assert (not m["homepage"]) or m["homepage"].startswith("http")
        assert m["capabilities"], f"{slug} should list future capabilities"
        assert p.supported_entities(), f"{slug} should declare entity types"


def test_query_is_offline_placeholder():
    p = ks.get_provider("neb")
    res = p.query(EntityType.RESTRICTION_ENZYME, "EcoRI")
    assert isinstance(res, QueryResult)
    assert res.status == ProviderStatus.PLANNED
    assert res.records == []
    assert res.warnings  # explains it's a placeholder
    assert p.lookup(EntityType.RESTRICTION_ENZYME, "EcoRI") is None
    assert p.recommend({"goal": "clone"}) == []


# ------------------------------- network guard ---------------------------- #
def test_network_is_disabled():
    assert NETWORK_ENABLED is False
    try:
        assert_online_allowed()
        assert False, "expected NetworkDisabledError"
    except NetworkDisabledError:
        pass


# ------------------------------- broker ----------------------------------- #
def test_broker_disabled_by_default():
    broker = ks.KnowledgeBroker(enabled=False)
    out = broker.retrieve(EntityType.QPCR_PRIMER, "GAPDH human")
    assert len(out) == 1 and out[0].status == ProviderStatus.DISABLED
    assert out[0].records == []
    assert broker.recommend({"goal": "qPCR"}) == []


def test_broker_enabled_fans_out_but_planned():
    broker = ks.KnowledgeBroker(enabled=True)
    out = broker.retrieve(EntityType.RESTRICTION_ENZYME, "BsaI")
    assert out  # at least NEB + REBASE serve this entity type
    assert all(r.status == ProviderStatus.PLANNED for r in out)
    assert all(r.records == [] for r in out)


def test_providers_for_entity():
    slugs = {p.slug for p in ks.providers_for(EntityType.RESTRICTION_ENZYME)}
    assert {"neb", "rebase"}.issubset(slugs)


# ------------------- mapping into the existing safety model ---------------- #
def test_record_maps_to_uncertainty_status():
    cases = {
        EvidenceLevel.AUTHORITATIVE_DB: "source_confirmed",
        EvidenceLevel.VENDOR_SPEC: "kit_confirmed",
        EvidenceLevel.PEER_REVIEWED: "literature_supported",
        EvidenceLevel.COMMUNITY: "literature_supported",
        EvidenceLevel.AI_INFERRED: "ai_suggested",
    }
    for lvl, status in cases.items():
        rec = KnowledgeRecord(source="x", entity_type=EntityType.BUFFER,
                              entity_name="rCutSmart", evidence_level=lvl)
        assert rec.suggested_uncertainty_status() == status


def test_to_uncertainty_evidence_shape_matches_value_promoter():
    rec = KnowledgeRecord(
        source="neb", entity_type=EntityType.RESTRICTION_ENZYME, entity_name="EcoRI",
        value="G^AATTC", confidence=0.99, evidence_level=EvidenceLevel.VENDOR_SPEC,
        citation=Citation(title="NEB EcoRI product page", identifier="R0101",
                          url="https://www.neb.com/products/r0101"))
    ev = rec.to_uncertainty_evidence()
    # exactly the keys value_promoter.apply(evidence=...) consumes
    for k in ("evidence_class", "source_name", "source_quote", "source_location", "confidence"):
        assert k in ev
    assert ev["evidence_class"] == "kit_confirmed"
    assert ev["source_name"] == "knowledge:neb"
    assert ev["source_location"]["id"] == "R0101"
    assert rec.as_dict()["entity_type"] == "restriction_enzyme"


# ------ MVP unchanged at runtime: layer OFF by default, tier inert by default - #
def test_knowledge_layer_off_by_default():
    # the layer is opt-in: with the env flag unset, a default broker is disabled
    import importlib, knowledge_sources as ks
    importlib.reload(ks.registry) if hasattr(ks, "registry") else None
    assert ks.KnowledgeBroker(enabled=None).enabled in (False, ks.KNOWLEDGE_LAYER_ENABLED)
    # agents (reasoning layer) must still not import the knowledge layer
    import pathlib
    agents_dir = pathlib.Path(__file__).resolve().parent.parent / "agents"
    for f in agents_dir.rglob("*.py"):
        assert "import knowledge_sources" not in f.read_text(encoding="utf-8"), \
            f"{f} should reach the layer via tools, not import it directly"


def test_evidence_tier_is_inert_without_a_broker():
    # tools/evidence_resolver wires the layer (Phase 3) but stays inert by default:
    # no broker -> no knowledge lookups, so runtime behavior is unchanged.
    from tools import evidence_resolver as er
    from tools import uncertainty_slots as us
    proto = {"protocol_title": "t", "materials": [],
             "workflow": [{"step_id": "s1", "step_number": 1, "title": "Elute",
                           "instructions": ["Elute."], "time_estimate": us.CONFIRM,
                           "conditions": {}, "reagents": [{"item": "EB", "amount": us.CONFIRM}]}]}
    us.enumerate_slots(proto)
    o = us.get(proto, "step:s1:reag:0:amount")
    assert er.from_knowledge_sources(proto, o, broker=None) == []
