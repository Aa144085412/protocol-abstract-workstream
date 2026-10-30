"""NEB (New England Biolabs) — molecular cloning. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class NEBProvider(KnowledgeProvider):
    slug = "neb"
    name = "New England Biolabs (NEB)"
    homepage = "https://www.neb.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (
        EntityType.RESTRICTION_ENZYME, EntityType.BUFFER, EntityType.BUFFER_COMPATIBILITY,
        EntityType.LIGATION, EntityType.PCR, EntityType.GOLDEN_GATE, EntityType.GIBSON,
        EntityType.CLONING_STRATEGY, EntityType.REAGENT_PRODUCT,
    )
    capabilities = (
        "restriction enzyme lookup", "buffer compatibility (Double Digest Finder)",
        "Golden Gate assembly guidance", "Gibson/NEBuilder assembly guidance",
        "ligation recommendations", "PCR (polymerase) recommendations",
        "cloning workflow suggestions",
    )
    license_note = "NEB content is proprietary; future adapter must respect ToS, lookup-only, cite source."
