"""PrimerBank — validated qPCR primers. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class PrimerBankProvider(KnowledgeProvider):
    slug = "primerbank"
    name = "PrimerBank"
    homepage = "https://pga.mgh.harvard.edu/primerbank/"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.PEER_REVIEWED
    entity_types = (EntityType.QPCR_PRIMER, EntityType.PRIMER)
    capabilities = (
        "validated qPCR primer pairs", "human transcripts", "mouse transcripts",
        "transcript-specific primer design", "experimental validation status",
    )
    license_note = "PrimerBank is academic; cite PrimerBank ID + reference on use."
