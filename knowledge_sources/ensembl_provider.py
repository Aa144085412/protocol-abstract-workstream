"""
Ensembl — LIVE gene / genomic-annotation provider via the public Ensembl REST API
(rest.ensembl.org). Returns authoritative gene records (ID, locus, biotype,
assembly) with provenance. Same injectable-transport pattern as the other live
providers.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from typing import Any, List

from . import base_provider as bp
from .base_provider import KnowledgeProvider
from .models import Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult

_BASE = "https://rest.ensembl.org/lookup/symbol"


def _default_http_get(url: str) -> str:
    bp.assert_online_allowed()
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:   # noqa: S310 (trusted Ensembl host)
        return r.read().decode("utf-8", "replace")


class EnsemblProvider(KnowledgeProvider):
    slug = "ensembl"
    name = "Ensembl"
    homepage = "https://www.ensembl.org"
    status = ProviderStatus.PLANNED
    entity_types = (EntityType.GENE,)
    capabilities = ("gene -> Ensembl ID, locus, biotype, assembly", "genomic annotations")
    license_note = "Ensembl data is open (Apache-2.0 / no-restriction); official REST API."

    def __init__(self, http_get=None, species: str = "homo_sapiens"):
        self._http = http_get
        self.species = species

    def health(self) -> ProviderStatus:
        if self._http is not None:
            return ProviderStatus.AVAILABLE
        return ProviderStatus.AVAILABLE if bp.NETWORK_ENABLED else ProviderStatus.PLANNED

    def _get(self, url: str) -> str:
        return (self._http or _default_http_get)(url)

    def query(self, entity_type: EntityType, query: str, max_results: int = 1,
              **context: Any) -> QueryResult:
        if entity_type not in self.entity_types or self.health() != ProviderStatus.AVAILABLE:
            return self._planned(entity_type, query)
        species = context.get("species", self.species)
        symbol = urllib.parse.quote(query.strip())
        url = f"{_BASE}/{species}/{symbol}?content-type=application/json"
        try:
            g = json.loads(self._get(url))
            return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE,
                               self._records(g), [])
        except Exception as exc:
            return QueryResult(self.slug, entity_type, query, ProviderStatus.ERROR, [],
                               [f"Ensembl query failed: {exc}"])

    def _records(self, g: dict) -> List[KnowledgeRecord]:
        if not g or not g.get("id"):
            return []
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        gid = g.get("id", "")
        locus = f"{g.get('seq_region_name','')}:{g.get('start','')}-{g.get('end','')}"
        return [KnowledgeRecord(
            source=self.slug, entity_type=EntityType.GENE,
            entity_name=f"{g.get('display_name','')} ({gid})", value=g.get("description", gid),
            confidence=0.9, evidence_level=EvidenceLevel.AUTHORITATIVE_DB,
            citation=Citation(title=g.get("description", gid), identifier=gid,
                              url=f"https://www.ensembl.org/{g.get('species','')}/Gene/Summary?g={gid}",
                              company="Ensembl", product=g.get("display_name", ""),
                              document_version=g.get("assembly_name", "")),
            retrieved_time=now,
            notes=" · ".join(x for x in (locus, g.get("biotype", ""), g.get("assembly_name", "")) if x and x != ":-"),
            raw=g)]
