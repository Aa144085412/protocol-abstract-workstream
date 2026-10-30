"""Thermo Fisher — reagents / RT-qPCR. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class ThermoFisherProvider(KnowledgeProvider):
    slug = "thermo"
    name = "Thermo Fisher Scientific"
    homepage = "https://www.thermofisher.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (
        EntityType.REAGENT_KIT, EntityType.REAGENT_PRODUCT, EntityType.QPCR_PRIMER, EntityType.PCR,
    )
    capabilities = (
        "RT-qPCR kit recommendations", "reagent / consumable recommendations",
        "TaqMan / primer resources", "context-aware product suggestions (vs hallucinated reagents)",
    )
    license_note = "Thermo catalog is proprietary; recommend products + catalog no., never invent."
