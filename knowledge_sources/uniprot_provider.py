"""
UniProt — LIVE protein/gene knowledge provider via the official UniProt REST API
(rest.uniprot.org), a public, documented, programmatic endpoint. Returns
authoritative protein records with full provenance (accession, gene, organism, URL).

Same safety/testability pattern as PubMed: injectable transport (fixture-driven in
tests; network-guarded default in the app).
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from typing import Any, List

from . import base_provider as bp
from .base_provider import KnowledgeProvider
from .models import Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult

_BASE = "https://rest.uniprot.org/uniprotkb/search"
_FIELDS = "accession,id,protein_name,gene_names,organism_name,length"


def _default_http_get(url: str) -> str:
    bp.assert_online_allowed()
    import urllib.request
    with urllib.request.urlopen(url, timeout=20) as r:   # noqa: S310 (trusted UniProt host)
        return r.read().decode("utf-8", "replace")


class UniProtProvider(KnowledgeProvider):
    slug = "uniprot"
    name = "UniProt"
    homepage = "https://www.uniprot.org"
    status = ProviderStatus.PLANNED
    entity_types = (EntityType.PROTEIN, EntityType.GENE)
    capabilities = ("protein information, functions, sequences",
                    "gene -> canonical protein resolution", "authoritative accession + citation")
    license_note = "UniProt data is CC-BY (4.0); access via the official REST API."

    def __init__(self, http_get=None):
        self._http = http_get

    def health(self) -> ProviderStatus:
        if self._http is not None:
            return ProviderStatus.AVAILABLE
        return ProviderStatus.AVAILABLE if bp.NETWORK_ENABLED else ProviderStatus.PLANNED

    def _get(self, url: str) -> str:
        return (self._http or _default_http_get)(url)

    def query(self, entity_type: EntityType, query: str, max_results: int = 3,
              **context: Any) -> QueryResult:
        if entity_type not in self.entity_types or self.health() != ProviderStatus.AVAILABLE:
            return self._planned(entity_type, query)
        params = urllib.parse.urlencode({"query": query, "fields": _FIELDS,
                                         "format": "json", "size": max_results})
        try:
            data = json.loads(self._get(f"{_BASE}?{params}"))
            return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE,
                               self._records(data), [])
        except Exception as exc:
            return QueryResult(self.slug, entity_type, query, ProviderStatus.ERROR, [],
                               [f"UniProt query failed: {exc}"])

    def _records(self, data: dict) -> List[KnowledgeRecord]:
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        out: List[KnowledgeRecord] = []
        for r in data.get("results", []) or []:
            acc = r.get("primaryAccession", "")
            name = (((r.get("proteinDescription") or {}).get("recommendedName") or {})
                    .get("fullName") or {}).get("value", r.get("uniProtkbId", acc))
            genes = r.get("genes") or []
            gene = (genes[0].get("geneName") or {}).get("value", "") if genes else ""
            org = (r.get("organism") or {}).get("scientificName", "")
            length = (r.get("sequence") or {}).get("length")
            out.append(KnowledgeRecord(
                source=self.slug, entity_type=EntityType.PROTEIN,
                entity_name=f"{gene} ({acc})" if gene else acc, value=name,
                confidence=0.9, evidence_level=EvidenceLevel.AUTHORITATIVE_DB,
                citation=Citation(title=name, identifier=acc,
                                  url=f"https://www.uniprot.org/uniprotkb/{acc}/entry",
                                  company="UniProt", product=gene,
                                  document_version=r.get("entryType", "")),
                retrieved_time=now, license="CC-BY 4.0",
                notes=" · ".join(x for x in (org, f"{length} aa" if length else "") if x),
                raw=r))
        return out
