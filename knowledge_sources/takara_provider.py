"""Takara Bio — reagents / kits. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class TakaraProvider(KnowledgeProvider):
    slug = "takara"
    name = "Takara Bio"
    homepage = "https://www.takarabio.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (
        EntityType.REAGENT_KIT, EntityType.REAGENT_PRODUCT, EntityType.PCR, EntityType.CLONING_STRATEGY,
    )
    capabilities = (
        "PCR polymerase / kit recommendations", "cDNA synthesis & library kits",
        "In-Fusion cloning guidance", "context-aware product suggestions",
    )
    license_note = "Takara catalog is proprietary; recommend products + catalog no., never invent."
