"""
knowledge_sources.registry
==========================
The single orchestration entry point for the (future) Knowledge Integration
Layer. The rest of the app will eventually call ``KnowledgeBroker`` rather than
any individual provider — so adding/removing sources is a registry change, not a
refactor.

Feature-flagged OFF by default (``KNOWLEDGE_LAYER_ENABLED``). With the flag off
every call returns a structured "disabled/planned" result with empty records, so
the MVP behaves exactly as before.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult, Recommendation
from . import cache as _cache

# providers
from .neb_provider import NEBProvider
from .rebase_provider import REBASEProvider
from .addgene_provider import AddgeneProvider
from .primerbank_provider import PrimerBankProvider
from .idt_provider import IDTProvider
from .thermo_provider import ThermoFisherProvider
from .qiagen_provider import QIAGENProvider
from .takara_provider import TakaraProvider
from .sigma_provider import SigmaProvider
from .pubmed_provider import PubMedProvider
from .pdf_manual_provider import PDFManualProvider
from .uniprot_provider import UniProtProvider
from .ensembl_provider import EnsemblProvider
from .chembl_provider import ChEMBLProvider

#: master registry, slug -> provider instance
REGISTRY: Dict[str, KnowledgeProvider] = {
    p.slug: p for p in (
        NEBProvider(), REBASEProvider(), AddgeneProvider(), PrimerBankProvider(),
        IDTProvider(), ThermoFisherProvider(), QIAGENProvider(), TakaraProvider(),
        SigmaProvider(), PubMedProvider(), PDFManualProvider(), UniProtProvider(),
        EnsemblProvider(), ChEMBLProvider(),
    )
}


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


#: global kill-switch — must be explicitly enabled before any source is consulted
KNOWLEDGE_LAYER_ENABLED = _env_flag("KNOWLEDGE_SOURCES_ENABLED", "false")


def get_provider(slug: str) -> Optional[KnowledgeProvider]:
    return REGISTRY.get(slug)


def list_providers() -> List[KnowledgeProvider]:
    return list(REGISTRY.values())


def providers_for(entity_type: EntityType) -> List[KnowledgeProvider]:
    return [p for p in REGISTRY.values() if p.supports(entity_type)]


class KnowledgeBroker:
    """Fans a query out across the providers that serve an entity type, normalizes
    everything to KnowledgeRecords, and (in future) ranks/merges/dedupes with
    provenance preserved. Today it is a safe no-op: with the layer disabled or all
    providers PLANNED, it returns disabled/planned envelopes and empty records."""

    def __init__(self, providers: Optional[List[KnowledgeProvider]] = None,
                 enabled: Optional[bool] = None):
        self.providers = providers if providers is not None else list_providers()
        self.enabled = KNOWLEDGE_LAYER_ENABLED if enabled is None else enabled

    def providers_for(self, entity_type: EntityType) -> List[KnowledgeProvider]:
        return [p for p in self.providers if p.supports(entity_type)]

    def retrieve(self, entity_type: EntityType, query: str,
                 sources: Optional[List[str]] = None,
                 context: Optional[dict] = None) -> List[QueryResult]:
        """Aggregate provider results for a query. Disabled -> one DISABLED
        envelope; enabled -> each matching provider's (currently PLANNED) result.
        Never raises, never hits the network in this build."""
        if not self.enabled:
            return [QueryResult(provider="broker", entity_type=entity_type, query=query,
                                status=ProviderStatus.DISABLED, records=[],
                                warnings=["Knowledge layer disabled "
                                          "(set KNOWLEDGE_SOURCES_ENABLED=true to enable)."])]
        chosen = self.providers_for(entity_type)
        if sources:
            chosen = [p for p in chosen if p.slug in set(sources)]
        return [p.query(entity_type, query, **(context or {})) for p in chosen] or [
            QueryResult(provider="broker", entity_type=entity_type, query=query,
                        status=ProviderStatus.PLANNED, records=[],
                        warnings=["No provider serves this entity type yet."])]

    # ---- ranking + cached merged retrieval ------------------------------- #
    #: authority weight per evidence level (higher = more trusted)
    AUTHORITY = {EvidenceLevel.AUTHORITATIVE_DB: 5, EvidenceLevel.VENDOR_SPEC: 4,
                 EvidenceLevel.PEER_REVIEWED: 3, EvidenceLevel.COMMUNITY: 2,
                 EvidenceLevel.AI_INFERRED: 1}

    def rank(self, records: List[KnowledgeRecord],
             context: Optional[dict] = None) -> List[KnowledgeRecord]:
        """Rank records best-first by authority x specificity x recency x confidence.
        Specificity: does the record match the user's exact product/catalog (from
        context)? Recency: newer publication_date wins."""
        ctx = context or {}
        want_cat = str(ctx.get("catalog_number", "")).lower()
        want_prod = str(ctx.get("product", "")).lower()

        def key(r: KnowledgeRecord):
            auth = self.AUTHORITY.get(r.evidence_level, 0)
            cit = r.citation
            specificity = 0
            if cit:
                if want_cat and want_cat == (cit.catalog_number or "").lower():
                    specificity += 2
                if want_prod and want_prod in (cit.product or "").lower():
                    specificity += 1
            recency = (cit.publication_date if cit else "") or ""
            conf = r.confidence if r.confidence is not None else 0.0
            return (auth, specificity, recency, conf)

        return sorted(records, key=key, reverse=True)

    def retrieve_records(self, entity_type: EntityType, query: str,
                         sources: Optional[List[str]] = None,
                         context: Optional[dict] = None,
                         use_cache: bool = True,
                         max_age_days: Optional[float] = 30.0) -> List[KnowledgeRecord]:
        """Fan out, merge, rank, and cache — returns ranked KnowledgeRecords.
        Disabled layer or no records -> []. Reproducible via the on-disk cache."""
        if not self.enabled:
            return []
        key = _cache.cache_key(entity_type.value, query, sources)
        if use_cache:
            cached = _cache.get(key, max_age_days=max_age_days)
            if cached is not None:
                return self.rank([KnowledgeRecord.from_dict(d) for d in cached], context)
        records: List[KnowledgeRecord] = []
        for res in self.retrieve(entity_type, query, sources, context):
            records.extend(res.records)
        ranked = self.rank(records, context)
        if use_cache and ranked:
            _cache.put(key, [r.as_dict() for r in ranked],
                       meta={"entity_type": entity_type.value, "query": query})
        return ranked

    def recommend(self, context: dict, entity_type: Optional[EntityType] = None,
                  sources: Optional[List[str]] = None) -> List[Recommendation]:
        """Future: gather records across sources then hand to a reasoning agent to
        rank + explain. Placeholder: empty until adapters + reasoning are wired."""
        return []

    def health(self) -> Dict[str, str]:
        return {p.slug: p.health().value for p in self.providers}
