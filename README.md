# Lab Experimental Agent (prototype)

A purpose-built, bench-side **experiment execution assistant** — not a chatbot.
It turns an uploaded wet-lab protocol (PDF / DOCX / TXT / MD) into adaptive,
step-by-step bench instructions with checkpoints, timers, reagent/equipment
checklists, troubleshooting branches, and **surgical protocol revision** when
something goes wrong.

It runs out of the box in **DEMO_MODE** (no API key needed) and switches to live
Claude **or** OpenAI calls when you provide a key — routable per agent.

---

## AI features at a glance (what each button does)

Every AI action has a deterministic, grounded fallback in DEMO mode, and never
fabricates exact volumes/times/temperatures/speeds or catalog numbers — unknowns
stay `[confirm with source protocol]`. The agent behind each is in parentheses
with its `role` key (used for per-agent routing, below).

| Where | Button / action | What it does | Agent (`role`) |
|---|---|---|---|
| A. Input | **Parse protocol** | Extracts structured facts from uploaded/pasted text (1 or many files) | DocumentAgent (`document`) |
| A. Input | **Search the web for a protocol** | Finds an authoritative protocol online, returns facts + source URLs (live, Anthropic) | SearchAgent (`search`) |
| B. Parsed → C. Protocol | **Approve → generate** | Synthesizes a bench-ready protocol (steps, QC, branches, materials) | ProtocolAgent (`protocol`) |
| C. Protocol | _review banner_ | Critiques completeness, safety, missing controls/QC, over-invention | ReviewAgent (`review`) |
| C. Protocol | **🧠 Suggest design improvements** | Turns review findings + best practice into applyable controls, QC gates, human-review flags, safety notes, conflict reconciliation | ImproveAgent (`improve`) |
| C. Protocol / D. Bench | **✨ Expand into detailed steps** | Rewrites a sparse step into full, self-contained instructions (keeps `[confirm]` for unknowns) | StepExpandAgent (`expand`) |
| C. Protocol / D. Bench | **💬 Ask the AI** | Q&A scoped to the current protocol ("spin speed for step 5?", "what if low yield?") | ChatAgent (`chat`) |
| F. Fill | **🤖 AI-assisted fill** | Proposes values for every unconfirmed field (incl. those embedded in instructions); you review/edit/apply | FillAgent (`fill`) |
| F. Fill | **🔬 Auto-fill from kit(s)** | Fills unconfirmed values from one or more bundled kits (no model) | kit library (local) |
| E. Revision | **Generate revised protocol** | Surgically revises only the flagged step(s), bumps the version | ProtocolAgent (`protocol`) |
| G. Plan | **Generate day-by-day plan** | Splits into sessions at safe stops; hands-on vs walk-away time | PlannerAgent (`planner`) |
| 📁 Projects | **Generate Methods writeup** | Drafts a paper-style Methods section from saved experiments | MethodsAgent (`methods`) |

---

## Why it's cheap by design

| Task | Model tier | Why |
|---|---|---|
| Document parsing / fact extraction | **cheap** | narrow structured extraction |
| Web protocol search | **cheap** | retrieval + extraction (web_search tool) |
| Day/session planning | **cheap (Haiku)** | scheduling reasoning over known steps |
| Protocol revision (surgical) | **cheap** | edits a few steps, not synthesis |
| AI-assisted fill / chat | **cheap** | grounded value suggestion, Q&A |
| Methods writeup | **cheap (Haiku)** | prose from recorded facts |
| Protocol synthesis (v1) | **strong** | novel reasoning |
| Safety/completeness review | **strong** | safety-critical |
| Design improvement / step expand | **strong** | experiment-design reasoning |
| Static parsing, rendering, kit fill | **no model** | done locally in `tools/` |

Any of these can be re-pointed at a cheaper model (or OpenAI) per agent — see
**Live mode, providers & per-agent routing** below.

Document text extraction and all Markdown/JSON rendering happen locally with no
model calls, so paging through a protocol never costs anything.

---

## Bench toolkit (deterministic — no model, no source needed)

Some values shouldn't be "confirm with source" — they're computable. The Fill
page and Bench Mode include calculators that compute these exactly:

- **🧬 PCR designer** — from primer sequences + polymerase: nearest-neighbor
  primer **Tm** (SantaLucia, salt-corrected), **annealing temp**, **extension
  time** (amplicon ÷ enzyme rate), the standard **reaction recipe**, and the
  **thermocycling program**. On the Fill page it can insert the design straight
  into a PCR step.
- **🧮 Calculators** — **ligation** (ng of insert for an insert:vector molar
  ratio), **dilution** (C1V1 = C2V2, leave one field blank to solve it), and
  **cell seeding** (cells + stock/medium volumes for N wells with excess).

In Bench Mode these appear inline and **auto-open the relevant tab** based on the
current step (a "Prepare PCR mix" step opens PCR; "Seed cells"/"Transduce" opens
cell seeding; "Dilute…" opens Dilution).

**Three tiers for resolving a value:** *compute* (toolkit) → *retrieve/infer*
(AI fill: web lookup + standard-practice inference, sourced/labeled) → *ground*
(kit auto-fill from the bundled library). The **⚡ Auto-resolve** button runs kit
+ AI in one click. **Confidence is dynamic** (a 0–100 readiness score) and rises
as you fill values and add controls/QC — see the "📈 How to raise confidence"
panel on the Protocol page.

## Re-verify after edits

A dependency-free smoke test exercises every agent, tool, structure edit,
calculator, and the projects/methods flow in DEMO mode:

```bash
cd lab_agent_prototype
python -m tests.test_smoke      # exits non-zero on first failure
```

---

## Architecture

```
DocumentAgent (cheap)  ->  ProtocolAgent.generate (strong)  ->  ReviewAgent (strong)
                                      |
                                      v
                          Bench Mode (local, no calls)
                                      |
                         flag issue -> ProtocolAgent.revise (cheap)  -> v2, v3, ...
```

The reference pipeline is *Literature → Strategy → Feasibility → Protocol →
Execution → Review*. This MVP implements the prioritized subset:
**Document → Protocol → Bench → Revision → Review.** `BaseAgent` centralizes
model routing, retry, markdown-tolerant JSON parsing, DEMO_MODE mocks, and
structured error output.

### Project layout
```
lab_agent_prototype/
  app.py                  # Streamlit UI (input, parsed, protocol, bench, revision)
  .env.example
  requirements.txt
  README.md
  agents/
    base_agent.py         # routing, retry, JSON parsing, DEMO_MODE, errors
    document_agent.py     # parse -> structured protocol facts (cheap)
    protocol_agent.py     # generate (strong) + revise (cheap, surgical)
    review_agent.py       # approve/revise/reject critique (strong)
  tools/
    document_parser.py    # pdf/docx/txt/md text extraction (no model calls)
    save_artifact.py      # run dirs + JSON/Markdown rendering
  prompts/
    document_agent.txt
    protocol_agent.txt
    protocol_revision.txt
    review_agent.txt
  runs/                   # run_YYYYMMDD_HHMMSS/ outputs land here
  memory/
    sample_protocol.json        # reusable bench-ready template
    sample_input_protocol.md    # example source doc to upload in the demo
```

---

## Setup & run

```bash
cd lab_agent_prototype
python -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt

cp .env.example .env        # DEMO_MODE=true by default — no key needed
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

### Live mode, providers & per-agent routing
Edit `.env`, then **restart the server** (env vars load at startup; imported
agent modules are not reloaded on a browser refresh). JSON parsing tolerates
markdown-fenced, prose-wrapped, and even truncated responses.

Basic live (Anthropic):
```
DEMO_MODE=false
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_CHEAP_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_STRONG_MODEL=claude-sonnet-4-6
```

Controls:
- `LLM_PROVIDER` = `anthropic` (default) or `openai` — global default.
- `FORCE_CHEAP=true` — every agent uses the cheap model (e.g. **Haiku-only**),
  skipping the strong model entirely.
- **Per-agent overrides**: `<ROLE>_PROVIDER` and `<ROLE>_MODEL` for any role
  (`document`, `protocol`, `review`, `planner`, `search`, `chat`, `methods`,
  `fill`, `improve`, `expand`). A `<ROLE>_MODEL` wins over tier/provider defaults
  and `FORCE_CHEAP`. The sidebar's **Per-agent routing** expander shows the live
  mapping (🟣 Claude / 🟢 OpenAI) for every agent.

Example — **ChatGPT for the detailed work, Haiku for the cheap work**:
```
DEMO_MODE=false
LLM_PROVIDER=anthropic
FORCE_CHEAP=true                 # planner/review/methods/search/document -> Haiku
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
PROTOCOL_PROVIDER=openai         # protocol synthesis + revision -> GPT-4o
PROTOCOL_MODEL=gpt-4o
CHAT_PROVIDER=openai             # protocol Q&A -> GPT-4o
CHAT_MODEL=gpt-4o
EXPAND_PROVIDER=openai           # step detailing -> GPT-4o
EXPAND_MODEL=gpt-4o
```
Mixing providers needs both API keys. Install the OpenAI SDK once with
`pip install -r requirements.txt`. Live web search requires the Anthropic
provider (it uses Claude's `web_search` tool); on OpenAI it falls back to the
local kit library.

---

## User flow

1. **A. Input** — upload a protocol (or paste text), fill experiment name, assay
   type, sample type, # samples, experience level (beginner/intermediate/expert),
   and lab constraints. To try it fast, upload `memory/sample_input_protocol.md`.
2. **B. Parsed document** — review extracted title, materials, steps, and
   uncertain fields. Approve or revise.
3. **C. Protocol** — metrics (steps, QC gates, materials, open questions,
   confidence), tabs (Workflow / Materials / QC / Failure branches / Open
   questions), Review Agent verdict, and download buttons.
4. **D. Bench Mode** — one step at a time: time/temp/speed, instructions,
   expected observation, checkpoint, pause point, troubleshooting, **Mark
   complete**, and **Flag issue** (low yield, no band, high background, cell
   loss, low viability, wrong fragment size, reagent missing, equipment
   unavailable, other) + observation note.
5. **E. Revision** — flagged issues drive a surgical revision: only affected
   steps change, version increments (v1 → v2), and a revision log is appended.

### Navigation, filling values, and commercial kits
- **Clickable stage nav** at the top of every page — jump back to **A. Input**,
  **B. Parsed**, **C. Protocol**, **F. Fill details**, **D. Bench**, or
  **E. Revision** anytime. Returning to Input preserves and lets you edit your
  entries, then re-parse.
- **F. Fill details** — a per-field editor for every value the source left
  unknown: materials table, and per-step time / temperature / speed /
  instructions / reagents (with exact amounts). Edits update the protocol *in
  place* (version unchanged) and re-save the artifacts.
- **Commercial kit library** — verified, offline, zero-cost reference protocols
  retrievable as known memory. Two ways to use: *Load a kit* from the Input page
  to start from a ready protocol, or *Auto-fill from a kit* on the Fill page to
  fill only the unconfirmed fields of your parsed protocol (non-destructive —
  confirmed values are never overwritten). Search matches on name/vendor/keywords.

  Bundled kits (search any of these):

    - *Exact-value column kits* (volumes, spin speeds, times specified):
      QIAprep Spin Miniprep (QIAGEN), Monarch Plasmid Miniprep (NEB),
      Zyppy Plasmid Miniprep (Zymo), Zymo DNA Clean & Concentrator-5,
      Zymoclean Gel DNA Recovery (Zymo).
    - *Workflow scaffolds* (correct stage order, QC gates, decision points, and
      troubleshooting; quantitative values marked `[confirm with source protocol]`
      to fill from the official user guide): ZymoPURE II Midiprep / Maxiprep,
      Zymo Quick-DNA Miniprep (genomic), 10x Chromium Single Cell 3' GEX v3.1,
      PacBio SMRTbell HiFi library prep.

  Why two tiers: simple spin-column kits have well-documented exact volumes, so
  those are provided in full. Complex NGS prep (10x, PacBio) has many proprietary
  volumes/cycle numbers that vary by version — inventing them would violate the
  no-fabrication rule, so those load as honest scaffolds you complete from the
  official guide (the Fill page is built for exactly this). All values carry
  provenance; confirm against your kit lot.

  **Add your own kits** with zero edits to existing files: drop a JSON file into
  `memory/kits/` (one kit per file, including a `kit_meta` block, or a dict of
  kits). It's auto-discovered on load. `memory/kit_library.json` also still works.
- **Smart web search** (Input page → "Search the web for a protocol") — a
  `SearchAgent` retrieves protocols beyond the bundled library. With
  `DEMO_MODE=false` and an `ANTHROPIC_API_KEY`, it uses Anthropic's `web_search`
  server tool to find an authoritative source (manufacturer handbook,
  protocols.io, Methods section), extracts structured facts, and returns the
  **source URLs** — never inventing values (unknowns stay
  `[confirm with source protocol]`). In DEMO mode it falls back to searching the
  local library. Found results flow straight into the parse → generate pipeline.
- **Day-by-day execution plan** (Protocol page → "🗓 Plan by day", or the **G.
  Plan** nav) — a `PlannerAgent` chunks the protocol into sessions/days, breaking
  ONLY at safe stops (pause points) and overnight/long incubations, respecting a
  daily hands-on hours budget, and never splitting a time-critical sequence
  across a break. Each session lists its steps, estimated time, reagents to
  prepare, and *why* the day ends there. It routes to the cheap **Haiku** model
  when live (`DEMO_MODE=false`); a deterministic chunker runs in demo mode.
  Steps with unconfirmed times are flagged so you can fill them first. Plans save
  to `runs/.../plan_vN.json` and `plan_vN.md`. Each session also splits
  **hands-on** (active bench work) vs **walk-away** (unattended incubations/spins)
  time, so you can see how much you're actually tied to the bench.
- **Ask-AI chat** (bottom of the Protocol and Bench pages) — a `ChatAgent`
  scoped to the current protocol. Ask "spin speed for step 5?", "how much Buffer
  P2?", "what if low yield?", "how long will this take?". Live it uses the cheap
  **Haiku** model with the protocol as context; in demo mode it answers offline
  straight from the loaded protocol (step lookups, reagent amounts, troubleshooting).
  It never invents missing values — it points to the Fill page instead.
- **Projects & paper writing** (📁 Projects tab) — group experiments that worked
  into named projects. From the Protocol page, **💾 Save to project** records the
  full protocol plus an outcome (worked / in-progress / failed) and notes into
  `memory/projects/<name>/`. The Projects page lists saved experiments with
  status chips, lets you **reload** any of them in one click, and **Generate
  Methods writeup** drafts a publication-style Methods section (past tense, with
  materials + procedure + QC) you can download — offline-deterministic in demo,
  Haiku-polished when live. It never fabricates values: unknowns are written
  "(specify)".
- **Clickable past runs** — the sidebar lists recent runs with a step/version
  chip; click one to reload its protocol (and plan/review) into the workspace.
- **Dashboard-style UI** — a lightweight theme (accent color, rounded metric
  cards, soft shadows, card containers) makes the protocol overview and plan read
  like a dashboard rather than a form.
- **Combine multiple protocols** (Input page → multiselect → "Combine selected
  into one protocol") — selected protocols are concatenated into one sequential
  bench run with globally renumbered steps, a **stage** label on each step, and
  merged materials / QC gates / decision points / failure branches (step-id
  references are remapped to the new numbering). Models a real multi-stage day,
  e.g. Miniprep → Gel Recovery → Clean & Concentrate as one Bench Mode session.
- **Bench Mode checkmarks** — each step shows a reagent checklist with exact
  amounts and a per-action checkbox list, plus the explicit temperature, speed,
  and time. Steps with unconfirmed values surface a one-click jump to Fill.

### Outputs (per run, in `runs/run_YYYYMMDD_HHMMSS/`)
`input.json`, `parsed_document.json`, `protocol_v1.json`, `protocol_v1.md`,
`protocol_bench_v1.md`, `review_v1.json`, `protocol_v2.json` (if revised),
`session_log.json`.

---

## Safety & honesty guarantees

- Never invents volumes, times, temperatures, concentrations, or **catalog
  numbers**. Unknown values are written `[confirm with source protocol]`.
- Every step carries an **expected observation**, **checkpoint**, **pause
  point**, and **troubleshooting** branch.
- `human_review_required` is set whenever a step/revision changes sample
  handling, incubation conditions, reagent concentration, cleanup/purification,
  or scales outside the source range.
- Never claims a protocol is guaranteed to work; risky changes are flagged for a
  human.
- The Review Agent specifically checks for **over-invention** (values that
  should have been marked uncertain), missing QC, and missing controls.

This is an MVP for prototyping, not a validated lab system. Always confirm
against the original source protocol and your institution's safety guidance.
