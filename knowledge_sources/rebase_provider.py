"""REBASE — restriction enzyme database. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class REBASEProvider(KnowledgeProvider):
    slug = "rebase"
    name = "REBASE (Restriction Enzyme Database)"
    homepage = "https://rebase.neb.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.AUTHORITATIVE_DB
    entity_types = (
        EntityType.RESTRICTION_ENZYME, EntityType.RECOGNITION_SITE,
        EntityType.METHYLATION_SENSITIVITY,
    )
    capabilities = (
        "restriction enzyme database lookup", "recognition site sequences",
        "methylation sensitivity (Dam/Dcm/CpG)", "isoschizomers / neoschizomers",
    )
    license_note = "REBASE is a curated academic database; cite REBASE + version on use."
