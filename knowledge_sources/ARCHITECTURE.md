# Knowledge Integration Layer — Architecture (placeholders only)

**Status: architecture only. Nothing here is implemented, nothing makes a network
call, and nothing in the app imports this package. The MVP behaves exactly as
before.** This document defines the seams so future retrieval plugs in without a
refactor.

## Why

A core philosophy of this project: **the AI should not invent known scientific
information.** When a reliable fact already exists in an authoritative source, the
agent should *retrieve it, cite it, reason over it, and present a transparent,
provenance-carrying recommendation.*

This evolves the architecture from:

```
LLM + deterministic validation
```

to:

```
LLM (orchestrator) + authoritative knowledge retrieval + deterministic validation + provenance
```

The LLM stops being a black box of remembered facts and becomes an **orchestrator**
that integrates retrieved facts, resolves conflicts, explains trade-offs, and adapts
to experimental context — while a human confirms and every claim is auditable.

## Two kinds of knowledge, one safety model

This layer slots cleanly beside the two uncertainty layers already in the app:

| Layer | Question | Module |
|---|---|---|
| Value uncertainty | "spin" but no speed | `tools/uncertainty_slots` + `evidence_resolver` |
| Route uncertainty | "plate cells" but no starting state | `tools/route_questions` + `ContextDigestAgent` |
| **Knowledge retrieval** | "which enzyme / primer / kit?" — a *known fact* | **`knowledge_sources/` (this layer)** |

A retrieved `KnowledgeRecord` maps onto the **existing** value-uncertainty evidence
model, so retrieval *confirms* a slot with provenance rather than letting the model
guess (`KnowledgeRecord.to_uncertainty_evidence()` + `suggested_uncertainty_status()`):

| Evidence level | Uncertainty status it may justify |
|---|---|
| `authoritative_db` (REBASE, NCBI) | `source_confirmed` |
| `vendor_spec` (NEB, IDT, vendors) | `kit_confirmed` |
| `peer_reviewed` (PubMed, Nature Protocols) | `literature_supported` |
| `community` | `literature_supported` |
| `ai_inferred` | `ai_suggested` |

So the **same guardrails apply**: only authoritative/vendor/calc/user evidence can
move a value into a "confirmed" status; an AI inference stays a suggestion.

## Folder structure

```
knowledge_sources/
  __init__.py          # exports + the single entry point (KnowledgeBroker)
  models.py            # KnowledgeRecord, Citation, Recommendation, QueryResult + enums
  base_provider.py     # KnowledgeProvider ABC + offline placeholder behavior + network guard
  registry.py          # REGISTRY, KnowledgeBroker, feature flag
  neb_provider.py      # molecular cloning (enzymes, buffers, assembly, PCR)
  rebase_provider.py   # restriction enzyme database
  addgene_provider.py  # plasmids / vectors / backbones
  primerbank_provider.py  # validated qPCR primers
  idt_provider.py      # oligos / primer analysis / CRISPR guides
  thermo_provider.py   # RT-qPCR kits / reagents
  qiagen_provider.py   # extraction / sample-prep kits
  takara_provider.py   # PCR / cDNA / In-Fusion
  sigma_provider.py    # chemicals / reagents
  pubmed_provider.py   # literature + protocol repositories
  ARCHITECTURE.md      # this file
```

## Interfaces

**`KnowledgeProvider`** (abstract; subclasses are mostly declarative):

```
metadata()             -> dict (name, homepage, status, entity_types, capabilities, license)
supported_entities()   -> [EntityType]
health()               -> ProviderStatus  (PLANNED until a real adapter exists)
query(entity_type, q)  -> QueryResult     (placeholder: empty, status=PLANNED, no network)
lookup(entity_type, id)-> KnowledgeRecord | None
recommend(context)     -> [Recommendation]
citation(record)       -> Citation
```

**`KnowledgeBroker`** (registry.py) — the only thing the app will call:

```
retrieve(entity_type, query, sources=None, context=None) -> [QueryResult]
recommend(context, entity_type=None, sources=None)       -> [Recommendation]
health()                                                  -> {slug: status}
```

Disabled by default (`KNOWLEDGE_SOURCES_ENABLED=false`) → returns a `DISABLED`
envelope with empty records, so adding the layer changes nothing until opted in.

## Unified Knowledge Object

`KnowledgeRecord`: `source`, `entity_type`, `entity_name`, `value`, `confidence`,
`evidence_level`, `citation`, `retrieved_time`, `assumptions`, `notes`, `license`,
`version`, `raw`. Every provider normalizes its native payload into this shape.

## Provenance (mandatory, never hidden)

Every recommendation preserves: **source · version · retrieved_time · citation ·
the original retrieved recommendation · the LLM's reasoning · the final user
decision.** The reasoning that integrates records is logged separately from the
records themselves, so a reader can always tell a **retrieved fact** from **AI
reasoning**. This reuses the app's existing `provenance_tracker` audit pattern.

## Recommendation pipeline (future)

```
User question
  -> Planner Agent
  -> KnowledgeBroker.retrieve()   (fan-out to providers for the entity type)
  -> trusted sources              (NEB / REBASE / Addgene / PrimerBank / IDT / vendors / PubMed)
  -> KnowledgeRecords             (normalized + cited)
  -> Reasoning Agent              (integrate, resolve conflicts, rank, explain WHY)
  -> Deterministic validation     (protocol_check, mol_tools, pcr_design)
  -> Ranked Recommendations       (with provenance + tradeoffs + cost/success estimates)
  -> User confirmation            (value_promoter.user_confirm)
  -> Audit log                    (provenance_tracker)
```

### Example — cloning strategy
`Read plasmid → find restriction sites → query NEB + REBASE → compare Gibson vs
Golden Gate → estimate complexity / cost / success → recommend + explain WHY`,
every step citing the source record.

### Example — qPCR for knockdown validation
`Read target genes → query PrimerBank (validated primers) → recommend Thermo RT
kit + RNA extraction kit → generate plate layout + reagent calculator + ordering
checklist + citations → emit SOP`, with primers `peer_reviewed` and kits
`vendor_spec`.

## Integration points (documented, NOT wired)

1. **`tools/evidence_resolver.py`** — add a future tier
   `from_knowledge_sources(obj, proto)` between kit (tier 2) and reference (tier 5):
   call `KnowledgeBroker.retrieve(...)`, map each `KnowledgeRecord` →
   `to_uncertainty_evidence()` → `value_promoter.auto_resolve(...)`. Confirms a slot
   with a real citation; AI-inferred records stay `ai_suggested`.
2. **`agents/` reasoning** — a future `RecommendationAgent` consumes `[KnowledgeRecord]`
   and returns `[Recommendation]`; prompt mandates "cite a record for every claim;
   never state a fact without a supporting record."
3. **UI** — a "Recommendations" panel (likely inside the Design hub) showing each
   option with its citations, confidence, tradeoffs, and an Accept→`user_confirmed`
   button (same pattern as Resolve).

## Guardrails carried forward

- **No network in this build** (`NETWORK_ENABLED = False`; `assert_online_allowed()`
  raises). Future adapters must respect each source's license/ToS (see each
  provider's `license_note`) and prefer official APIs over scraping.
- **Never invent**: vendor/catalog/enzyme/primer facts come from a record or stay
  unresolved — mirroring the `[confirm with source protocol]` contract.
- **Retrieval ≠ confirmation by the model**: a record only confirms a value to the
  status its evidence level allows; the user (or genuine evidence) still confirms.

## TODO roadmap (per source)

- [ ] NEB: enzyme lookup, Double Digest Finder (buffer compatibility), NEBuilder/Golden Gate guidance (official API/data where available).
- [ ] REBASE: enzyme + recognition site + methylation sensitivity (academic data dump).
- [ ] Addgene: plasmid metadata + backbone features + reference linkage.
- [ ] PrimerBank: validated qPCR primer retrieval (human/mouse).
- [ ] IDT: OligoAnalyzer-style primer QC + CRISPR guide design (API/account-gated).
- [ ] Thermo / QIAGEN / Takara / Sigma: catalog + context-aware product recommendation.
- [ ] PubMed: abstract/DOI retrieval; protocols.io / Nature Protocols linkage.
- [ ] `RecommendationAgent` + prompt; `evidence_resolver.from_knowledge_sources`; Recommendations UI panel.
- [ ] Conflict resolution + ranking across sources; cost/success estimators.
- [ ] Caching layer (`memory/knowledge_cache/`) with `retrieved_time` + `version` for reproducibility.
