"""IDT (Integrated DNA Technologies) — oligos / CRISPR. PLACEHOLDER (not implemented)."""
from __future__ import annotations

from .base_provider import KnowledgeProvider
from .models import EntityType, EvidenceLevel, ProviderStatus


class IDTProvider(KnowledgeProvider):
    slug = "idt"
    name = "Integrated DNA Technologies (IDT)"
    homepage = "https://www.idtdna.com"
    status = ProviderStatus.PLANNED
    default_evidence_level = EvidenceLevel.VENDOR_SPEC
    entity_types = (
        EntityType.PRIMER, EntityType.OLIGO, EntityType.CRISPR_GUIDE, EntityType.REAGENT_PRODUCT,
    )
    capabilities = (
        "primer / oligo ordering", "oligo synthesis specs (scale, purification)",
        "primer analysis (Tm, hairpin, dimer via OligoAnalyzer-style)",
        "CRISPR guide RNA design + on/off-target scoring",
    )
    license_note = "IDT tools are proprietary; future adapter is ordering/analysis aid, cite source."
