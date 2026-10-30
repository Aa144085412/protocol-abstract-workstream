"""
PDFManualProvider — manufacturer values from UPLOADED kit manuals (offline,
ToS-safe). Manufacturer protocol sites have no public API and their ToS forbid
scraping, so the legitimate way to use vendor data is the document the user
already has: their kit manual / product insert. This provider indexes that text
and serves value-bearing snippets as vendor_spec records, fully cited.

Self-contained (its own small unit regexes) so knowledge_sources does not depend
on the app's tools. No network.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base_provider import KnowledgeProvider
from .models import Citation, EntityType, EvidenceLevel, KnowledgeRecord, ProviderStatus, QueryResult

# dimension -> value regex (local copy; keeps this package independent of tools/)
_RX = {
    "volume": r"\d+(?:\.\d+)?\s?(?:µl|ul|μl|ml|l)\b",
    "mass": r"\d+(?:\.\d+)?\s?(?:pg|ng|µg|ug|μg|mg|g)\b",
    "temperature": r"-?\d+(?:\.\d+)?\s?°?\s?c\b",
    "time": r"\d+(?:\.\d+)?\s?(?:s|sec|secs|min|mins|h|hr|hrs|hour|hours|day|days)\b|overnight",
    "speed": r"\d[\d,]*\s?(?:x\s?g|×\s?g|rpm|rcf)\b",
    "concentration": r"\d+(?:\.\d+)?\s?(?:pg|ng|µg|ug|mg)\s?/\s?(?:µl|ul|ml|l)\b",
}
_STOP = {"the", "a", "an", "of", "to", "and", "in", "for", "with", "on", "by", "at",
         "use", "add", "step", "from", "into", "per", "this"}


class PDFManualProvider(KnowledgeProvider):
    slug = "pdf_manual"
    name = "Uploaded kit manuals"
    homepage = ""
    status = ProviderStatus.PLANNED
    entity_types = (EntityType.PROTOCOL, EntityType.REAGENT_KIT, EntityType.REAGENT_PRODUCT)
    capabilities = ("extract values from uploaded manufacturer manuals / product inserts",
                    "cited vendor_spec values without scraping vendor sites")
    license_note = "Uses the user's own uploaded documents; no external requests."

    def __init__(self, manuals: Optional[List[Dict[str, Any]]] = None):
        # each manual: {title, company, product, catalog_number, version, url, text}
        self.manuals: List[Dict[str, Any]] = manuals or []

    def add_manual(self, text: str, *, title: str = "", company: str = "", product: str = "",
                   catalog_number: str = "", version: str = "", url: str = "") -> None:
        self.manuals.append({"title": title, "company": company, "product": product,
                             "catalog_number": catalog_number, "version": version,
                             "url": url, "text": text or ""})

    def health(self) -> ProviderStatus:
        return ProviderStatus.AVAILABLE if self.manuals else ProviderStatus.PLANNED

    def query(self, entity_type: EntityType, query: str, max_results: int = 5,
              **context: Any) -> QueryResult:
        if entity_type not in self.entity_types or not self.manuals:
            return self._planned(entity_type, query)
        etype = context.get("expected_type")
        rxs = self._regexes(etype)
        terms = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 3 and t not in _STOP}
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        records: List[KnowledgeRecord] = []
        seen = set()
        for man in self.manuals:
            text = man.get("text", "") or ""
            for rx in rxs:
                for m in re.finditer(rx, text, re.I):
                    window = text[max(0, m.start() - 110): m.end() + 40]
                    if terms and not any(t in window.lower() for t in terms):
                        continue
                    val = m.group(0).strip()
                    dedup = (man.get("catalog_number", ""), val.lower())
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    records.append(KnowledgeRecord(
                        source=self.slug, entity_type=entity_type, entity_name=val,
                        value=val, confidence=0.8, evidence_level=EvidenceLevel.VENDOR_SPEC,
                        citation=Citation(
                            title=man.get("title", "kit manual"), company=man.get("company", ""),
                            product=man.get("product", ""), catalog_number=man.get("catalog_number", ""),
                            document_version=man.get("version", ""), url=man.get("url", ""),
                            identifier=man.get("catalog_number", "")),
                        retrieved_time=now,
                        notes=" ".join(window.split()),   # the supporting snippet
                    ))
                    if len(records) >= max_results:
                        return QueryResult(self.slug, entity_type, query,
                                           ProviderStatus.AVAILABLE, records, [])
        return QueryResult(self.slug, entity_type, query, ProviderStatus.AVAILABLE, records, [])

    @staticmethod
    def _regexes(expected_type: Optional[str]) -> List[str]:
        if not expected_type:
            return list(_RX.values())
        if expected_type == "material_amount":
            return [_RX["mass"], _RX["volume"]]
        return [_RX[expected_type]] if expected_type in _RX else list(_RX.values())
