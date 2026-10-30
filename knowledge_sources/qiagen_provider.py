"""QIAGEN — extraction / sample-prep kits. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class QIAGENProvider(KnowledgeProvider):
    slug = "qiagen"
    name = "QIAGEN"
    homepage = "https://www.qiagen.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (EntityType.REAGENT_KIT, EntityType.REAGENT_PRODUCT, EntityType.PROTOCOL)
    capabilities = (
        "DNA/RNA extraction kit recommendations", "sample-prep kit selection by sample type",
        "kit handbook protocol references", "context-aware product suggestions",
    )
    license_note = "QIAGEN catalog + handbooks are proprietary; recommend + cite, never invent values."
