"""Addgene — plasmid repository. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class AddgeneProvider(KnowledgeProvider):
    slug = "addgene"
    name = "Addgene"
    homepage = "https://www.addgene.org"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.AUTHORITATIVE_DB
    entity_types = (
        EntityType.PLASMID, EntityType.VECTOR, EntityType.BACKBONE_FEATURE,
        EntityType.CLONING_STRATEGY,
    )
    capabilities = (
        "plasmid maps", "vector / backbone information", "backbone features (selection, ori, tags)",
        "published cloning strategies", "depositor + reference paper linkage",
    )
    license_note = "Addgene data is shared with attribution; cite plasmid ID + depositor/reference."
