"""Sigma-Aldrich (MilliporeSigma) — reagents / chemicals. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class SigmaProvider(KnowledgeProvider):
    slug = "sigma"
    name = "Sigma-Aldrich (MilliporeSigma)"
    homepage = "https://www.sigmaaldrich.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (EntityType.REAGENT_PRODUCT, EntityType.REAGENT_KIT)
    capabilities = (
        "chemical / reagent catalog lookup", "reagent recommendations by context",
        "grade / purity / catalog-number resolution", "safety (SDS) reference linkage",
    )
    license_note = "Sigma catalog + SDS are proprietary; recommend + cite catalog no., never invent."
