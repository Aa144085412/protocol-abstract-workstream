"""
PubMed / NCBI E-utilities — LIVE literature & protocol-citation provider.

Uses the public, programmatic NCBI E-utilities API (esearch -> esummary), which is
explicitly intended for automated access — unlike manufacturer protocol sites,
which have no public API and whose ToS forbid scraping (those stay as the
upload-the-manual provider). Returns peer-reviewed citations with full provenance.

Testability + safety:
  - An injectable ``http_get(url) -> str`` transport. Default transport uses the
    standard library and is gated by ``assert_online_allowed()`` (no network until
    the layer is explicitly enabled). Tests inject a fixture transport (no network).
  - NCBI etiquette: send tool + email (and optional api_key) params; cap results.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, List, Optional

from . import base_provider as bp
from .base_provider import KnowledgeProvider
from .models import Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _default_http_get(url: str) -> str:
    bp.assert_online_allowed()                 # raises unless NETWORK_ENABLED
    import urllib.request
    with urllib.request.urlopen(url, timeout=15) as r:   # noqa: S310 (trusted NCBI host)
        return r.read().decode("utf-8", "replace")


class PubMedProvider(KnowledgeProvider):
    slug = "pubmed"
    name = "PubMed / NCBI E-utilities"
    homepage = "https://pubmed.ncbi.nlm.nih.gov"
    status = ProviderStatus.PLANNED
    entity_types = (EntityType.LITERATURE, EntityType.PROTOCOL)
    capabilities = ("literature lookup (PubMed)", "citation + DOI retrieval",
                    "evidence linkage for recommendations")
    license_note = ("PubMed metadata is public; access via the official E-utilities API "
                    "with tool+email identification. No full-text scraping.")

    def __init__(self, http_get=None, email: str = "", api_key: str = "", tool: str = "lab-agent"):
        self._http = http_get          # None -> network-guarded default transport
        self.email = email
        self.api_key = api_key
        self.tool = tool

    # available if a transport is injected (tests/live) or the network flag is on
    def health(self) -> ProviderStatus:
        if self._http is not None:
            return ProviderStatus.AVAILABLE
        return ProviderStatus.AVAILABLE if bp.NETWORK_ENABLED else ProviderStatus.PLANNED

    def _get(self, url: str) -> str:
        return (self._http or _default_http_get)(url)

    def _params(self, **kw) -> str:
        p = {"tool": self.tool, **({"email": self.email} if self.email else {}),
             **({"api_key": self.api_key} if self.api_key else {}), **kw}
        return urllib.parse.urlencode(p)

    def query(self, entity_type: EntityType, query: str, max_results: int = 5,
              **context: Any) -> QueryResult:
        if entity_type not in self.entity_types or self.health() != ProviderStatus.AVAILABLE:
            return self._planned(entity_type, query)
        try:
            esearch = json.loads(self._get(
                f"{_EUTILS}/esearch.fcgi?{self._params(db='pubmed', term=query, retmode='json', retmax=max_results)}"))
            ids = (esearch.get("esearchresult", {}) or {}).get("idlist", []) or []
            if not ids:
                return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE, [], [])
            esum = json.loads(self._get(
                f"{_EUTILS}/esummary.fcgi?{self._params(db='pubmed', id=','.join(ids), retmode='json')}"))
            return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE,
                               self._records(esum), [])
        except Exception as exc:   # network/parse errors -> error envelope, never crash
            return QueryResult(self.slug, entity_type, query, ProviderStatus.ERROR, [],
                               [f"PubMed query failed: {exc}"])

    # ------------------------------------------------------------------ #
    def _records(self, esummary: Dict[str, Any]) -> List[KnowledgeRecord]:
        from .base_provider import KnowledgeProvider  # for utc via agents not needed
        from datetime import datetime
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        res = esummary.get("result", {}) or {}
        out: List[KnowledgeRecord] = []
        for uid in res.get("uids", []) or []:
            rec = res.get(uid, {}) or {}
            title = rec.get("title", "").rstrip(".")
            doi = ""
            for aid in rec.get("articleids", []) or []:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "")
            out.append(KnowledgeRecord(
                source=self.slug, entity_type=EntityType.LITERATURE, entity_name=title,
                value=title, confidence=0.6, evidence_level=EvidenceLevel.PEER_REVIEWED,
                citation=Citation(
                    title=title, identifier=f"PMID:{uid}", url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    publisher=rec.get("fulljournalname", ""), company="PubMed/NCBI",
                    catalog_number=(f"doi:{doi}" if doi else ""),
                    publication_date=rec.get("sortpubdate", "") or rec.get("pubdate", "")),
                retrieved_time=now, raw=rec))
        return out
