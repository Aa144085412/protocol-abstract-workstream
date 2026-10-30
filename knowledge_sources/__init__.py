"""
knowledge_sources
=================
ARCHITECTURE-ONLY scaffolding for a future Knowledge Integration Layer that lets
the Executive Lab Agent retrieve validated scientific knowledge from trusted
sources (NEB, REBASE, Addgene, PrimerBank, IDT, vendors, PubMed, …) instead of
having the LLM invent it.

Status: PLACEHOLDER. No provider is implemented, nothing here makes a network
call, and nothing in the app imports this package — so the MVP is unchanged.

Single future entry point: ``KnowledgeBroker``. Everything is feature-flagged off
via ``KNOWLEDGE_SOURCES_ENABLED`` (default false). See ARCHITECTURE.md.
"""

from .models import (
    Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus,
    QueryResult, Recommendation,
)
from .base_provider import (
    KnowledgeProvider, NETWORK_ENABLED, NetworkDisabledError, assert_online_allowed,
)
from .registry import (
    REGISTRY, KNOWLEDGE_LAYER_ENABLED, KnowledgeBroker,
    get_provider, list_providers, providers_for,
)
from . import cache

__all__ = [
    "Citation", "EntityType", "EvidenceLevel", "KnowledgeRecord", "ProviderStatus",
    "QueryResult", "Recommendation",
    "KnowledgeProvider", "NETWORK_ENABLED", "NetworkDisabledError", "assert_online_allowed",
    "REGISTRY", "KNOWLEDGE_LAYER_ENABLED", "KnowledgeBroker",
    "get_provider", "list_providers", "providers_for",
]
