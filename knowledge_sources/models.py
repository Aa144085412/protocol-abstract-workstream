"""
knowledge_sources.models
========================
Standardized data models for the (future) Knowledge Integration Layer.

These are pure data definitions — no network, no logic. Every provider, when it
is eventually implemented, must convert its native response into a
``KnowledgeRecord`` so the rest of the app sees ONE shape regardless of source.

Design intent (architecture only — not yet wired into the app):
  - Provenance is mandatory: a record always carries where it came from, a
    citation, an evidence level, when it was retrieved, license, and version.
  - The layer plugs into the EXISTING uncertainty/value_promoter safety model:
    a retrieved record maps to an uncertainty "evidence" dict and a suggested
    status (e.g. a vendor spec -> kit_confirmed, a paper -> literature_supported,
    an AI inference -> ai_suggested). Retrieval therefore CONFIRMS values with
    provenance instead of letting the LLM invent them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# enums
# --------------------------------------------------------------------------- #
class EntityType(str, Enum):
    """What kind of scientific entity a record/query is about."""
    RESTRICTION_ENZYME = "restriction_enzyme"
    RECOGNITION_SITE = "recognition_site"
    METHYLATION_SENSITIVITY = "methylation_sensitivity"
    BUFFER = "buffer"
    BUFFER_COMPATIBILITY = "buffer_compatibility"
    LIGATION = "ligation"
    PCR = "pcr"
    GOLDEN_GATE = "golden_gate"
    GIBSON = "gibson"
    PLASMID = "plasmid"
    VECTOR = "vector"
    BACKBONE_FEATURE = "backbone_feature"
    CLONING_STRATEGY = "cloning_strategy"
    PRIMER = "primer"
    QPCR_PRIMER = "qpcr_primer"
    OLIGO = "oligo"
    CRISPR_GUIDE = "crispr_guide"
    REAGENT_KIT = "reagent_kit"
    REAGENT_PRODUCT = "reagent_product"
    PROTOCOL = "protocol"
    LITERATURE = "literature"
    PROTEIN = "protein"
    GENE = "gene"
    SMALL_MOLECULE = "small_molecule"


class EvidenceLevel(str, Enum):
    """How authoritative the information is — drives the uncertainty status it can
    justify downstream."""
    AUTHORITATIVE_DB = "authoritative_db"   # curated reference DB (REBASE, NCBI)
    VENDOR_SPEC = "vendor_spec"             # manufacturer's published spec (NEB, IDT)
    PEER_REVIEWED = "peer_reviewed"         # a paper / Nature Protocols
    COMMUNITY = "community"                 # community protocol repo, validated-by-users
    AI_INFERRED = "ai_inferred"            # model reasoning (never "confirmed")


class ProviderStatus(str, Enum):
    AVAILABLE = "available"   # implemented + reachable
    DISABLED = "disabled"     # implemented but turned off (flag / no key)
    PLANNED = "planned"       # placeholder only (MVP state)
    ERROR = "error"


# evidence level -> the uncertainty status it may justify (ties into value_promoter)
_EVIDENCE_TO_STATUS = {
    EvidenceLevel.AUTHORITATIVE_DB: "source_confirmed",
    EvidenceLevel.VENDOR_SPEC: "kit_confirmed",
    EvidenceLevel.PEER_REVIEWED: "literature_supported",
    EvidenceLevel.COMMUNITY: "literature_supported",
    EvidenceLevel.AI_INFERRED: "ai_suggested",
}


# --------------------------------------------------------------------------- #
# value objects
# --------------------------------------------------------------------------- #
@dataclass
class Citation:
    title: str = ""             # protocol / paper / product page title
    identifier: str = ""        # DOI / catalog no. / accession / enzyme id / PMID
    url: str = ""
    publisher: str = ""
    company: str = ""           # manufacturer / source organization
    product: str = ""           # product / kit name
    catalog_number: str = ""
    document_version: str = ""
    publication_date: str = ""  # ISO date of publication / last update
    accessed_time: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeRecord:
    """One unit of retrieved scientific knowledge, normalized across providers."""
    source: str                              # provider slug, e.g. "neb"
    entity_type: EntityType
    entity_name: str
    value: Any = None                        # the actual fact (str/dict/number)
    confidence: Optional[float] = None       # 0-1 (provider/curation confidence)
    evidence_level: EvidenceLevel = EvidenceLevel.AI_INFERRED
    citation: Optional[Citation] = None
    retrieved_time: Optional[str] = None
    assumptions: List[str] = field(default_factory=list)
    notes: str = ""
    license: Optional[str] = None
    version: Optional[str] = None            # DB/spec version for reproducibility
    raw: Optional[Dict[str, Any]] = None     # provider-native payload (audit)

    # ---- mapping into the existing uncertainty / value_promoter model -------- #
    def suggested_uncertainty_status(self) -> str:
        """Which uncertainty status this record could justify. A record NEVER
        auto-confirms past what its evidence level allows."""
        return _EVIDENCE_TO_STATUS.get(self.evidence_level, "ai_suggested")

    def to_uncertainty_evidence(self) -> Dict[str, Any]:
        """Shape compatible with value_promoter.apply(..., evidence=...): lets a
        future retrieval step confirm an uncertainty slot WITH provenance."""
        cit = self.citation or Citation()
        return {
            "evidence_class": self.suggested_uncertainty_status(),
            "source_name": f"knowledge:{self.source}",
            "source_quote": cit.title or (str(self.value)[:160] if self.value is not None else None),
            "source_location": {"url": cit.url, "id": cit.identifier} if (cit.url or cit.identifier) else None,
            "confidence": self.confidence if self.confidence is not None else 0.0,
        }

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["entity_type"] = self.entity_type.value
        d["evidence_level"] = self.evidence_level.value
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "KnowledgeRecord":
        cit = d.get("citation")
        return KnowledgeRecord(
            source=d.get("source", ""),
            entity_type=EntityType(d.get("entity_type", "literature")),
            entity_name=d.get("entity_name", ""),
            value=d.get("value"),
            confidence=d.get("confidence"),
            evidence_level=EvidenceLevel(d.get("evidence_level", "ai_inferred")),
            citation=Citation(**cit) if isinstance(cit, dict) else None,
            retrieved_time=d.get("retrieved_time"),
            assumptions=d.get("assumptions", []) or [],
            notes=d.get("notes", ""),
            license=d.get("license"),
            version=d.get("version"),
            raw=d.get("raw"),
        )


@dataclass
class Recommendation:
    """A reasoned recommendation built FROM one or more KnowledgeRecords. The
    LLM's job is to integrate/rank/explain — every claim still traces to a record."""
    option: str
    rationale: str = ""
    supporting_records: List[KnowledgeRecord] = field(default_factory=list)
    confidence: Optional[float] = None
    tradeoffs: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    cost_estimate: Optional[str] = None
    success_estimate: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["supporting_records"] = [r.as_dict() for r in self.supporting_records]
        return d


@dataclass
class QueryResult:
    """Standard envelope returned by every provider call."""
    provider: str
    entity_type: Optional[EntityType]
    query: str
    status: ProviderStatus
    records: List[KnowledgeRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def ok(self) -> bool:
        return self.status == ProviderStatus.AVAILABLE and bool(self.records)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "entity_type": self.entity_type.value if self.entity_type else None,
            "query": self.query,
            "status": self.status.value,
            "records": [r.as_dict() for r in self.records],
            "warnings": self.warnings,
        }
