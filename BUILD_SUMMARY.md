# Executive Lab Agent — Build Summary (for records / paper)

A reference of everything built turning the prototype into a **provenance-carrying,
dependency-aware protocol compiler**. Status at writing: **155 tests passing**,
across 20 test files; new logic is deterministic, offline-by-default, and opt-in
where it touches the network — the original MVP behaves the same until enabled.

## One-sentence framing

We don't search biology for you; we **compile a messy protocol into a standardized,
executable, reproducible workflow** — removing every decision that trusted knowledge
can make, and labeling every value with where it came from, how confident we are,
and whether you still need to confirm it.

## Core invariants (hold across every subsystem)

1. **Never present a guess as a source value.** Suggestions live in a side-car
   registry; only source/kit/calculation/user-confirmed values ever enter the
   protocol tree (*tree-safety*).
2. **Every value is traceable** — provenance, confidence, risk, and a "why".
3. **The AI proposes; evidence or the user confirms.** A model can never self-promote
   a value into a confirmed status.
4. **Deterministic core, AI for judgment.** Validation, units, scaling, retrieval
   parsing, and the dependency graph are auditable rules; agents handle the fuzzy work
   and always fall back to deterministic behavior offline (DEMO_MODE).

## Subsystems

### 1. Active uncertainty layer (value provenance)
`tools/uncertainty_slots.py`, `value_promoter.py`, `provenance_tracker.py`,
`evidence_resolver.py`, `suggest_value.py`, `readiness.py` (+ `UNCERTAINTY_OBJECTS_DESIGN.md`).
Every missing value becomes a structured object with a **status** in three bands —
CONFIRMED (source/kit/calculated/user), PARTIAL (literature/typical/ai_suggested),
SPECIAL (unresolved/conflict/not_applicable). `value_promoter` is the only writer,
enforcing an allow-matrix (no guess→confirmed) and a conflict guard (a differing
value never overwrites a confirmed one). Readiness Factor-1 is evidence-weighted,
so AI-only suggestions can't float a protocol to "high".

### 2. Value policy: propose-and-label, risk-tiered
The agent **does** suggest defaults, but every one carries provenance + an
`inference_basis` + a risk tier. High-impact fields (tagmentation time, MOI,
nuclei/10x loading, electroporation, antibiotic/drug dose, FACS gates,
ultracentrifuge, sc-library PCR cycles, …) are escalated to high risk and always
require confirmation. UI badges: Source value / You confirmed / Suggested default /
Needs confirmation / Not applicable.

### 3. Route discovery (workflow uncertainty)
`tools/route_library.py`, `route_questions.py`, `agents/context_digest_agent.py`
(+ `memory/route_library.json`). Distinguishes *route* uncertainty ("plate cells" →
several workflows) from *value* uncertainty. Detects route-ambiguous phrases
semantically (not just keywords), proposes 2–5 routes, and asks only the blocking
question — gating generation until the user chooses.

### 4. Slot applicability triage (decision tree)
`tools/slot_triage.py`, `agents/slot_triage_agent.py`. Retires flags that are schema
artifacts (a centrifuge speed on a plating step) with a reason + audit trail, so the
human only sees flags that truly need them. AI decision-tree live; deterministic tree
offline.

### 5. Standardization core
`tools/standard_units.py` (one canonical unit per dimension — mass→ng, volume→µL,
molarity→M, moles→mol, concentration→ng/µL, cells, U, °C; parses `2.5×10⁵`/`2.5e5`/
superscripts; `convert`/`same_dimension`). `tools/vessels.py` (vessel geometry DB +
area/working-volume scaling; resolves "T75"/"100 mm dish"/"6-well").

### 6. Standardized defaults engine
`tools/standard_defaults.py` + `memory/standard_defaults.json`, `tools/defaults_engine.py`.
A curated catalog of accepted starting values (restriction input, Gibson ratio, RNA
input, seeding density, miniprep volume, …) and a recommendation ladder:
**evidence → catalog → typical → AI → needs-confirmation**, returning value_promoter-
ready proposals so a parsed protocol arrives mostly pre-filled with cited defaults.

### 7. Knowledge integration layer (live retrieval)
`knowledge_sources/` — `KnowledgeProvider` interface, `KnowledgeBroker` (ranking by
authority × specificity × recency × confidence), on-disk `cache.py`, `models.py`
(`KnowledgeRecord` + `Citation` with company/product/catalog/version/date/URL).
- **Live, real APIs:** PubMed (NCBI E-utilities), **UniProt**, **Ensembl**, **ChEMBL**.
- **Live, ToS-safe:** `PDFManualProvider` over the user's uploaded kit manuals.
- **Placeholders (no public API; scraping is ToS-barred):** NEB, REBASE, Addgene,
  PrimerBank, IDT, Thermo, QIAGEN, Takara, Sigma — usable via uploaded manuals.
Wired into `evidence_resolver` as a tier (inert unless a broker is passed + enabled)
and into the UI via the Resolve "Use knowledge sources" toggle + a gene/protein/
molecule/literature lookup panel. Each retrieved value maps to the uncertainty model
(authoritative_db→source_confirmed, vendor_spec→kit_confirmed, paper→literature).

### 8. Protocol as a living dependency graph
`tools/protocol_graph.py` (reactive recompute with explanations + lockable nodes;
deterministic transforms reuse vessels/units), `tools/slot_roles.py` (semantic role
tagging: media_volume, wash_volume, lysis_volume, cell_number, rna_input, spin_speed,
…), `tools/protocol_binding.py` (binds a real change to dependent slots: vessel →
media/wash volumes; cell number → lysis volume + RNA-yield estimate). Recomputed
values are explained suggestions; confirmed values are never silently overwritten.

## UI (Streamlit, opt-in additions)
- Consolidated workflow: **Input · Parse · Design (Review+Fill+Resolve) · Plan · Bench · Revise**.
- Input intake: research goal + background/manual upload.
- Resolve: bulk **Auto-resolve** (evidence/catalog/typical), **Triage**, knowledge
  toggle + per-slot Search/AI/typical/N-A, provenance badges + citations.
- Design hub: **Scientific references** panel, **Vessel & context-aware scaling**
  control, **knowledge lookup** panel.
- Plan: in-app calendar (live progress) + **what-if vessel scaler**.
- Emoji replaced by text + small SVG.

## Design docs in repo
`UNCERTAINTY_OBJECTS_DESIGN.md` (value model + value policy), `PRODUCT_REDESIGN.md`
(10-part redesign + knowledge-graph idea + roadmap), `knowledge_sources/ARCHITECTURE.md`
(retrieval layer), this file.

## Test coverage (155 across 20 files)
Uncertainty core, evidence/suggest, prompt-contract + philosophy ("spin 5 min, no
speed"), route discovery, slot triage, value policy, standard units, vessels,
standard defaults, defaults engine, knowledge sources + retrieval/cache/ranking,
PubMed/UniProt/Ensembl/ChEMBL providers (real fixtures), PDF-manual provider,
evidence knowledge tier, slot roles + binding, protocol graph.

## What's live vs future
- **Live now:** standardization, defaults, 4 real knowledge APIs + uploaded manuals,
  provenance, dependency graph, role-based vessel/cell binding — all opt-in.
- **Future (one provider file each, behind the same interface):** protocols.io
  (token API), additional public APIs; deeper graph chains; a true right-rail layout;
  contextual calculator sidebar from `PRODUCT_REDESIGN.md`.
