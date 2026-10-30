"""
ChEMBL — LIVE small-molecule / bioactivity provider via the public EBI ChEMBL API
(ebi.ac.uk/chembl/api/data). Returns authoritative compound records (ChEMBL ID,
formula, MW, max clinical phase) with provenance. Same injectable-transport pattern.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from typing import Any, List

from . import base_provider as bp
from .base_provider import KnowledgeProvider
from .models import Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult

_BASE = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"


def _default_http_get(url: str) -> str:
    bp.assert_online_allowed()
    import urllib.request
    with urllib.request.urlopen(url, timeout=20) as r:   # noqa: S310 (trusted EBI host)
        return r.read().decode("utf-8", "replace")


class ChEMBLProvider(KnowledgeProvider):
    slug = "chembl"
    name = "ChEMBL"
    homepage = "https://www.ebi.ac.uk/chembl"
    status = ProviderStatus.PLANNED
    entity_types = (EntityType.SMALL_MOLECULE,)
    capabilities = ("small molecules, targets, bioactivity",
                    "compound -> ChEMBL ID, formula, MW, clinical phase")
    license_note = "ChEMBL data is CC-BY-SA 3.0; official EBI REST API."

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
        params = urllib.parse.urlencode({"pref_name__iexact": query.strip(), "limit": max_results})
        try:
            data = json.loads(self._get(f"{_BASE}?{params}"))
            return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE,
                               self._records(data), [])
        except Exception as exc:
            return QueryResult(self.slug, entity_type, query, ProviderStatus.ERROR, [],
                               [f"ChEMBL query failed: {exc}"])

    def _records(self, data: dict) -> List[KnowledgeRecord]:
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        out: List[KnowledgeRecord] = []
        for m in data.get("molecules", []) or []:
            cid = m.get("molecule_chembl_id", "")
            name = m.get("pref_name", cid)
            props = m.get("molecule_properties") or {}
            notes = " · ".join(x for x in (
                f"MW {props.get('full_mwt')}" if props.get("full_mwt") else "",
                props.get("full_molformula", ""),
                f"max phase {m.get('max_phase')}" if m.get("max_phase") else "") if x)
            out.append(KnowledgeRecord(
                source=self.slug, entity_type=EntityType.SMALL_MOLECULE,
                entity_name=f"{name} ({cid})", value=name, confidence=0.9,
                evidence_level=EvidenceLevel.AUTHORITATIVE_DB,
                citation=Citation(title=name, identifier=cid,
                                  url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{cid}/",
                                  company="ChEMBL", product=name),
                retrieved_time=now, license="CC-BY-SA 3.0", notes=notes, raw=m))
        return out
