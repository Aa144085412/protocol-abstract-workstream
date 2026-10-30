"""
knowledge_sources.base_provider
===============================
The abstract interface every knowledge provider implements. THIS IS ARCHITECTURE
ONLY — the base class provides safe, offline placeholder behavior so the rest of
the app can call a provider today and get a clear "planned, not implemented"
answer instead of an error or a network call.

Hard rule for the MVP: ``NETWORK_ENABLED is False``. No provider may make an
external request. A future implementation must call ``assert_online_allowed()``
before any network access, which raises until the layer is explicitly enabled.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, List, Optional

from .models import (
    Citation, EntityType, KnowledgeRecord, ProviderStatus, QueryResult, Recommendation,
)

# Global guard: the MVP NEVER goes online. Flip via the registry feature flag only
# once real adapters exist and the user has opted in.
NETWORK_ENABLED = False


class NetworkDisabledError(RuntimeError):
    pass


def assert_online_allowed() -> None:
    """Future adapters must call this before any external request."""
    if not NETWORK_ENABLED:
        raise NetworkDisabledError(
            "Knowledge layer network access is disabled. This is a placeholder "
            "provider; no external calls are permitted in the current build.")


class KnowledgeProvider(ABC):
    """Base class for all knowledge providers.

    Subclasses are mostly DECLARATIVE: set the class attributes (slug, name,
    homepage, entity_types, capabilities, license_note). The placeholder method
    bodies below are inherited as-is until a real adapter is written, so a
    provider is usable (returns a structured 'planned' result) from day one.
    """

    slug: str = "base"
    name: str = "Base Provider"
    homepage: str = ""
    status: ProviderStatus = ProviderStatus.PLANNED
    #: entity types this source will eventually serve
    entity_types: tuple = ()
    #: human-readable future capabilities (shown in docs / UI)
    capabilities: tuple = ()
    #: licensing / terms-of-use note (respected by future adapters)
    license_note: str = ""

    # ---- introspection (safe to call now) --------------------------------- #
    def metadata(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "homepage": self.homepage,
            "status": self.health().value,
            "entity_types": [e.value for e in self.entity_types],
            "capabilities": list(self.capabilities),
            "license_note": self.license_note,
        }

    def supported_entities(self) -> List[EntityType]:
        return list(self.entity_types)

    def supports(self, entity_type: EntityType) -> bool:
        return entity_type in self.entity_types

    def health(self) -> ProviderStatus:
        """Default: PLANNED (placeholder). A real adapter overrides this to report
        AVAILABLE / DISABLED / ERROR based on config + reachability."""
        return self.status

    # ---- retrieval API (placeholder bodies) ------------------------------- #
    def query(self, entity_type: EntityType, query: str, **context: Any) -> QueryResult:
        """Search the source for records matching a query. Placeholder: returns an
        empty, clearly-statused envelope. Never raises, never hits the network."""
        return self._planned(entity_type, query)

    def lookup(self, entity_type: EntityType, identifier: str) -> Optional[KnowledgeRecord]:
        """Fetch a single record by a stable identifier (catalog no., accession,
        enzyme id). Placeholder: None until implemented."""
        return None

    def recommend(self, context: Dict[str, Any]) -> List[Recommendation]:
        """Given an experimental context, propose ranked, cited recommendations.
        Placeholder: empty list until implemented."""
        return []

    def citation(self, record: KnowledgeRecord) -> Optional[Citation]:
        return record.citation

    # ---- helpers ---------------------------------------------------------- #
    def _planned(self, entity_type: Optional[EntityType], query: str) -> QueryResult:
        return QueryResult(
            provider=self.slug, entity_type=entity_type, query=query,
            status=self.health(), records=[],
            warnings=[f"'{self.name}' is a planned provider — not implemented; "
                      "no network access in this build."],
        )
