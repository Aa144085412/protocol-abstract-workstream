"""
Lab Experimental Agent — Streamlit prototype
============================================
A purpose-built bench-side execution assistant (NOT a chatbot). It turns an
uploaded protocol into adaptive, step-by-step bench instructions with
checkpoints, timers, checklists, troubleshooting branches, and surgical
protocol revision.

Run:
    pip install -r requirements.txt
    streamlit run app.py

Set DEMO_MODE=true (default) to run with no API key.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

# Load .env BEFORE importing agents so env routing is picked up.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import streamlit as st

import compat
compat.apply()  # tolerate older Streamlit versions (e.g. Anaconda's 1.12)

from agents import (
    DocumentAgent, ProtocolAgent, ReviewAgent, SearchAgent, PlannerAgent, ChatAgent,
    MethodsAgent, FillAgent, ImproveAgent, StepExpandAgent, DesignAgent,
    LiteratureAgent, SummaryAgent, EducatorAgent, AuditAgent,
    ExperimentDesignAgent, SuggestAgent, ContextDigestAgent, SlotTriageAgent,
)
from agents.base_agent import utc_timestamp
from agents.document_agent import classify_doc
from tools import projects as proj
from tools.fill_slots import list_slots, write_slot, apply_values
from tools import uncertainty_slots, value_promoter, typical_values
from tools import evidence_resolver, suggest_value
from tools import route_library, route_questions
from tools import slot_triage
from tools import vessels, protocol_graph, standard_units
from tools import protocol_binding, slot_roles
from tools import defaults_engine, consistency, reaction_scaling
from tools import assay_gaps, sanity_check, flow_check, known_reagents, sequence_scan, field_hygiene
from tools import reagent_placement
from tools.protocol_check import _VOLUME, _MASS, _TEMP, _SPEED, _TIME
from tools.step_ops import (
    merge_steps, suggest_merges, split_step, move_step, delete_step, move_to_preconditions,
)
from tools.readiness import compute_readiness
from tools.pcr_design import design_pcr, design_to_instructions, polymerases
from tools.mol_tools import ligation_insert_ng, dilution, cell_seeding
from tools import (
    extract_text,
    SUPPORTED_EXTENSIONS,
    new_run_dir,
    save_json,
    save_text,
    protocol_to_markdown,
    bench_to_markdown,
    plan_to_markdown,
    list_kits,
    search_kits,
    get_kit,
    apply_kit,
    combine_protocols,
    count_confirm,
)
from tools.kit_lookup import detect_format_questions
from tools.save_artifact import RUNS_DIR, normalize_protocol

CONFIRM_TAG = "[confirm with source protocol]"

st.set_page_config(page_title="Lab Experimental Agent", page_icon="", layout="wide")

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() in ("1", "true", "yes", "on")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()
FORCE_CHEAP = os.environ.get("FORCE_CHEAP", "false").lower() in ("1", "true", "yes", "on")
if LLM_PROVIDER == "openai":
    CHEAP_MODEL = os.environ.get("OPENAI_CHEAP_MODEL", "gpt-4o-mini")
    STRONG_MODEL = os.environ.get("OPENAI_STRONG_MODEL", "gpt-4o")
else:
    CHEAP_MODEL = os.environ.get("ANTHROPIC_CHEAP_MODEL", "claude-haiku-4-5-20251001")
    STRONG_MODEL = os.environ.get("ANTHROPIC_STRONG_MODEL", "claude-sonnet-4-6")

FLAG_OPTIONS = [
    "Low yield", "No band", "High background", "Cell loss", "Low viability",
    "Wrong fragment size", "Reagent missing", "Equipment unavailable", "Other",
]


# ---------------------------------------------------------------------- #
# Session state
# ---------------------------------------------------------------------- #
def init_state():
    ss = st.session_state
    ss.setdefault("page", "input")          # input | parsed | protocol | bench | revision
    ss.setdefault("run_dir", None)
    ss.setdefault("input_meta", {})
    ss.setdefault("raw_text", "")
    ss.setdefault("parsed", None)
    ss.setdefault("parsed_docs", [])
    ss.setdefault("source_docs", [])        # uploaded docs (name, type, text) for grounding
    ss.setdefault("user_level", "intermediate")  # global experience level (sidebar)
    ss.setdefault("live_mode", not DEMO_MODE)     # Live (API) vs Offline (mock) toggle
    ss.setdefault("current_exp_id", None)   # the saved experiment we're updating in place
    ss.setdefault("doc_include", {})
    ss.setdefault("input_reveal", False)    # show the welcome landing before the form
    ss.setdefault("protocol", None)         # current protocol (latest version)
    ss.setdefault("protocol_v1", None)
    ss.setdefault("review", None)
    ss.setdefault("completed_steps", set())
    ss.setdefault("flagged", {})            # step_id -> {issue_type, observation}
    ss.setdefault("session_log", [])
    ss.setdefault("bench_idx", 0)
    ss.setdefault("search_results", None)
    ss.setdefault("plan", None)
    ss.setdefault("chat_history", [])
    ss.setdefault("current_project", "")
    ss.setdefault("methods_md", None)
    ss.setdefault("_resumed", None)
    ss.setdefault("fill_suggestions", None)
    ss.setdefault("improve_suggestions", None)
    ss.setdefault("_orig_instr", {})
    ss.setdefault("fill_context", "")


def log_event(kind: str, detail: dict):
    st.session_state.session_log.append(
        {"time": utc_timestamp(), "event": kind, "detail": detail}
    )
    if st.session_state.run_dir:
        save_json(st.session_state.run_dir, "session_log.json", st.session_state.session_log)


def reset_run():
    """Start a completely clean run. EVERYTHING tied to a previous run or project is
    wiped so no stale content (old protocol, cached summary/brief/literature/lesson,
    source docs, or the previously-open project) can bleed into — and hallucinate
    over — the new experiment. Only global preferences (experience level, Live/Offline,
    model routing) are preserved."""
    ss = st.session_state
    for k in ("run_dir", "parsed", "protocol", "protocol_v1", "review", "raw_text"):
        ss[k] = None if k != "raw_text" else ""
    ss.input_meta = {}
    ss.parsed_docs = []
    ss.source_docs = []
    ss.completed_steps = set()
    ss.flagged = {}
    ss.session_log = []
    ss.bench_idx = 0
    ss.search_results = None
    ss.plan = None
    ss.current_exp_id = None
    ss.input_reveal = False   # back to the welcome landing
    ss.chat_history = []
    ss.page = "input"
    # --- the parts that previously leaked across runs ---
    ss.current_project = ""        # don't stay attached to the old project
    ss.methods_md = None
    ss.fill_suggestions = None
    ss.improve_suggestions = None
    ss.fill_context = ""
    ss.doc_include = {}
    ss._orig_instr = {}
    ss._resumed = None
    # cached agent outputs (Learn brief/summary/literature/lesson, Design, helper keys)
    for k in list(ss.keys()):
        if (k.startswith("learn_") or k.startswith("design_") or k.startswith("valsugg_")
                or k in ("brief", "_learn_loaded", "_learn_cache_for", "_design_cache_for",
                         "design_result", "_repair_changes", "audit_result_proto")):
            ss.pop(k, None)


def save_progress():
    """Persist bench position + completed/flagged so the user can resume later."""
    rd = st.session_state.run_dir
    if not rd:
        return
    try:
        save_json(rd, "progress.json", {
            "bench_idx": st.session_state.bench_idx,
            "completed_steps": sorted(st.session_state.completed_steps),
            "flagged": st.session_state.flagged,
            "updated_at": utc_timestamp(),
            "protocol_version": (st.session_state.protocol or {}).get("protocol_version", "v1"),
        })
    except Exception:
        pass


def persist_protocol(proto: dict):
    """Re-save the current protocol's JSON + Markdown artifacts (edit-in-place)."""
    normalize_protocol(proto)
    rd = st.session_state.run_dir
    if not rd:
        return
    ver = proto.get("protocol_version", "v1")
    save_json(rd, f"protocol_{ver}.json", proto)
    save_text(rd, f"protocol_{ver}.md", protocol_to_markdown(proto))
    save_text(rd, f"protocol_bench_{ver}.md", bench_to_markdown(proto))


def apply_correction(correction: str, history_msgs=None, reference_text: str = "") -> bool:
    """Apply a plain-language scientific correction as a new protocol version.

    Routes the current protocol + correction (and optional pasted/uploaded
    reference protocol text) through ProtocolAgent's correction-revision (strong
    model live; logged-only fallback in DEMO). On success: installs the new
    version, saves artifacts, logs the change and stores a flash for the UI.
    Returns True on success."""
    correction = (correction or "").strip()
    if not correction:
        return False
    proto = st.session_state.get("protocol") or {}
    hist = ""
    for h in (history_msgs or [])[-6:]:
        hist += f"\n{h.get('role','user').upper()}: {h.get('content','')}"
    from_ver = proto.get("protocol_version", "v1")
    with st.spinner(f"Applying your correction → revising {from_ver}…"):
        revised = ProtocolAgent().revise_with_correction(
            proto, correction, hist, reference_text=reference_text)
    if revised.get("status") == "error":
        st.session_state["_correction_flash"] = ("error", revised.get("error", "revision failed"))
        return False
    normalize_protocol(revised)
    to_ver = revised.get("protocol_version", _bump(from_ver))
    rd = st.session_state.run_dir
    if rd:
        save_json(rd, f"protocol_{to_ver}.json", revised)
        save_text(rd, f"protocol_{to_ver}.md", protocol_to_markdown(revised))
        save_text(rd, f"protocol_bench_{to_ver}.md", bench_to_markdown(revised))
    st.session_state.protocol = revised
    log_event("protocol_corrected", {
        "from": from_ver, "to": to_ver, "correction": correction[:200],
        "changed_step_ids": revised.get("changed_step_ids", []),
    })
    import re as _re
    had_url = bool(_re.search(r"https?://", correction))
    st.session_state["_correction_flash"] = ("success", {
        "from": from_ver, "to": to_ver,
        "summary": revised.get("summary_of_changes", ""),
        "diagnosis": revised.get("root_cause_diagnosis", ""),
        "changed": revised.get("changed_step_ids", []),
        "had_url": had_url,
        "retrieved": bool(revised.get("_retrieved_reference")),
        "ref_source": revised.get("_reference_source", "none"),
    })
    return True


# ---------------------------------------------------------------------- #
# Sidebar
# ---------------------------------------------------------------------- #
def _role_route(role: str, tier: str):
    """Resolve (provider, model) for an agent role exactly as BaseAgent does."""
    prov = (os.environ.get(f"{role.upper()}_PROVIDER") or LLM_PROVIDER).lower()
    model = os.environ.get(f"{role.upper()}_MODEL")
    if not model:
        strong_roles = {r.strip().lower() for r in os.environ.get("STRONG_ROLES", "").split(",") if r.strip()}
        t = "strong" if role.lower() in strong_roles else ("cheap" if FORCE_CHEAP else tier)
        if prov == "openai":
            model = (os.environ.get("OPENAI_STRONG_MODEL", "gpt-4o") if t == "strong"
                     else os.environ.get("OPENAI_CHEAP_MODEL", "gpt-4o-mini"))
        else:
            model = (os.environ.get("ANTHROPIC_STRONG_MODEL", "claude-sonnet-4-6") if t == "strong"
                     else os.environ.get("ANTHROPIC_CHEAP_MODEL", "claude-haiku-4-5-20251001"))
    return prov, model


_AGENT_ROLES = [
    ("Document", "document", "cheap"), ("Protocol", "protocol", "strong"),
    ("Review", "review", "strong"), ("Planner", "planner", "cheap"),
    ("Search", "search", "cheap"), ("Chat", "chat", "cheap"),
    ("Methods", "methods", "cheap"), ("Literature", "literature", "cheap"),
    ("Summary", "summary", "cheap"), ("Educator", "educator", "cheap"),
    ("Audit", "audit", "strong"), ("Experiment design", "expdesign", "strong"),
    ("Value suggest", "suggest", "cheap"),
]


def _short_model(name: str) -> str:
    n = name.replace("claude-", "").replace("-latest", "")
    return n[:22] + "…" if len(n) > 23 else n


def _pretty_run(name: str) -> str:
    # run_20260612_214606 -> Jun 12, 21:46
    m = re.match(r"run_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", name)
    if not m:
        return name
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    _, mo, d, hh, mm = m.groups()[:5]
    return f"{months[int(mo)]} {int(d)}, {hh}:{mm}"


def _latest_protocol_file(run_path: str):
    files = [f for f in os.listdir(run_path) if re.match(r"protocol_v\d+\.json$", f)] \
        if os.path.isdir(run_path) else []
    if not files:
        return None
    files.sort(key=lambda f: int(re.search(r"v(\d+)", f).group(1)))
    return files[-1]


def run_summary(name: str):
    path = os.path.join(RUNS_DIR, name)
    pf = _latest_protocol_file(path)
    if not pf:
        return None
    try:
        with open(os.path.join(path, pf), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    done = None
    pp = os.path.join(path, "progress.json")
    if os.path.exists(pp):
        try:
            with open(pp, "r", encoding="utf-8") as fh:
                done = len(json.load(fh).get("completed_steps", []) or [])
        except Exception:
            done = None
    return {
        "title": data.get("protocol_title", "Protocol"),
        "steps": len(data.get("workflow", []) or []),
        "version": data.get("protocol_version", "v1"),
        "confidence": data.get("confidence", ""),
        "done": done,
    }


def load_run(name: str):
    path = os.path.join(RUNS_DIR, name)
    pf = _latest_protocol_file(path)
    if not pf:
        st.warning("That run has no saved protocol yet.")
        return

    def _read(fn):
        fp = os.path.join(path, fn)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return None
        return None

    proto = _read(pf)
    if not proto:
        st.error("Could not read that run's protocol.")
        return
    reset_run()
    st.session_state.run_dir = path
    st.session_state.protocol = proto
    st.session_state.protocol_v1 = _read("protocol_v1.json") or proto
    st.session_state.input_meta = _read("input.json") or {}
    parsed = _read("parsed_document.json")
    if isinstance(parsed, dict) and "documents" in parsed:
        st.session_state.parsed_docs = parsed["documents"]
        st.session_state.parsed = parsed["documents"][0] if parsed["documents"] else None
    elif parsed:
        st.session_state.parsed = parsed
        st.session_state.parsed_docs = [parsed]
    # optional extras
    rev = _read("review_v1.json")
    if rev:
        st.session_state.review = rev
    ver = proto.get("protocol_version", "v1")
    plan = _read(f"plan_{ver}.json") or _read("plan_v1.json")
    if plan:
        st.session_state.plan = plan
    # restore bench progress so the user resumes where they left off
    prog = _read("progress.json")
    resumed_to_bench = False
    if prog:
        st.session_state.completed_steps = set(prog.get("completed_steps", []) or [])
        st.session_state.flagged = prog.get("flagged", {}) or {}
        st.session_state.bench_idx = int(prog.get("bench_idx", 0) or 0)
        st.session_state._resumed = prog.get("updated_at")
        if st.session_state.completed_steps:
            resumed_to_bench = True
    log_event("run_loaded", {"run": name, "version": ver, "resumed": resumed_to_bench})
    st.session_state.page = "bench" if resumed_to_bench else "protocol"
    st.rerun()


# --------------------------------------------------------------------------- #
# Experience level → audience + how it drives detail and guidance everywhere.
# beginner = undergraduate · intermediate = master's/PhD student · expert = scientist/PI
# --------------------------------------------------------------------------- #
LEVEL_PROFILES = {
    "beginner": {
        "audience": "Undergraduate",
        "detail": ("Maximum hand-holding. Write long, fully spelled-out sub-steps. Define "
                   "every technique, reagent and acronym inline. Add a short 'why this matters' "
                   "and a safety/pitfall note on each step. Assume no prior bench experience."),
        "guide": ("Teach as you go: define terms, explain the reasoning behind each action, "
                  "and call out common beginner mistakes. Err on the side of more explanation."),
    },
    "intermediate": {
        "audience": "Master's / PhD student",
        "detail": ("Standard working detail. Clear ordered steps with the key rationale and "
                   "critical checkpoints. Assume basic bench competence — skip definitions of "
                   "routine techniques, but flag non-obvious choices."),
        "guide": ("Assume working bench experience. Focus on rationale, decision points and "
                  "what to verify; skip basic definitions unless asked."),
    },
    "expert": {
        "audience": "Scientist / PI",
        "detail": ("Terse and technical. Condensed steps, exact parameters only, no basic "
                   "explanations. Assume deep expertise — surface only non-standard, risky or "
                   "decision-critical points worth a senior scientist's attention."),
        "guide": ("Assume an experienced scientist. Be concise and technical; emphasize "
                  "trade-offs, edge cases and where the protocol deviates from convention."),
    },
}


def _level_profile(level: str) -> dict:
    l = (level or "intermediate").lower()
    if any(k in l for k in ("begin", "novice", "undergrad")):
        return LEVEL_PROFILES["beginner"]
    if any(k in l for k in ("expert", "advanced", "senior", "scientist", "pi", "phd-level")):
        return LEVEL_PROFILES["expert"]
    return LEVEL_PROFILES["intermediate"]


def _level_label(level: str) -> str:
    """Dropdown label: 'Beginner · Undergraduate' etc."""
    return f"{str(level).capitalize()} · {_level_profile(level)['audience']}"


def sidebar():
    with st.sidebar:
        brand_box = st.container()
        with brand_box:
            if st.button("Home", key="brand_home", help="Back to the home screen"):
                st.session_state.page = "home"
                st.session_state.input_reveal = False
                st.rerun()
        brand_box.markdown(
            '<div class="lab-brand">'
            '<svg width="44" height="44" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex:0 0 auto;">'
            '<rect x="8" y="8" width="104" height="104" rx="28" fill="url(#gb)"/>'
            '<defs><linearGradient id="gb" x1="0" y1="0" x2="120" y2="120">'
            '<stop stop-color="#6E61F0"/><stop offset="1" stop-color="#9A86F6"/></linearGradient></defs>'
            '<path d="M50 34h20v15l16 30a9 9 0 0 1-8 13H42a9 9 0 0 1-8-13l16-30V34z" fill="#fff"/>'
            '<path d="M44 64h32l9 17a5 5 0 0 1-4.5 7H39.5A5 5 0 0 1 35 81l9-17z" fill="#C8C0FF"/>'
            '<circle cx="52" cy="78" r="3.4" fill="#6E61F0"/><circle cx="66" cy="84" r="2.6" fill="#6E61F0"/>'
            '<circle cx="60" cy="74" r="2.2" fill="#6E61F0"/>'
            '<rect x="48" y="30" width="24" height="6" rx="3" fill="#fff"/>'
            '<circle cx="53" cy="49" r="2.6" fill="#2B2A4A"/><circle cx="67" cy="49" r="2.6" fill="#2B2A4A"/>'
            '<path d="M53 55q7 5 14 0" stroke="#2B2A4A" stroke-width="2.4" stroke-linecap="round" fill="none"/>'
            '<path d="M92 30l2.2 5.2L99 37l-4.8 1.8L92 44l-2.2-5.2L85 37l4.8-1.8z" fill="#FFD25A"/></svg>'
            '<div><div class="lab-brand-name">Lab Agent</div>'
            '<div class="lab-brand-sub">Bench-side execution assistant</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        live = st.session_state.get("live_mode", not DEMO_MODE)
        sc1, sc2 = st.columns([1, 1])
        with sc1:
            st.markdown(
                f'<div class="lab-status {"live" if live else "on"}"><span class="dot"></span>'
                f'{"LIVE" if live else "OFFLINE"}</div>', unsafe_allow_html=True)
        with sc2:
            new_live = st.toggle("Live", value=live, key="side_live",
                                 help="On = real API calls. Off = offline mock outputs (no key needed).")
        if new_live != live:
            st.session_state.live_mode = new_live
            st.rerun()

        with st.expander("Models · per-agent"):
            st.caption("Pick the model each agent uses. Default follows your settings.")
            _MODELS = {
                "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"],
                "openai": ["gpt-4o-mini", "gpt-4o"],
            }
            routing = st.session_state.setdefault("routing", {})
            for label, role, tier in _AGENT_ROLES:
                cur = routing.get(role, {})
                dprov, dmodel = _role_route(role, tier)
                pv = st.selectbox(
                    f"{label}", ["Default", "Anthropic / Claude", "OpenAI / ChatGPT"],
                    index=(0 if not cur else (1 if cur.get("provider") == "anthropic" else 2)),
                    key=f"route_prov_{role}")
                if pv == "Default":
                    routing.pop(role, None)
                    st.caption(f"↳ default · {_short_model(dmodel)}")
                else:
                    prov = "anthropic" if pv.startswith("Anthropic") else "openai"
                    mopts = _MODELS[prov]
                    midx = mopts.index(cur["model"]) if cur.get("model") in mopts else 0
                    model = st.selectbox("model", mopts, index=midx, key=f"route_model_{role}",
                                         label_visibility="collapsed")
                    routing[role] = {"provider": prov, "model": model}
            st.session_state.routing = routing

        st.write("")
        # User level — drives protocol detail + Learn depth (Projects live in the top nav)
        st.markdown('<div class="lab-section">Your level</div>', unsafe_allow_html=True)
        _levels = ["beginner", "intermediate", "expert"]
        cur_lvl = st.session_state.get("user_level", "intermediate")
        new_lvl = st.selectbox(
            "Experience level", _levels,
            index=_levels.index(cur_lvl) if cur_lvl in _levels else 1,
            key="side_user_level", format_func=_level_label,
            help="Drives protocol step detail AND the side-by-side guidance depth.\n\n"
                 "• Beginner = Undergraduate — long, fully-explained steps + most teaching\n"
                 "• Intermediate = Master's / PhD student — standard detail + rationale\n"
                 "• Expert = Scientist / PI — terse, technical, minimal explanation")
        if new_lvl != cur_lvl:
            st.session_state.user_level = new_lvl
            if isinstance(st.session_state.get("input_meta"), dict):
                st.session_state.input_meta["experience_level"] = new_lvl
            st.rerun()
        cp = st.session_state.get("current_project")
        if cp:
            nm = next((p["name"] for p in proj.list_projects() if p["slug"] == cp), cp)
            st.caption(f"{nm}")


# ---------------------------------------------------------------------- #
# Page A: Input
def _render_landing():
    """Friendly welcome screen — mascot + how-it-works. The action lives in the top
    WORKSPACE bar (＋ Start, beside Projects / Learn)."""
    st.markdown(
        """
        <style>
          .lnd{max-width:920px;margin:6px auto 0;}
          .lnd-hero{position:relative;overflow:hidden;border:1px solid var(--border);border-radius:22px;
            background:linear-gradient(180deg,#FAF9FF 0%, #FFFFFF 60%);box-shadow:0 6px 24px rgba(91,79,224,.08);
            padding:26px 30px;}
          .lnd-hero::after{content:"";position:absolute;right:-90px;top:-90px;width:260px;height:260px;border-radius:50%;
            background:radial-gradient(circle, rgba(122,111,240,.18), rgba(122,111,240,0) 70%);}
          .lnd-head{display:flex;align-items:center;gap:18px;position:relative;z-index:1;}
          .lnd-h1{font-weight:850;font-size:1.55rem;letter-spacing:-.02em;margin:0;line-height:1.1;
            background:linear-gradient(92deg,#5B4FE0,#9A86F6);-webkit-background-clip:text;background-clip:text;
            -webkit-text-fill-color:transparent;}
          .lnd-tag{color:var(--muted);font-size:14px;margin:6px 0 0;max-width:640px;line-height:1.55;}
          .lnd-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:13px;}
          .lnd-chip{font-size:11.5px;font-weight:650;color:var(--accent);background:var(--accent-soft);
            border:1px solid #E2DEFB;border-radius:999px;padding:4px 11px;}
          .lnd-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px;}
          .lnd-step{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:15px 14px;
            transition:transform .12s ease,box-shadow .12s ease;}
          .lnd-step:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(16,24,40,.07);}
          .lnd-ic{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;justify-content:center;
            font-size:19px;}
          .lnd-n{font-size:10.5px;font-weight:800;letter-spacing:.06em;color:var(--accent);margin-top:10px;}
          .lnd-t{font-weight:750;font-size:13.5px;margin-top:1px;color:var(--ink);}
          .lnd-d{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.45;}
          .lnd-cap{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--muted);margin:18px 2px 8px;}
          @media (max-width:760px){.lnd-steps{grid-template-columns:repeat(2,1fr);}}
        </style>
        <div class="lnd"><div class="lnd-hero"><div class="lnd-head">
          <svg width="74" height="74" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="8" y="8" width="104" height="104" rx="28" fill="url(#g)"/>
            <defs><linearGradient id="g" x1="0" y1="0" x2="120" y2="120">
              <stop stop-color="#6E61F0"/><stop offset="1" stop-color="#9A86F6"/></linearGradient></defs>
            <path d="M50 34h20v15l16 30a9 9 0 0 1-8 13H42a9 9 0 0 1-8-13l16-30V34z" fill="#fff"/>
            <path d="M44 64h32l9 17a5 5 0 0 1-4.5 7H39.5A5 5 0 0 1 35 81l9-17z" fill="#C8C0FF"/>
            <circle cx="52" cy="78" r="3.4" fill="#6E61F0"/><circle cx="66" cy="84" r="2.6" fill="#6E61F0"/>
            <circle cx="60" cy="74" r="2.2" fill="#6E61F0"/>
            <rect x="48" y="30" width="24" height="6" rx="3" fill="#fff"/>
            <circle cx="53" cy="49" r="2.6" fill="#2B2A4A"/><circle cx="67" cy="49" r="2.6" fill="#2B2A4A"/>
            <path d="M53 55q7 5 14 0" stroke="#2B2A4A" stroke-width="2.4" stroke-linecap="round" fill="none"/>
            <path d="M92 30l2.2 5.2L99 37l-4.8 1.8L92 44l-2.2-5.2L85 37l4.8-1.8z" fill="#FFD25A"/>
          </svg>
          <div>
            <div class="lnd-h1">Lab Experimental Agent</div>
            <div class="lnd-tag">Turn any protocol — a kit manual, a paper's Methods, or your own messy
            notes — into adaptive, step-by-step bench instructions with checks, timers and gap-filling.</div>
            <div class="lnd-chips"><span class="lnd-chip">No invented values</span>
              <span class="lnd-chip">Redundancy &amp; contradiction checks</span>
              <span class="lnd-chip">Bench timers</span><span class="lnd-chip">Methods &amp; Learn</span></div>
          </div>
        </div></div>
        <div class="lnd-cap">HOW IT WORKS</div>
        <div class="lnd"><div class="lnd-steps">
          <div class="lnd-step"><div class="lnd-ic" style="background:#EAF0FB;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563EB" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4"/><path d="M7 9l5-5 5 5"/><path d="M5 20h14"/></svg></div>
            <div class="lnd-n">STEP 1</div><div class="lnd-t">Upload</div>
            <div class="lnd-d">Drop in protocols, kit manuals, or paste text.</div></div>
          <div class="lnd-step"><div class="lnd-ic" style="background:#EFEDFD;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6D5BD0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-3.2-3.2"/><path d="M8.5 11l2 2 3.5-3.5"/></svg></div>
            <div class="lnd-n">STEP 2</div><div class="lnd-t">AI parses &amp; checks</div>
            <div class="lnd-d">Extracts steps; flags redundancy &amp; contradictions.</div></div>
          <div class="lnd-step"><div class="lnd-ic" style="background:#FDF4E7;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#D97706" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M13.5 7l3 3"/></svg></div>
            <div class="lnd-n">STEP 3</div><div class="lnd-t">Review &amp; fill</div>
            <div class="lnd-d">Confirm values, fill gaps, raise confidence.</div></div>
          <div class="lnd-step"><div class="lnd-ic" style="background:#E9F7EF;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16A34A" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="7 4 19 12 7 20" fill="#16A34A" stroke="none"/></svg></div>
            <div class="lnd-n">STEP 4</div><div class="lnd-t">Run &amp; learn</div>
            <div class="lnd-d">Bench mode, plan by day, and a Learn brief.</div></div>
        </div></div></div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------- #
def page_input():
    if not st.session_state.get("input_reveal"):
        _render_landing()
        return
    hero("New experiment", "Upload a protocol, pick a kit, search the web, or combine several — then parse and run it step by step.")

    kits = list_kits()

    # --- Commercial kit shortcut: load one verified protocol with exact values ---
    with st.expander("Use known commercial kit(s) (skip parsing, exact values)", expanded=False):
        if kits:
            options = {f"{k['title']} — {k['vendor']}": k["id"] for k in kits}
            choice = st.selectbox("Commercial kit", list(options.keys()), key="kit_pick_input")
            sel = next(k for k in kits if k["id"] == options[choice])
            st.caption(sel.get("provenance", ""))
            if st.button("Load this kit protocol →", key="load_kit_input"):
                load_kit_as_protocol(options[choice])

            st.divider()
            st.markdown("**Select multiple protocols to combine into one run**")
            st.caption("Stages run in order — e.g. Miniprep → Gel Recovery → Clean & Concentrate.")
            multi = st.multiselect(
                "Protocols (order = run order)",
                list(options.keys()), key="kit_multi_input",
            )
            if st.button("Combine selected into one protocol →", key="combine_input",
                         disabled=len(multi) < 2):
                load_combined_protocol([options[m] for m in multi])
            if 0 < len(multi) < 2:
                st.caption("Pick at least 2 to combine.")
        else:
            st.caption("No kits found in memory/kit_library.json or memory/kits/.")

    # --- Smart web search for protocols beyond the library ---
    with st.expander("Search the web for a protocol (smart retrieval)", expanded=False):
        if DEMO_MODE:
            st.info("Live web search runs when DEMO_MODE=false with an ANTHROPIC_API_KEY. "
                    "In demo mode this searches the local kit library instead.")
        q = st.text_input("Describe the protocol to find",
                          key="websearch_q",
                          placeholder="e.g. Zymo Direct-zol RNA Miniprep, or NEBNext Ultra II library prep")
        if st.button("Search", key="websearch_btn", disabled=not q.strip()):
            run_protocol_search(q.strip())
        _render_search_results()

    meta = st.session_state.input_meta or {}
    uploaded = st.file_uploader(
        "Protocol file(s) — upload one, or several to combine into one sequential run",
        type=[e.strip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
    )
    bg_files = st.file_uploader(
        "Background (optional) — past protocols, papers, or lab notes that give the "
        "agent context for your goal",
        type=[e.strip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True, key="bg_uploader",
    )

    # When an experiment is loaded, show its documents so you can SEE them, ADD more files
    # above, and edit the goal below — re-parsing keeps these unless you untick.
    existing_docs = st.session_state.get("source_docs") or []
    include_existing = False
    if existing_docs:
        st.markdown(f"**{len(existing_docs)} document(s) already in this experiment**")
        for d in existing_docs:
            st.caption(f"• {d.get('title') or d.get('name', 'document')}")
        include_existing = st.checkbox(
            f"Keep these {len(existing_docs)} document(s) when I re-parse (add new uploads above)",
            value=True, key="keep_existing_docs")
        st.caption("Edit the goal below and/or add files above, then **Parse** to update this "
                   "experiment. Re-parsing rebuilds the protocol from the combined documents.")

    with st.form("meta_form"):
        goal = st.text_area(
            "Research question / goal",
            meta.get("goal", ""),
            placeholder="e.g. Which chromatin regulators control H3K27ac at active enhancers "
                        "in MCF7 vs MCF10A, and how does CRISPRi knockdown reshape it?",
            help="A one-line goal helps the agent frame the right experiment and the route choices.",
        )
        c1, c2 = st.columns(2)
        with c1:
            experiment_name = st.text_input("Experiment name", meta.get("experiment_name", ""))
            assay_type = st.text_input("Assay type", meta.get("assay_type", ""))
            sample_type = st.text_input("Sample type", meta.get("sample_type", ""))
        with c2:
            num_samples = st.number_input(
                "Number of samples", min_value=1, value=int(meta.get("num_samples", 1)), step=1
            )
            _levels = ["beginner", "intermediate", "expert"]
            _lvl_default = meta.get("experience_level") or st.session_state.get("user_level", "intermediate")
            experience = st.selectbox(
                "Experience level", _levels,
                index=_levels.index(_lvl_default) if _lvl_default in _levels else 1,
                format_func=_level_label,
                help="Undergraduate / Master's-PhD / Scientist-PI. Drives step detail and "
                     "guidance depth. Defaults to your sidebar level; change per-run here.",
            )
        constraints = st.text_area(
            "Lab constraints (missing equipment, limited sample, replacement reagents, etc.)",
            meta.get("lab_constraints", ""),
        )
        paste = st.text_area(
            "…or paste protocol text directly (optional, used if no file uploaded)",
            st.session_state.raw_text if not uploaded else "",
        )
        submitted = st.form_submit_button("Parse protocol →", use_container_width=True)

    if submitted:
        files = uploaded or []  # file_uploader returns a list now
        if not files and not paste.strip() and not (include_existing and existing_docs):
            st.error("Upload file(s) or paste protocol text first.")
            return
        # Extract text from each uploaded file (or the pasted text)
        sources = []  # list of (name, text)
        try:
            if files:
                for f in files:
                    sources.append((f.name, extract_text(
                        path="", raw_bytes=f.getvalue(), file_name=f.name)))
            elif paste.strip():
                sources.append(("pasted_text.txt", paste))
        except Exception as exc:
            st.error(f"Could not read file: {exc}")
            return

        # background/context documents — parsed alongside, classified (background/
        # literature) so they inform framing/routes/Methods but aren't protocol steps
        try:
            for f in (bg_files or []):
                sources.append((f.name, extract_text(
                    path="", raw_bytes=f.getvalue(), file_name=f.name)))
        except Exception:
            pass

        # carry over the documents already in this experiment (so adding a file or changing
        # the goal doesn't drop them), skipping any re-uploaded under the same name
        if include_existing and existing_docs:
            names_now = {n for n, _ in sources}
            carried = [(d.get("name") or d.get("title", "document"), d.get("text", ""))
                       for d in existing_docs
                       if d.get("text") and (d.get("name") or d.get("title", "document")) not in names_now]
            sources = carried + sources

        # drop empty / unreadable (e.g. scanned-PDF) sources
        sources = [(n, t) for n, t in sources
                   if t and t.strip() and not t.strip().startswith("[No extractable text")]
        if not sources:
            st.error("No readable protocol text found. Upload a text-based PDF/DOCX/TXT/MD "
                     "or paste the protocol text. (Scanned/image-only PDFs can't be read.)")
            return

        source_label = ", ".join(n for n, _ in sources)
        meta = {
            "experiment_name": experiment_name,
            "assay_type": assay_type,
            "sample_type": sample_type,
            "num_samples": int(num_samples),
            "experience_level": experience,
            "lab_constraints": constraints,
            "goal": goal.strip(),
            "source_file": source_label,
        }

        run_dir = new_run_dir()
        st.session_state.run_dir = run_dir
        st.session_state.input_meta = meta
        st.session_state.raw_text = sources[0][1]
        save_json(run_dir, "input.json", {**meta, "num_files": len(sources)})
        log_event("input_submitted", {**meta, "num_files": len(sources)})

        # DocumentAgent (cheap) — parse each document
        parsed_docs = []
        with st.spinner(f"Document Agent: extracting facts from {len(sources)} document(s)…"):
            for name, text in sources:
                parsed_docs.append(DocumentAgent().parse(text, file_name=name))
        errs = [p for p in parsed_docs if p.get("status") == "error"]
        if errs:
            st.error(f"Parsing failed: {errs[0].get('error')}")
            return
        st.session_state.parsed_docs = parsed_docs
        st.session_state.parsed = parsed_docs[0]
        # keep the raw uploaded text (with its classified type) so the Methods
        # writer can re-read ALL source documents — including background/literature
        # that carry context (e.g. parental cell-line genotype) the structured
        # protocol may not capture.
        st.session_state.source_docs = [
            {"name": name, "doc_type": pd.get("doc_type", "protocol"),
             "title": pd.get("protocol_title", name), "text": (text or "")[:8000]}
            for (name, text), pd in zip(sources, parsed_docs)
        ]
        # scan the FULL extracted text (not the 8000-char stored copy) for embedded sequences,
        # so WT/Mut inserts or primers deep in a Twist order / FASTA aren't missed by truncation.
        try:
            st.session_state["_captured_sequences"] = sequence_scan.scan_docs(
                [{"title": pd.get("protocol_title", name), "name": name, "text": text}
                 for (name, text), pd in zip(sources, parsed_docs)])
        except Exception:
            st.session_state["_captured_sequences"] = []
        save_json(run_dir, "parsed_document.json",
                  parsed_docs[0] if len(parsed_docs) == 1 else {"documents": parsed_docs})
        log_event("document_parsed", {"count": len(parsed_docs), "goal": bool(goal.strip()),
                                      "background_files": len(bg_files or [])})
        st.session_state.page = "parse_routes"
        st.rerun()


# ---------------------------------------------------------------------- #
# Page B: Parsed document
# ---------------------------------------------------------------------- #
def page_parsed():
    parsed = st.session_state.parsed
    hero("Parsed document", "Review the extracted facts. Uncertain values are flagged — confirm them before bench use.")
    if not parsed:
        st.info("Nothing parsed yet.")
        return

    docs = st.session_state.parsed_docs or [parsed]
    if len(docs) > 1:
        _badge = {"protocol": "protocol", "background": "background",
                  "literature": "literature", "reference": "reference"}
        n_proto = sum(1 for d in docs if d.get("doc_type", "protocol") == "protocol")
        st.info(f"{len(docs)} documents parsed and **classified**. Only documents marked "
                "**Use as protocol** become workflow steps; the rest are kept as project "
                "background / reference (to study, not run).")
        includes = {}
        for i, d in enumerate(docs):
            dtype = d.get("doc_type", "protocol")
            cc1, cc2 = st.columns([5, 1])
            with cc1:
                with st.expander(f"{_badge.get(dtype, dtype)} — {d.get('protocol_title','—')}"):
                    st.write(d.get("summary", ""))
                    if d.get("major_steps"):
                        st.markdown("**Major steps:** "
                                    + " → ".join(_li_text(s) for s in d.get("major_steps", [])[:12]))
            includes[i] = cc2.checkbox("Use as protocol", value=(dtype == "protocol"),
                                       key=f"docinc_{i}")
        st.session_state.doc_include = includes
        sel = sum(1 for v in includes.values() if v)
        st.caption(f"{sel} document(s) will become protocol steps; {len(docs) - sel} kept as reference.")

        # --- consistency audit: flag redundancy / contradictions / false logic ---
        with st.expander("Check uploads for redundancy / contradictions / logic issues", expanded=False):
            st.caption("Flags duplicate or repeated content, internal contradictions, illogical order, "
                       "and claims that conflict with your ground-truth notes. It only flags — nothing is changed.")
            if st.button("Run consistency audit", key="run_audit", use_container_width=True):
                gt = next((d.get("text", "") for d in _learn_source_docs()
                           if "ground-truth" in d.get("title", "").lower()
                           or "study notes" in d.get("title", "").lower()), "")
                with st.spinner("Consistency Auditor: checking the uploaded documents…"):
                    st.session_state["audit_result"] = AuditAgent().audit(
                        docs=docs, protocol=None, ground_truth=gt)
                st.rerun()
            _render_audit(st.session_state.get("audit_result"))

        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button(f"Find core experiment & design it",
                         use_container_width=True, type="primary", disabled=sel == 0,
                         help="Analyze the messy uploads: identify the ONE core experiment, merge "
                              "overlapping docs into a non-redundant workflow, AND design the missing "
                              "framing (arms, controls, readouts) — view it in the Design tab."):
                design_experiment()
        with c2:
            if st.button(f"Combine as stages ({sel})", use_container_width=True,
                         disabled=sel == 0,
                         help="Concatenate each selected doc as its own stage (no de-dup)"):
                generate_protocol()
        with c3:
            if st.button("↩ Revise input", use_container_width=True):
                st.session_state.page = "input"
                st.rerun()
        return

    st.subheader(parsed.get("protocol_title", "—"))
    st.caption(f"Assay: {parsed.get('assay_type','—')}  •  source: {parsed.get('source_file','—')}")
    st.write(parsed.get("summary", ""))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Materials (as found)**")
        for m in parsed.get("materials", []):
            if isinstance(m, dict):
                st.write(f"- {m.get('item','')} — amt: {m.get('amount','')} · cat: {m.get('catalog_number','')}")
            else:
                st.write(f"- {_li_text(m)}")
        st.markdown("**Equipment**")
        for e in parsed.get("equipment", []):
            st.write(f"- {_li_text(e)}")
    with c2:
        st.markdown("**Major steps**")
        for s in parsed.get("major_steps", []):
            st.write(f"- {_li_text(s)}")
        st.markdown("**Sample requirements**")
        for s in parsed.get("sample_requirements", []):
            st.write(f"- {_li_text(s)}")

    if parsed.get("safety_notes"):
        st.warning("Safety: " + " ".join(_li_text(x) for x in parsed["safety_notes"]))
    if parsed.get("uncertain_fields"):
        st.error(
            "Uncertain / unconfirmed fields (will be marked "
            "`[confirm with source protocol]`): "
            + ", ".join(_li_text(x) for x in parsed["uncertain_fields"])
        )

    st.divider()
    st.markdown("**Approval gate**")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Approve → generate protocol", use_container_width=True):
            generate_protocol()
    with c2:
        if st.button("↩ Revise input", use_container_width=True):
            st.session_state.page = "input"
            st.rerun()
    with c3:
        with st.expander("View raw parsed JSON"):
            st.json(parsed)


def load_kit_as_protocol(kit_id: str):
    """Load a verified commercial-kit protocol wholesale (exact values)."""
    kit = get_kit(kit_id)
    if not kit:
        st.error("Kit not found.")
        return
    if not st.session_state.run_dir:
        st.session_state.run_dir = new_run_dir()
    meta = st.session_state.input_meta or {}
    # carry the chosen experience level into the loaded kit, if set
    if meta.get("experience_level"):
        kit["intended_user"] = meta["experience_level"]
    kit.setdefault("protocol_version", "v1")
    st.session_state.input_meta = {
        **meta,
        "experiment_name": meta.get("experiment_name") or kit.get("protocol_title", ""),
        "assay_type": kit.get("assay_type", meta.get("assay_type", "")),
        "source_file": f"kit_library:{kit_id}",
    }
    save_json(st.session_state.run_dir, "input.json", st.session_state.input_meta)
    st.session_state.parsed = {
        "agent": "Kit Library", "status": "success",
        "protocol_title": kit.get("protocol_title", ""),
        "assay_type": kit.get("assay_type", ""),
        "source_file": f"kit_library:{kit_id}",
        "summary": kit.get("summary", ""),
        "materials": kit.get("materials", []),
        "equipment": kit.get("preconditions", {}).get("equipment_requirements", []),
        "sample_requirements": kit.get("preconditions", {}).get("sample_requirements", []),
        "major_steps": [s.get("title", "") for s in kit.get("workflow", [])],
        "safety_notes": kit.get("preconditions", {}).get("safety_notes", []),
        "uncertain_fields": [],
    }
    save_json(st.session_state.run_dir, "parsed_document.json", st.session_state.parsed)
    st.session_state.protocol = kit
    st.session_state.protocol_v1 = kit
    persist_protocol(kit)
    log_event("kit_loaded", {"kit_id": kit_id, "title": kit.get("protocol_title")})
    with st.spinner("Review Agent: checking the loaded kit protocol…"):
        st.session_state.review = ReviewAgent().review(kit, st.session_state.parsed)
    st.session_state.completed_steps = set()
    st.session_state.bench_idx = 0
    st.session_state.page = "protocol"
    st.rerun()


def _install_protocol(proto: dict, parsed_stub: dict, source_file: str):
    """Shared path: persist a ready protocol, review it, go to Protocol page."""
    if not st.session_state.run_dir:
        st.session_state.run_dir = new_run_dir()
    # field hygiene FIRST: strip parse artifacts (a temperature in the time field, a storage
    # temp leaked onto a reaction step, the same amount copied across many reagents) so the
    # protocol is never pre-seeded with nonsense — those become honest 'to confirm' slots.
    try:
        hy = field_hygiene.clean(proto)
        if hy:
            log_event("field_hygiene", {"n": len(hy), "kinds": sorted({k for k, _ in hy})})
    except Exception:
        pass

    # reagent-to-step validation: relocate a reagent listed on the wrong step (packaging
    # plasmids on a sequencing step, an enzyme on a plating step) to the step it fits, or flag it.
    try:
        moves = reagent_placement.apply(proto)
        if moves:
            log_event("reagent_placement", {"n": len(moves)})
            relocated = [m for m in moves if m["action"] == "moved"]
            if relocated:
                st.session_state["_reagent_flash"] = (
                    f"Moved {len(relocated)} misplaced reagent(s) to the right step: "
                    + "; ".join(f"{m['item']} → {m['to_title']}" for m in relocated[:6]) + ".")
    except Exception:
        pass

    # capture DNA/oligo sequences embedded in the uploaded docs (Twist orders, primer lists,
    # FASTA) and attach them to the matching material — so the actual WT/Mut insert & primer
    # sequences aren't dropped when the protocol is structured.
    try:
        # prefer the full-text scan captured at upload (avoids 8000-char truncation); fall back
        # to scanning the stored source docs.
        seqs = (st.session_state.get("_captured_sequences")
                or sequence_scan.scan_docs(st.session_state.get("source_docs") or []))
        if seqs:
            n_attached = sequence_scan.attach_to_materials(proto, seqs)
            log_event("sequences_captured", {"found": len(seqs), "attached": n_attached})
            st.session_state["_seq_flash"] = (
                f"Captured {len(seqs)} sequence(s) from your upload "
                f"({n_attached} attached to materials). See the Materials tab / Sequences panel.")
    except Exception:
        pass

    # parse → design auto-repair: insert the missing connecting steps the logic check finds
    # (vector digestion before ligation, virus production before transduction, sequence
    # verification, designed validation) so the protocol that lands in Design is connected.
    try:
        fixes = flow_check.apply_fixes(proto)
        if fixes:
            normalize_protocol(proto)
            log_event("flow_autofix", {"n": len(fixes),
                                       "kinds": [f["kind"] for f in fixes]})
            st.session_state["_flow_fix_flash"] = (
                f"Logic check added {len(fixes)} connecting step(s): "
                + "; ".join(f["title"] for f in fixes) + ". Review the flagged steps.")
    except Exception:  # never block install on the auto-repair
        pass
    st.session_state.input_meta = {
        **(st.session_state.input_meta or {}),
        "source_file": source_file,
        "assay_type": proto.get("assay_type", ""),
    }
    save_json(st.session_state.run_dir, "input.json", st.session_state.input_meta)
    st.session_state.parsed = parsed_stub
    save_json(st.session_state.run_dir, "parsed_document.json", parsed_stub)
    st.session_state.protocol = proto
    st.session_state.protocol_v1 = proto
    persist_protocol(proto)
    with st.spinner("Review Agent: checking the protocol…"):
        st.session_state.review = ReviewAgent().review(proto, parsed_stub)
    st.session_state.completed_steps = set()
    st.session_state.bench_idx = 0
    st.session_state.page = "protocol"
    st.rerun()


def load_combined_protocol(kit_ids):
    """Combine several library kits into one sequential protocol."""
    protos = [get_kit(k) for k in kit_ids]
    protos = [p for p in protos if p]
    if len(protos) < 2:
        st.error("Need at least two valid kits to combine.")
        return
    combined = combine_protocols(protos)
    combined["timestamp"] = utc_timestamp()
    titles = [p.get("protocol_title", "") for p in protos]
    parsed_stub = {
        "agent": "Kit Library", "status": "success",
        "protocol_title": combined["protocol_title"],
        "assay_type": "Multi-stage workflow",
        "source_file": "combined:" + ",".join(kit_ids),
        "summary": "Combined from: " + "; ".join(titles),
        "materials": combined.get("materials", []),
        "equipment": combined.get("preconditions", {}).get("equipment_requirements", []),
        "sample_requirements": combined.get("preconditions", {}).get("sample_requirements", []),
        "major_steps": [f"{s.get('stage','')}: {s.get('title','')}" for s in combined.get("workflow", [])],
        "safety_notes": combined.get("preconditions", {}).get("safety_notes", []),
        "uncertain_fields": [],
    }
    log_event("protocols_combined", {"kits": kit_ids, "steps": len(combined.get("workflow", []))})
    _install_protocol(combined, parsed_stub, "combined:" + ",".join(kit_ids))


def run_protocol_search(query: str):
    with st.spinner("Search Agent: looking for matching protocols…"):
        st.session_state.search_results = SearchAgent().search(query)
    log_event("protocol_search", {"query": query,
                                  "status": st.session_state.search_results.get("status")})


def _render_search_results():
    res = st.session_state.search_results
    if not res:
        return
    if res.get("status") == "error":
        st.error(f"Search failed: {res.get('error')}")
        return

    # Demo / local-library results
    if res.get("mode") == "demo_local_library":
        st.caption(res.get("message", ""))
        results = res.get("results", [])
        if not results:
            st.write("No local matches. Try different keywords.")
        for r in results:
            c1, c2 = st.columns([3, 1])
            c1.write(f"**{r['title']}** — {r.get('vendor','')}  ·  _{r.get('assay_type','')}_")
            if c2.button("Load", key=f"loadsearch_{r['kit_id']}"):
                load_kit_as_protocol(r["kit_id"])
        return

    # Live web-search results
    if not res.get("found", True):
        st.warning("No reliable source found. " + (res.get("parsed_document", {}) or {}).get("summary", ""))
        return
    st.success(f"Found: **{res.get('best_match_title','')}** ({res.get('vendor_or_author','')})")
    srcs = res.get("sources", []) or []
    if srcs:
        st.markdown("**Sources:**")
        for s in srcs:
            st.write(f"- [{s.get('title','source')}]({s.get('url','')})")
    pd_doc = res.get("parsed_document")
    if pd_doc:
        with st.expander("Extracted protocol facts"):
            st.json(pd_doc)
        if st.button("Use this protocol → generate", key="use_search_result"):
            pd_doc.setdefault("status", "success")
            pd_doc.setdefault("source_file", res.get("best_match_title", "web_search"))
            if not st.session_state.run_dir:
                st.session_state.run_dir = new_run_dir()
            st.session_state.input_meta = {
                **(st.session_state.input_meta or {}),
                "source_file": "web:" + res.get("best_match_title", ""),
            }
            save_json(st.session_state.run_dir, "input.json", st.session_state.input_meta)
            st.session_state.parsed = pd_doc
            save_json(st.session_state.run_dir, "parsed_document.json", pd_doc)
            st.session_state.page = "parsed"
            st.rerun()


def apply_improvements(proto: dict, sugg: dict, accept: dict) -> tuple:
    """Append accepted design improvements into the protocol. Returns (new, n)."""
    new = json.loads(json.dumps(proto))
    n = 0
    if accept.get("qc"):
        new.setdefault("qc_checkpoints", []).extend(sugg.get("add_qc_checkpoints", []))
        n += len(sugg.get("add_qc_checkpoints", []))
    if accept.get("controls") and sugg.get("add_controls"):
        new.setdefault("decision_points", []).append({
            "decision": "Include recommended controls", "when": "Experiment design",
            "options": sugg["add_controls"],
        })
        new.setdefault("open_questions_for_human", []).extend(
            f"[Control] {c}" for c in sugg["add_controls"])
        n += len(sugg["add_controls"])
    if accept.get("human_review"):
        by_id = {s.get("step_id"): s for s in new.get("workflow", [])}
        for fr in sugg.get("flag_human_review", []):
            sid, note = fr.get("step_id"), fr.get("note", "")
            if sid in by_id and note:
                by_id[sid].setdefault("human_review_required", []).append(note)
                n += 1
            elif note:
                new.setdefault("open_questions_for_human", []).append(f"[Human review] {note}")
                n += 1
    if accept.get("safety"):
        new.setdefault("preconditions", {}).setdefault("safety_notes", []).extend(
            sugg.get("add_safety_notes", []))
        n += len(sugg.get("add_safety_notes", []))
    if accept.get("reconcile"):
        new.setdefault("open_questions_for_human", []).extend(
            f"[Reconcile] {c}" for c in sugg.get("reconcile_conflicts", []))
        n += len(sugg.get("reconcile_conflicts", []))
    if accept.get("questions"):
        new.setdefault("open_questions_for_human", []).extend(sugg.get("add_open_questions", []))
        n += len(sugg.get("add_open_questions", []))
    if accept.get("new_steps") and sugg.get("suggested_new_steps"):
        wf = new.setdefault("workflow", [])
        nxt = len(wf)
        for ns in sugg["suggested_new_steps"]:
            nxt += 1
            wf.append({
                "step_id": f"step_{nxt:02d}", "step_number": nxt,
                "title": ns.get("title", "Suggested control step"),
                "purpose": ns.get("purpose", ""),
                "instructions": ns.get("instructions", []),
                "time_estimate": "[confirm with source protocol]",
                "conditions": {"temperature": "", "speed": "", "other": ""},
                "reagents": [], "expected_observation": "", "checkpoint": "",
                "pause_point": False,
                "human_review_required": ["Suggested control/addition — review placement and details."],
                "troubleshooting": [], "notes": ["[AI-suggested addition — reposition as needed]"],
            })
            n += 1
    return new, n


def _apply_workflow_edit(result, msg: str = ""):
    """Shared handler for merge/split/move/delete/precondition edits."""
    new, err = result
    if err:
        st.warning(err)
        return
    st.session_state.protocol = new
    if st.session_state.protocol_v1 and \
            st.session_state.protocol_v1.get("protocol_version") == new.get("protocol_version"):
        st.session_state.protocol_v1 = new
    st.session_state.completed_steps = set()  # step ids changed
    st.session_state.bench_idx = 0
    st.session_state._orig_instr = {}
    persist_protocol(new)
    if msg:
        st.success(msg)
    st.rerun()


def do_merge(step_ids):
    proto = st.session_state.protocol
    _apply_workflow_edit(merge_steps(proto, step_ids),
                         f"Merged {len(step_ids)} steps.")


def mark_fill_later():
    """Replace remaining [confirm…] placeholders with '(TBD)' so they no longer
    block — the user will fill them during the experiment (Bench Mode edit)."""
    proto = st.session_state.protocol
    s = json.dumps(proto, ensure_ascii=False).replace(CONFIRM_TAG, "(TBD — fill at bench)")
    new = json.loads(s)
    st.session_state.protocol = new
    if st.session_state.protocol_v1 and \
            st.session_state.protocol_v1.get("protocol_version") == new.get("protocol_version"):
        st.session_state.protocol_v1 = new
    persist_protocol(new)
    log_event("marked_fill_later", {})
    st.rerun()


def auto_resolve_confirms():
    """One-click: stage candidate values for every unconfirmed slot, through the
    uncertainty layer. Kit-library values are evidence (kit_confirmed); AI/web
    values are SUGGESTIONS (ai_suggested) the user reviews on Resolve — they never
    auto-become the protocol's confirmed value."""
    from tools.fill_slots import kit_suggestions
    proto = st.session_state.protocol
    new = json.loads(json.dumps(proto))
    uncertainty_slots.migrate_protocol(new)      # ensure registry on the working copy
    n_kit = n_ai = 0
    sources = []

    # 1) grounded kit values (free, offline) -> kit_confirmed evidence
    slots = list_slots(new)
    for sid, v in (kit_suggestions(new, slots) or {}).items():
        try:
            value_promoter.apply(new, sid, "kit_confirmed", v,
                                 {"evidence_class": "kit_confirmed", "source_name": "kit_library",
                                  "source_quote": "bundled kit library value", "confidence": 0.85},
                                 "system:kit_lookup")
            n_kit += 1
        except value_promoter.PromotionError:
            pass

    # 2) AI fill the remainder (web lookup + inference when live) -> ai_suggested
    slots2 = list_slots(new)
    if slots2:
        res = FillAgent().suggest(new, slots2, st.session_state.get("fill_context", ""),
                                  source_text=st.session_state.get("raw_text", ""))
        if res.get("status") == "success":
            props = res.get("proposals", {}) or {}
            for sid, v in (res.get("suggestions", {}) or {}).items():
                if not str(v).strip():
                    continue
                p = props.get(sid, {})
                # A model claim of *_confirmed is capped to a suggestion: only
                # deterministic evidence (Search source) or the user can confirm.
                ec = p.get("evidence_class", "ai_suggested")
                status = "typical_range" if ec == "typical_range" else "ai_suggested"
                try:
                    value_promoter.apply(new, sid, status, str(v),
                                         {"evidence_class": status,
                                          "source_name": "agent:Fill Assistant",
                                          "confidence": p.get("confidence", 0.35),
                                          "rationale": p.get("rationale", "")},
                                         "system:agent:Fill Assistant")
                    n_ai += 1
                except value_promoter.PromotionError:
                    pass
            sources = res.get("sources", []) or []
    total_filled = n_kit

    st.session_state.protocol = new
    if st.session_state.protocol_v1 and \
            st.session_state.protocol_v1.get("protocol_version") == new.get("protocol_version"):
        st.session_state.protocol_v1 = new
    persist_protocol(new)
    log_event("auto_resolved", {"kit_confirmed": n_kit, "ai_suggested": n_ai,
                                "remaining": count_confirm(new)})
    st.session_state["_auto_resolve_result"] = {
        "filled": total_filled, "kit_confirmed": n_kit, "ai_suggested": n_ai,
        "remaining": count_confirm(new), "sources": sources, "demo": DEMO_MODE,
    }
    st.rerun()


def render_step_edit(step: dict, key_prefix: str):
    """Per-step structural controls: move, split, move-to-preconditions, delete."""
    proto = st.session_state.protocol
    sid = step.get("step_id")
    c1, c2, c3, c4, c5 = st.columns(5)
    if c1.button("⬆ Up", key=f"up_{key_prefix}", use_container_width=True):
        _apply_workflow_edit(move_step(proto, sid, -1))
    if c2.button("⬇ Down", key=f"down_{key_prefix}", use_container_width=True):
        _apply_workflow_edit(move_step(proto, sid, +1))
    if c3.button("Split", key=f"split_{key_prefix}", use_container_width=True,
                 disabled=len(step.get("instructions", []) or []) < 2):
        _apply_workflow_edit(split_step(proto, sid), "Step split into sub-steps.")
    if c4.button("→Precond", key=f"pre_{key_prefix}", use_container_width=True,
                 help="Move out of the workflow into preconditions (e.g. training/prereqs)"):
        _apply_workflow_edit(move_to_preconditions(proto, sid), "Moved to preconditions.")
    if c5.button("Delete", key=f"del_{key_prefix}", use_container_width=True):
        _apply_workflow_edit(delete_step(proto, sid), "Step deleted.")


def _user_ctx():
    meta = st.session_state.input_meta or {}
    return {
        "experiment_name": meta.get("experiment_name"),
        "assay_type": meta.get("assay_type"),
        "sample_type": meta.get("sample_type"),
        "num_samples": meta.get("num_samples"),
        "experience_level": meta.get("experience_level"),
        "lab_constraints": meta.get("lab_constraints"),
        "goal": meta.get("goal"),
    }


def _selected_docs():
    docs = st.session_state.parsed_docs or [st.session_state.parsed]
    inc = st.session_state.get("doc_include", {})
    proto_docs = [d for i, d in enumerate(docs)
                  if inc.get(i, d.get("doc_type", "protocol") == "protocol")]
    ref_docs = [d for i, d in enumerate(docs)
                if not inc.get(i, d.get("doc_type", "protocol") == "protocol")]
    return proto_docs, ref_docs


def _attach_references(proto, ref_docs):
    if ref_docs:
        proto["background_references"] = [
            {"title": d.get("protocol_title", d.get("source_file", "doc")),
             "type": d.get("doc_type", "reference"), "summary": d.get("summary", "")}
            for d in ref_docs]
        oq = proto.setdefault("open_questions_for_human", [])
        for d in ref_docs:
            oq.append(f"[{d.get('doc_type','reference').title()}] Study (not a step): "
                      f"{d.get('protocol_title', d.get('source_file',''))}")


def design_experiment():
    proto_docs, ref_docs = _selected_docs()
    if not proto_docs:
        st.error("Tick at least one document as a protocol.")
        return
    with st.spinner(f"Design Agent: identifying the core experiment and de-duplicating "
                    f"{len(proto_docs)} document(s)…"):
        design = DesignAgent().design(proto_docs, _user_ctx())
    if design.get("status") == "error":
        st.error(f"Design failed: {design.get('error')}")
        return
    _attach_references(design, ref_docs)
    design["timestamp"] = utc_timestamp()

    # Layer on the experimental-DESIGN overlay (arms, controls, readouts, replicates):
    # the messy docs are analyzed, the core experiment is framed, and the gaps the notes
    # omit are filled by design. Stored for the Design tab + summarized into the protocol.
    try:
        level = (st.session_state.input_meta or {}).get("experience_level", "intermediate")
        ddocs = st.session_state.get("source_docs") or [
            {"title": d.get("protocol_title", ""), "text": d.get("summary", "")} for d in proto_docs]
        overlay = ExperimentDesignAgent().design("", _design_ctx(), ddocs, level)
        if overlay.get("status") == "success":
            st.session_state["design_result"] = overlay
            if st.session_state.get("current_project"):
                try:
                    proj.set_project_memory(st.session_state["current_project"], "design", overlay)
                except Exception:
                    pass
            # surface the design framing on the protocol itself
            ctrls = overlay.get("controls", {}) or {}
            flat_ctrls = "; ".join(f"{k}: {', '.join(v)}" for k, v in ctrls.items() if v)
            oq = design.setdefault("open_questions_for_human", [])
            if overlay.get("hypothesis"):
                oq.append(f"[Design] Hypothesis: {overlay['hypothesis']}")
            if flat_ctrls:
                oq.append(f"[Design] Controls to include — {flat_ctrls}")
            if overlay.get("readouts"):
                oq.append(f"[Design] Primary/secondary readouts: {', '.join(overlay['readouts'])}")
            # surface the VALIDATION assay onto the protocol itself (QC checkpoint + open
            # question) so the readout that proves the goal isn't lost — e.g. an anti-mCherry
            # Western for P2A WT vs mutant, with the expected band-size difference.
            for va in overlay.get("validation_assays", []) or []:
                exp = va.get("expected_results") or {}
                exp_s = ("; ".join(f"{k}: {v}" for k, v in exp.items())
                         if isinstance(exp, dict) else str(exp))
                oq.append(f"[Design] Validation — {va.get('name','')}: {va.get('rationale','')}"
                          + (f" Expected: {exp_s}" if exp_s else ""))
                design.setdefault("qc_checkpoints", []).append({
                    "checkpoint_name": va.get("name", "Validation assay"),
                    "when": "validation / readout",
                    "measurements": [va.get("method", "")],
                    "pass_criteria": ([f"{k}: {v}" for k, v in exp.items()]
                                      if isinstance(exp, dict) else [str(exp)]),
                    "fail_signals": ["result does not match the expected pattern"],
                    "recommended_action_on_fail": "re-check construct identity, antibody, and controls.",
                })
    except Exception:
        pass

    parsed_stub = {
        "agent": "Design Agent", "status": "success",
        "protocol_title": design.get("protocol_title", "Designed experiment"),
        "assay_type": design.get("assay_type", ""),
        "source_file": "designed:" + ",".join(d.get("source_file", "") for d in proto_docs),
        "summary": design.get("summary", ""),
        "materials": design.get("materials", []), "equipment": [],
        "sample_requirements": [], "major_steps": [s.get("title", "") for s in design.get("workflow", [])],
        "safety_notes": [], "uncertain_fields": [],
    }
    log_event("experiment_designed",
              {"docs": len(proto_docs), "steps": len(design.get("workflow", [])),
               "redundancies": len(design.get("redundancies_resolved", []))})
    _install_protocol(design, parsed_stub, parsed_stub["source_file"])


def generate_protocol():
    meta = st.session_state.input_meta
    parsed = st.session_state.parsed
    docs = st.session_state.parsed_docs or [parsed]
    run_dir = st.session_state.run_dir
    user_ctx = {
        "experiment_name": meta.get("experiment_name"),
        "assay_type": meta.get("assay_type") or parsed.get("assay_type"),
        "sample_type": meta.get("sample_type"),
        "num_samples": meta.get("num_samples"),
        "experience_level": meta.get("experience_level"),
        "lab_constraints": meta.get("lab_constraints"),
        "goal": meta.get("goal"),
    }
    # route choices made in Route discovery -> expand only the selected route(s)
    _routes = _route_selections()
    if _routes:
        user_ctx["selected_routes"] = _routes
    if len(docs) > 1:
        inc = st.session_state.get("doc_include", {})
        proto_docs = [d for i, d in enumerate(docs) if inc.get(i, d.get("doc_type", "protocol") == "protocol")]
        ref_docs = [d for i, d in enumerate(docs) if not inc.get(i, d.get("doc_type", "protocol") == "protocol")]
        if not proto_docs:
            st.error("No documents selected as protocols. Tick 'Use as protocol' for at least one.")
            return
        with st.spinner(f"Protocol Agent: building & combining {len(proto_docs)} protocol(s)…"):
            protos = [ProtocolAgent().generate(d, user_ctx) for d in proto_docs]
            protos = [p for p in protos if p.get("status") != "error"]
            if not protos:
                st.error("Protocol generation failed for all documents.")
                return
            proto = combine_protocols(protos) if len(protos) > 1 else protos[0]
            # attach the non-protocol docs as project background / references
            if ref_docs:
                proto["background_references"] = [
                    {"title": d.get("protocol_title", d.get("source_file", "doc")),
                     "type": d.get("doc_type", "reference"),
                     "summary": d.get("summary", "")}
                    for d in ref_docs
                ]
                oq = proto.setdefault("open_questions_for_human", [])
                for d in ref_docs:
                    oq.append(f"[{d.get('doc_type','reference').title()}] Study (not a step): "
                              f"{d.get('protocol_title', d.get('source_file',''))}")
            proto["timestamp"] = utc_timestamp()
    else:
        with st.spinner("Protocol Agent (strong model): synthesizing bench-ready protocol…"):
            proto = ProtocolAgent().generate(parsed, user_ctx)
        if proto.get("status") == "error":
            st.error(f"Protocol generation failed: {proto.get('error')}")
            return

    st.session_state.protocol = proto
    st.session_state.protocol_v1 = proto
    save_json(run_dir, "protocol_v1.json", proto)
    save_text(run_dir, "protocol_v1.md", protocol_to_markdown(proto))
    save_text(run_dir, "protocol_bench_v1.md", bench_to_markdown(proto))
    log_event("protocol_generated", {"version": proto.get("protocol_version")})

    # Simple Review Agent pass (strong, safety-critical)
    with st.spinner("Review Agent (strong model): critiquing for safety & completeness…"):
        review = ReviewAgent().review(proto, parsed)
    st.session_state.review = review
    save_json(run_dir, "review_v1.json", review)
    log_event("protocol_reviewed", {"decision": review.get("decision")})

    st.session_state.completed_steps = set()
    st.session_state.bench_idx = 0
    st.session_state.page = "protocol"
    st.rerun()


# ---------------------------------------------------------------------- #
# Page C: Protocol
# ---------------------------------------------------------------------- #
_RXN_KW = ("reaction", "master mix", "mastermix", "per reaction", "per rxn", "pcr",
           "ligation", "ligate", "digest", "assembly", "gibson", "golden gate",
           "tagment", "rt reaction", "cdna", "mix")


def _render_master_mix(proto: dict):
    """Reaction setup / master mix: standardized per-reaction values × N reactions
    (+ overage). Surfaces reaction-step reagents that already have a per-reaction value."""
    rows = []  # {step, item, per_rxn}
    for s in proto.get("workflow", []) or []:
        text = (str(s.get("title", "")) + " "
                + " ".join(str(i) for i in s.get("instructions", []) or [])).lower()
        if not any(k in text for k in _RXN_KW):
            continue
        sid = s.get("step_id")
        for ri, r in enumerate(s.get("reagents", []) or []):
            o = uncertainty_slots.get(proto, f"step:{sid}:reag:{ri}:amount")
            if not o:
                continue
            val = o.get("recommended_candidate") if o.get("status") not in uncertainty_slots.CONFIRMED \
                else o.get("current_value")
            if val and standard_units.parse_number(str(val)) is not None:
                rows.append({"step": s.get("title", sid), "name": r.get("item", "reagent"),
                             "per_rxn": str(val)})
    if not rows:
        return
    meta = st.session_state.input_meta or {}
    with st.expander(f"Master mix · {len(rows)}"):
        st.caption("Per-reaction values × N reactions (+ overage) = master-mix totals.")
        c1, c2 = st.columns(2)
        n = int(c1.number_input("Reactions (N)", min_value=1,
                                value=int(meta.get("num_samples", 1) or 1), step=1, key="mm_n"))
        ov = c2.slider("Overage %", 0, 50, 10, key="mm_ov") / 100.0
        mm = reaction_scaling.master_mix(rows, n, ov)
        st.markdown(f"**Master mix for {n} reactions** "
                    f"(prepare ~{mm['reactions_with_overage']}× with overage)")
        for r in mm["rows"]:
            st.markdown(f"- **{r.get('name') or 'reagent'}** — {r.get('per_rxn','')} / rxn → "
                        f"**{r.get('total') or '—'}** total")
        st.caption(mm["note"])


def _render_improvements(proto: dict):
    """AI design-improvement suggestions (controls · QC · human-review flags) shown and
    applied inline. Same engine as the old 'Suggest improvements' panel — now folded into
    'Raise confidence' so there is one quality hub, not two overlapping ones."""
    sugg = st.session_state.get("improve_suggestions")
    if not sugg:
        return
    if sugg.get("status") == "error":
        st.error(f"Couldn't draft improvements: {sugg.get('error')}")
        return
    if sugg.get("summary"):
        st.info(sugg["summary"])
    cats = [
        ("controls", "Controls", sugg.get("add_controls", []), lambda x: f"- {x}"),
        ("qc", "QC checkpoints", sugg.get("add_qc_checkpoints", []),
         lambda q: f"- **{q.get('checkpoint_name','')}** ({q.get('when','')}) — "
                   f"on fail: {q.get('recommended_action_on_fail','')}"),
        ("human_review", "Human-review flags", sugg.get("flag_human_review", []),
         lambda fr: f"- `{fr.get('step_id','?')}`: {fr.get('note','')}"),
        ("safety", "Safety notes", sugg.get("add_safety_notes", []), lambda x: f"- {x}"),
        ("reconcile", "Conflicts to reconcile", sugg.get("reconcile_conflicts", []), lambda x: f"- {x}"),
        ("questions", "Open design questions", sugg.get("add_open_questions", []), lambda x: f"- {x}"),
        ("new_steps", "Suggested control steps", sugg.get("suggested_new_steps", []),
         lambda s: f"- **{s.get('title','')}**: {s.get('purpose','')}"),
    ]
    with st.form("improve_form"):
        accept = {}
        for key, label, items, fmt in cats:
            if not items:
                continue
            accept[key] = st.checkbox(f"Apply {label} ({len(items)})", value=True, key=f"imp_{key}")
            for it in items[:8]:
                st.markdown(fmt(it))
            st.write("")
        applied = st.form_submit_button("Apply selected", use_container_width=True)
    if applied:
        new, cnt = apply_improvements(proto, sugg, accept)
        st.session_state.protocol = new
        if st.session_state.protocol_v1 and \
                st.session_state.protocol_v1.get("protocol_version") == new.get("protocol_version"):
            st.session_state.protocol_v1 = new
        persist_protocol(new)
        st.session_state.improve_suggestions = None
        log_event("improve_applied", {"n": cnt})
        st.success(f"Applied {cnt} improvement(s).")
        st.rerun()


def _render_assay_gaps(proto: dict):
    """Context-aware 'clarify to design' panel: detects which assays the protocol contains
    (digest, PCR, ligation, cell culture, CUT&Tag) and surfaces the standardization values
    each one needs but is still missing — so the user clarifies only what's relevant."""
    found = assay_gaps.detect(proto)
    found = [a for a in found if a["gaps"]]
    if not found:
        return
    n = sum(len(a["gaps"]) for a in found)
    with st.expander(f"Clarify to design · {n} to specify"):
        st.caption("Values this assay needs that are NOT yet in the protocol — decisions you "
                   "make to design the experiment (vs Provenance, which shows values already filled).")
        for a in found:
            st.markdown(f"**{a['assay']}** — set: " + ", ".join(a["gaps"]))
            if a["present"]:
                st.caption("already specified: " + ", ".join(a["present"]))
        st.caption("Add these in **Edit this step** or the **Fill** tab; they're assay "
                   "standards, not read from your source.")


def _render_flow_gaps(proto: dict):
    """Experimental-LOGIC review: flags steps that don't connect — missing vector digestion,
    transduction with no virus production, validation steps that aren't designed, etc. The
    point the user made: stop 'just filling steps' and reason about whether the flow works."""
    gaps = flow_check.detect(proto)
    if not gaps:
        return
    with st.expander(f"Logic & flow gaps · {len(gaps)}", expanded=True):
        st.caption("Where the experiment's steps don't connect — gaps a thinking bench scientist "
                   "would catch. Use 'Suggest improvements' (Raise confidence) to add the fixes.")
        for g in gaps:
            st.markdown(f"- **{g['where']}** — {g['issue']}")
            st.caption(f"Fix: {g['fix']}")


def _render_sequences(proto: dict):
    """Captured DNA/oligo sequences from the uploaded docs (WT/Mut inserts, primers). Shows
    each with its label, length and kind; downloadable as FASTA. Self-gates on presence."""
    seqs = proto.get("sequences") or []
    if not seqs:
        return
    with st.expander(f"Sequences · {len(seqs)}"):
        st.caption("DNA/oligo sequences found in your uploaded documents — kept for cloning, "
                   "primer/PCR design and junction checks.")
        for s in seqs:
            st.markdown(f"**{s.get('label') or '(unlabelled)'}** — {s['length']} bp · {s['kind']}"
                        + (f"  ·  _{s.get('source','')}_" if s.get("source") else ""))
            st.code(s["sequence"], language=None)
        fasta = "\n".join(f">{(s.get('label') or f'seq{i+1}').replace(' ', '_')}\n{s['sequence']}"
                          for i, s in enumerate(seqs))
        st.download_button("⬇ Sequences (.fasta)", data=fasta, file_name="sequences.fasta",
                           mime="text/plain", key="dl_fasta", use_container_width=True)


def _render_design_tools(proto: dict):
    """Auxiliary Design panels — context-aware: each sub-panel renders only when it is
    relevant to this assay (e.g. vessel scaling needs cell-culture volumes; master mix
    needs reaction reagents), so the rail isn't cluttered with tools that don't apply."""
    _render_sequences(proto)          # self-gates: only if sequences were captured from uploads
    _render_flow_gaps(proto)          # self-gates: only if experimental-logic gaps are detected
    _render_assay_gaps(proto)         # self-gates: only if a detected assay has missing standards
    _render_vessel_control(proto)     # self-gates: only if media/wash volumes exist (cell work)
    _render_master_mix(proto)         # self-gates: only if reaction reagents exist (PCR/digest/ligation)
    _render_references(proto)
    _render_knowledge_lookup(proto)


def _render_knowledge_lookup(proto: dict):
    """Live recommendation/reference lookup routed by entity type to the right
    knowledge provider (Ensembl/UniProt/ChEMBL/PubMed). Opt-in (Resolve toggle)."""
    with st.expander("Look up · gene · protein · molecule"):
        if not st.session_state.get("knowledge_enabled"):
            st.caption("Turn on 'Use knowledge sources' on the Resolve tab to query live, "
                       "cited databases (Ensembl · UniProt · ChEMBL · PubMed).")
            return
        import knowledge_sources as ks
        kinds = {"Gene (Ensembl)": ks.EntityType.GENE, "Protein (UniProt)": ks.EntityType.PROTEIN,
                 "Small molecule (ChEMBL)": ks.EntityType.SMALL_MOLECULE,
                 "Literature (PubMed)": ks.EntityType.LITERATURE}
        c1, c2 = st.columns([1, 2])
        kind = c1.selectbox("Type", list(kinds), key="klookup_kind")
        q = c2.text_input("Query", key="klookup_q",
                          placeholder="e.g. TP53 · aspirin · CUT&Tag H3K27ac")
        if st.button("Look up", key="klookup_go") and q.strip():
            broker = _knowledge_broker()
            with st.spinner("Querying knowledge sources…"):
                recs = broker.retrieve_records(kinds[kind], q.strip()) if broker else []
            if not recs:
                st.info("No results (or the source was unavailable).")
            for r in recs[:6]:
                st.markdown(f"**{r.entity_name}** — {r.value}")
                if r.notes:
                    st.caption(r.notes)
                cit = r.citation
                if cit:
                    st.caption(f"{cit.company} · {cit.identifier}"
                               + (f" · {cit.document_version}" if cit.document_version else ""))
                    if cit.url:
                        st.caption(cit.url)


def _render_vessel_control(proto: dict):
    """Live graph binding: set the culture vessel; media/wash volumes on role-tagged
    steps re-derive automatically (recomputed suggestions, confirmed values untouched)."""
    params = proto.setdefault("parameters", {})
    names = [v["name"] for v in vessels.list_vessels()]
    cur = params.get("vessel")
    tagged = slot_roles.tag_roles(proto)  # ensure roles present
    n_media = len(slot_roles.slots_with_role(proto, "media_volume"))
    n_wash = len(slot_roles.slots_with_role(proto, "wash_volume"))
    if (n_media + n_wash) == 0:
        return  # nothing to scale, hide the control
    with st.expander(f"Vessel scaling · {n_media + n_wash} volumes"):
        st.caption(f"{n_media + n_wash} media/wash volume(s) are tied to the culture vessel. "
                   "Change the vessel and they re-derive as suggestions (confirmed values kept).")
        idx = names.index(cur) if cur in names else names.index("T75 flask")
        new_v = st.selectbox("Culture vessel", names, index=idx, key="proto_vessel")
        if st.button("Apply vessel — rescale dependents", key="apply_vessel", type="primary"):
            changes = protocol_binding.apply_rescale_to_vessel(proto, new_v, _user_email(),
                                                               from_vessel=cur)
            params["vessel"] = new_v
            persist_protocol(proto)
            applied = [c for c in changes if not c.get("skipped")]
            log_event("vessel_rescale", {"to": new_v, "applied": len(applied)})
            st.success(f"Vessel set to {new_v}. Rescaled {len(applied)} value(s) "
                       f"(as suggestions to confirm).")
            for c in changes:
                st.caption(f"• {c['skipped'] if c.get('skipped') else c['explanation']}")
            st.rerun()


def _render_references(proto: dict):
    """Provenance panel — 'where did every value come from?' Groups confirmed
    (evidence-backed) vs suggested values; shows status, basis, quote, citation."""
    reg = uncertainty_slots.registry(proto)
    rows = [o for o in reg.values() if o.get("status") != "not_applicable"]
    if not rows:
        return
    confirmed = [o for o in rows if o["status"] in uncertainty_slots.CONFIRMED]
    suggested = [o for o in rows if o["status"] in uncertainty_slots.PARTIAL]
    flags = sanity_check.flag(proto)
    flagged_ids = {f["slot_id"] for f in flags}

    head = (f"Provenance · {len(flags)} to check" if flags
            else f"Provenance · {len(confirmed)}/{len(rows)} sourced")
    with st.expander(head, expanded=bool(flags)):

        def _line(o):
            val = o.get("recommended_candidate") or o.get("current_value")
            st.markdown(f"**{o.get('step_id') or 'material'} · {o['field_name']}** = `{val}`")
            st.markdown(_value_status_badge(o), unsafe_allow_html=True)
            if o.get("inference_basis"):
                st.caption(f"Why: {o['inference_basis']}")
            if o.get("source_quote"):
                st.caption(f"“{str(o['source_quote'])[:160]}”")
            loc = o.get("source_location")
            if isinstance(loc, dict):
                cit = " · ".join(str(v) for v in (loc.get("company"), loc.get("product"),
                                 loc.get("catalog_number"), loc.get("document_version")) if v)
                if cit:
                    st.caption(f"Citation: {cit}")
                if loc.get("url"):
                    st.caption(loc["url"])

        # 1) the signal: values that look biologically/chemically off (incl. uploaded source)
        if flags:
            st.markdown("**⚠ Check these — they look off for this kind of experiment**")
            for f in flags:
                st.markdown(f"- **{f['label']}** = `{f['value']}` — {f['reason']}")
            st.caption(f"Sourced from your upload/source, but flagged against domain limits. "
                       f"Fix on the Fill tab if wrong. {len(rows)} value(s) total; "
                       f"{len(confirmed)} sourced, {len(suggested)} suggested.")
        else:
            st.caption(f"No values look out of range. {len(rows)} value(s): {len(confirmed)} from "
                       f"your source/upload (trusted), {len(suggested)} suggested (confirm before use).")

        # 2) suggestions still need a human. Material details (catalog/vendor/amount) live in
        #    the Materials table (purple) — only step-level suggestions are listed here.
        sugg_step = [o for o in suggested if not str(o.get("slot_id", "")).startswith("mat:")]
        sugg_mat = [o for o in suggested if str(o.get("slot_id", "")).startswith("mat:")]
        if sugg_step:
            st.markdown("**Suggested — step values (confirm before use)**")
            for o in sugg_step[:60]:
                _line(o)
        if sugg_mat:
            st.caption(f"{len(sugg_mat)} suggested material detail(s) (catalog #, vendor, amount) "
                       "are shown in the **Materials** tab, highlighted purple.")

        # 3) the full audit of trusted source values is collapsed — no need to read 200+
        if confirmed:
            with st.expander(f"Show full audit of {len(confirmed)} sourced value(s)"):
                for o in confirmed[:200]:
                    _line(o)


_NUCLEIC_KW = ("dsdna", "ssdna", "oligo", "primer", "gblock", "gene fragment", "synthesized",
               "synthetic")
_PLASMID_KW = ("plasmid", "vector", "backbone", "construct", "pspax", "pmd2", "pcg", "transfer plasmid")


def _catalog_optional(item: str) -> str:
    """Return a label if a catalog number is OPTIONAL for this item (so a blank catalog is not
    a gap), else ''. Synthesized DNA/oligos have no catalog (ordered by sequence from IDT/Twist);
    plasmids may be in-house (or an Addgene #), so don't demand a catalog/vendor either."""
    it = str(item or "").lower()
    if any(k in it for k in _NUCLEIC_KW):
        return "n/a — synthesized"
    if any(k in it for k in _PLASMID_KW):
        return "n/a — plasmid (in-house or Addgene)"
    return ""


def _mat_cell(proto: dict, i: int, field: str, fallback):
    """(value, is_ai) for a material field. is_ai=True marks UNVERIFIED values to highlight:
    an AI/typical suggestion, OR a value with no source on record (legacy-imported) — both are
    'the agent put this here, confirm it'. A source-backed confirmation is not highlighted."""
    o = uncertainty_slots.get(proto, f"mat:{i}:{field}")
    if o:
        stt = o.get("status")
        if stt in uncertainty_slots.PARTIAL:
            return _clean_val(o.get("recommended_candidate")), True
        if stt in uncertainty_slots.CONFIRMED:
            v = _clean_val(o.get("current_value")) or _clean_val(fallback)
            # confirmed but with NO source quote/citation on record -> unverified (AI/auto)
            unverified = o.get("legacy_imported") or not (
                o.get("source_quote") or o.get("source_location") or o.get("citation"))
            return v, bool(v and unverified)
    v = _clean_val(fallback)
    return ("" if str(v).startswith("(TBD") else v), False


def _render_materials_table(proto: dict):
    """Materials as an HTML table. AI-suggested defaults (catalog #, vendor, amount that the
    parser left blank and the agent proposed) are highlighted PURPLE with an 'AI' tag, so the
    full reagent/product detail lives here — not as a long list in the Provenance panel."""
    mats = proto.get("materials", []) or []
    if not mats:
        st.caption("No materials listed.")
        return
    cols = [("Item", "item"), ("Vendor", "vendor"), ("Catalog #", "catalog_number"),
            ("Amount / conc.", "amount"), ("Required", "required"), ("Notes", "notes")]
    any_ai = False
    body = []
    for i, m in enumerate(mats):
        tds = []
        cat_label = _catalog_optional(m.get("item", ""))
        for label, field in cols:
            if field in ("vendor", "catalog_number", "amount"):
                v, is_ai = _mat_cell(proto, i, field, m.get(field, ""))
            else:
                v, is_ai = _clean_val(m.get(field, "")), False
            v = "" if str(v).startswith("(TBD") else v
            # synthesized DNA/oligo OR (possibly in-house) plasmid: catalog optional, not a gap
            if field in ("catalog_number", "vendor") and cat_label and not v:
                tds.append(f"<td class='na'>{cat_label if field == 'catalog_number' else '—'}</td>")
                continue
            if is_ai and v:
                any_ai = True
                tds.append(f"<td class='ai'>{v} <span class='aitag'>AI</span></td>")
            else:
                tds.append(f"<td>{v or '—'}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    head = "".join(f"<th>{c}</th>" for c, _ in cols)
    css = ("<style>.mattbl{border-collapse:collapse;width:100%;font-size:13px;margin-top:4px}"
           ".mattbl th,.mattbl td{border:1px solid #E5E7EB;padding:6px 9px;text-align:left;vertical-align:top}"
           ".mattbl th{background:#FAFAFA;font-weight:700}"
           ".mattbl td.ai{background:#F3F0FF;color:#5B3DF5;font-weight:600}"
           ".mattbl td.na{color:#9CA3AF;font-style:italic}"
           ".mattbl .aitag{font-size:10px;font-weight:800;color:#6D28D9;background:#EDE9FE;"
           "border-radius:6px;padding:1px 5px;margin-left:5px;vertical-align:middle}"
           "</style>")
    st.markdown(css + f"<table class='mattbl'><thead><tr>{head}</tr></thead><tbody>"
                + "".join(body) + "</tbody></table>", unsafe_allow_html=True)
    if any_ai:
        st.caption("Purple = AI-suggested / unverified (no source on record) — verify before "
                   "ordering or relying on it.")


def page_protocol(tools_col=None):
    # When a tools_col (right panel) is given, secondary analysis panels render there
    # instead of inline, leaving a minimal canvas. _tx is "the tools container or st".
    _tx = tools_col or st
    proto = st.session_state.protocol
    normalize_protocol(proto)
    level = (st.session_state.input_meta or {}).get("experience_level", "intermediate")
    _ver = str(proto.get('protocol_version', 'v1'))
    _ver = _ver if _ver.lower().startswith('v') else f"v{_ver}"
    hero(proto.get('protocol_title', 'Protocol'),
         f"Review &amp; fill · {_ver} · {proto.get('assay_type','')}")

    workflow = proto.get("workflow", []) or []
    n_confirm = count_confirm(proto)

    # beginner gets a more detailed, guided view by default
    is_beginner = "begin" in level.lower() or "novice" in level.lower()
    if is_beginner:
        st.info("**Beginner view** — steps show extra detail and 'why it matters'. "
                "Use **Expand into detailed steps** on any step for full instructions, "
                "and the **Learn** tab (top) to study the concepts.")

    # (The 'Learn alongside' panel was removed — studying the experiment lives in the dedicated
    #  Learn workspace tab, so the Design rail stays focused on building the protocol.)
    # dynamic readiness -> keep the protocol's confidence in sync with its state
    rd = compute_readiness(proto)
    if proto.get("confidence") != rd["level"]:
        proto["confidence"] = rd["level"]
        persist_protocol(proto)
    from tools.readiness import completeness as _completeness
    comp = _completeness(proto)
    metric_cards([
        ("Confidence", rd["level"].title(), f"evidence {rd['score']}/100"),
        ("Filled", f"{comp['score']}%", f"{comp['confirmed']} confirmed · {comp['to_confirm']} to verify"),
        ("Steps", str(len(workflow))),
        ("QC gates", str(len(proto.get("qc_checkpoints", []) or []))),
        ("To confirm", str(n_confirm), "unfilled values"),
    ])
    if comp["total"]:
        if comp["ready"]:
            st.success(f"Bench-ready: {comp['score']}% filled with standardized values — "
                       f"verify {comp['to_confirm']} unconfirmed value(s) at the bench before relying on them.")
        elif comp["conflicts"]:
            st.warning(f"{comp['score']}% filled, but {comp['conflicts']} conflict(s) to resolve first.")
        else:
            st.info(f"{comp['score']}% filled — run **Auto-fill all** on the Resolve tab to reach "
                    "bench-ready (≥90%), then confirm the high-risk values.")

    render_workflow_chart(proto)

    with _tx.expander(f"Raise confidence · {rd['score']}/100",
                     expanded=rd["level"] == "low"):
        st.caption("Close the gaps below to raise confidence.")
        for f in rd["factors"]:
            mark = "✓" if f["ok"] else "•"
            st.markdown(f"{mark} **{f['label']}** — {f['points']}/{f['max']}")
            if not f["ok"]:
                st.caption(f["detail"])
        c1, c2 = st.columns(2)
        if c1.button("Fill values", key="rd_fill", use_container_width=True):
            st.session_state.page = "fill"; st.rerun()
        if c2.button("Suggest improvements", key="rd_improve", use_container_width=True,
                     help="AI proposes controls, QC checkpoints and human-review flags to apply"):
            with st.spinner("Design Assistant: drafting improvements…"):
                st.session_state.improve_suggestions = ImproveAgent().suggest(proto, st.session_state.review)
            log_event("improve_suggested", {"mode": (st.session_state.improve_suggestions or {}).get("mode")})
            st.rerun()
        _render_improvements(proto)   # inline: review & apply AI suggestions here

    with _tx.expander("Correct the experiment",
                     expanded=False):
        st.caption("Say what's wrong in plain language. The Protocol Agent rewrites only the "
                   "affected steps, bumps the version, and logs the change.")
        corr = st.text_area("Your correction", key="proto_correction",
                            placeholder="What is the real experiment / what should change?")

        st.caption("Optional: add a reference protocol (most reliable) — paste it or upload a file.")
        ref_paste = st.text_area(
            "Paste reference (optional)", key="proto_ref_paste", height=120,
            placeholder="e.g. Bind anti-H3K27ac 1:50 overnight 4°C; pAG-Tn5 1 h RT; tagment 37°C…")
        ref_file = st.file_uploader("…or upload (.pdf/.docx/.txt/.md/.xlsx/.csv)",
                                    type=["pdf", "docx", "txt", "md", "xlsx", "xls", "csv"],
                                    key="proto_ref_file")
        ref_text = (ref_paste or "").strip()
        if ref_file is not None:
            try:
                ref_text = (ref_text + "\n\n" + extract_text(
                    path="", raw_bytes=ref_file.getvalue(), file_name=ref_file.name)).strip()
                st.caption(f"Read {ref_file.name} ({len(ref_text)} chars).")
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Couldn't read that file: {exc}")

        if st.button("Apply correction (new version)", key="apply_correction_btn",
                     type="primary", disabled=not corr.strip()):
            apply_correction(corr, st.session_state.get("chat_history"),
                             reference_text=ref_text)
            st.rerun()
        _render_correction_flash()

    if proto.get("background_references"):
        with _tx.expander(f"Background & references · {len(proto['background_references'])}"):
            for r in proto["background_references"]:
                st.markdown(f"- **[{r.get('type','ref')}]** {r.get('title','')}")
                if r.get("summary"):
                    st.caption(r["summary"][:300])
    if proto.get("kit_source"):
        st.info(f"Values sourced from **{proto['kit_source'].get('title','')}**. "
                + proto["kit_source"].get("provenance", ""))
    if n_confirm:
        cw1, cw2 = st.columns([3, 2])
        cw1.warning(f"{n_confirm} value(s) need filling (volumes/speeds/times).")
        if cw2.button("Auto-resolve from source & kits", key="auto_resolve_proto",
                      type="primary", use_container_width=True):
            with st.spinner("Resolving values from kits and the manufacturer's protocol…"):
                auto_resolve_confirms()
        if detect_format_questions(proto):
            st.caption("This kit has multiple formats (e.g. spin vs vacuum). Open **F. Fill** "
                       "and pick the format first so Auto-resolve fills exact values.")
        ar2 = st.session_state.pop("_auto_resolve_result", None)
        if ar2:
            st.success(f"Filled {ar2['filled']} value(s); {ar2['remaining']} left. "
                       + ("(Demo: kits only.)" if ar2.get("demo") else ""))

    # Review banner
    review = st.session_state.review
    if review and review.get("status") == "success":
        decision = review.get("decision", "")
        msg = f"Review decision: **{decision}** — {review.get('rationale','')}"
        if decision in ("revise", "reject"):
            st.error(msg)
        elif decision == "approve_with_caution":
            st.warning(msg)
        else:
            st.success(msg)
        with _tx.expander("Full review findings"):
            for f in review.get("findings", []):
                st.write(f"- **[{f.get('severity')}] {f.get('category')}** — {f.get('issue')}")
            if review.get("unresolved_confirm_tags"):
                st.caption(f"Unresolved confirm tags: {review['unresolved_confirm_tags']}")

    with _tx.expander("Consistency audit"):
        st.caption("Flags redundant steps, contradictions, and out-of-order stages. Nothing changes.")
        if st.button("Run consistency audit", key="run_audit_proto", use_container_width=True):
            gt = next((d.get("text", "") for d in _learn_source_docs()
                       if "ground-truth" in d.get("title", "").lower()
                       or "study notes" in d.get("title", "").lower()), "")
            with st.spinner("Consistency Auditor: checking the protocol…"):
                st.session_state["audit_result_proto"] = AuditAgent().audit(
                    docs=st.session_state.get("parsed_docs", []), protocol=proto, ground_truth=gt)
            st.rerun()
        _render_audit(st.session_state.get("audit_result_proto"))

    # --- merge / consolidate steps ---
    with _tx.expander("Merge steps"):
        st.caption("Combine consecutive steps into one (instructions, reagents, conditions are "
                   "merged). Renumbers the workflow; bench progress resets.")
        labels = {f"Step {s.get('step_number')} — {s.get('title')}": s.get("step_id")
                  for s in workflow}
        picks = st.multiselect("Select consecutive steps to merge", list(labels.keys()),
                              key="merge_pick")
        if st.button("Merge selected", disabled=len(picks) < 2, key="merge_btn"):
            do_merge([labels[p] for p in picks])
        sugg = suggest_merges(proto)
        if sugg:
            st.markdown("**Suggested merges** (runs of consecutive single-action steps):")
            num_by_id = {s.get("step_id"): s.get("step_number") for s in workflow}
            for gi, group in enumerate(sugg):
                nums = ", ".join(str(num_by_id.get(sid, "?")) for sid in group)
                if st.button(f"Merge steps {nums}", key=f"merge_sugg_{gi}"):
                    do_merge(group)
        else:
            st.caption("No obvious consecutive trivial steps to suggest.")

    t_wf, t_mat, t_qc, t_fb, t_oq = st.tabs(
        ["Workflow", "Materials", "QC gates", "Failure branches", "Open questions"]
    )

    with t_wf:
        st.caption(f"{len(workflow)} steps — values are pre-filled as suggestions (labeled "
                   "_verify_); only high-risk/unverifiable values are left for you to confirm.")
        for i, s in enumerate(workflow):
            with st.container(border=True):
                stage = f"  ·  _{s['stage']}_" if s.get("stage") else ""
                st.markdown(f"#### Step {s.get('step_number')} — {s.get('title')}{stage}")
                _render_step_detail(s)
                render_expand_step(s, f"wf_{i}_{s.get('step_id')}")
                render_step_edit(s, f"wf_{i}_{s.get('step_id')}")

    with t_mat:
        _render_materials_table(proto)

    with t_qc:
        for q in proto.get("qc_checkpoints", []) or []:
            st.markdown(f"**{q.get('checkpoint_name','')}** — _{q.get('when','')}_")
            st.write(f"Measurements: {', '.join(q.get('measurements', []))}")
            st.write(f"Pass: {', '.join(q.get('pass_criteria', []))}")
            st.write(f"Fail: {', '.join(q.get('fail_signals', []))}")
            st.write(f"On fail: {q.get('recommended_action_on_fail','')}")
            st.divider()

    with t_fb:
        for b in proto.get("failure_branches", []) or []:
            st.markdown(f"**{b.get('condition','')}**")
            st.write(f"Steps affected: {', '.join(b.get('step_ids_affected', []))}")
            st.write(f"Likely causes: {', '.join(b.get('likely_causes', []))}")
            st.write(f"Modifications: {', '.join(b.get('recommended_modifications', []))}")
            st.write(f"Repeat/stop: {b.get('whether_to_repeat_or_stop','')}")
            st.divider()

    with t_oq:
        for q in proto.get("open_questions_for_human", []) or []:
            st.write(f"- {q}")

    st.divider()
    _download_buttons(proto)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("▶ Open Bench Mode", use_container_width=True, type="primary"):
            st.session_state.page = "bench"
            st.rerun()
    with c2:
        if st.button("Plan by day", use_container_width=True):
            st.session_state.page = "plan"
            st.rerun()
    with c3:
        if st.button("Fill in details", use_container_width=True):
            st.session_state.page = "fill"
            st.rerun()
    with c4:
        with st.expander("View JSON"):
            st.json(proto)

    st.divider()
    with st.expander("Save this experiment to a project (for later / paper writing)"):
        projects = proj.list_projects()
        names = [p["name"] for p in projects]
        col1, col2 = st.columns([2, 1])
        with col1:
            existing = st.selectbox("Project", ["New project…"] + names, key="save_proj_pick")
            new_name = ""
            if existing == "New project…":
                new_name = st.text_input("New project name", key="save_proj_new",
                                         placeholder="e.g. CUT&Tag optimization 2026")
        with col2:
            status = st.selectbox("Outcome", ["worked", "in_progress", "failed"], key="save_proj_status")
        notes = st.text_input("Notes (optional)", key="save_proj_notes",
                              placeholder="e.g. final conditions that gave clean bands")
        if st.button("Save to project", key="save_proj_btn", type="primary"):
            target = new_name.strip() if existing == "New project…" else existing
            if not target:
                st.error("Enter a project name.")
            else:
                exp_id = proj.save_experiment(target, proto, st.session_state.input_meta,
                                              status=status, notes=notes,
                                              plan=st.session_state.plan,
                                              source_documents=st.session_state.get("source_docs", []),
                                              parsed_docs=st.session_state.get("parsed_docs", []))
                st.session_state.current_project = proj._slug(target)
                log_event("experiment_saved", {"project": target, "exp_id": exp_id, "status": status})
                st.success(f"Saved to project '{target}'. Open Projects to document it.")

    st.divider()
    render_chat(key="chat_protocol")


def _li_text(x) -> str:
    """Coerce a list item to display text — tolerates a model returning dicts (e.g. a safety
    note as {item, context, source_quote}) where a string was expected, so renders never crash."""
    if isinstance(x, dict):
        return str(x.get("item") or x.get("text") or x.get("note") or x.get("name")
                   or x.get("value") or "; ".join(f"{k}: {v}" for k, v in x.items() if v) or "")
    return str(x)


def _clean_val(v):
    """Return a display value, or '' if it's empty, a placeholder, or a non-value token
    like 'n/a' / 'none' / '-' (so we never render '• n/a' or force a meaningless field)."""
    v = v.strip() if isinstance(v, str) else v
    if not v or v == CONFIRM_TAG:
        return ""
    if isinstance(v, str) and v.strip().lower() in ("n/a", "na", "none", "null", "-", "—", "tbd", "?"):
        return ""
    return v


def _step_text(s: dict) -> str:
    return (str(s.get("title", "")) + " " + " ".join(str(i) for i in s.get("instructions", []) or [])).lower()


def _confirm_clue(text: str) -> str:
    """The few words just before a [confirm…] placeholder, so the user knows which
    value in the sentence is missing (e.g. '…incubate at' → temperature)."""
    seg = str(text).split(CONFIRM_TAG)[0].strip().rstrip(":–-—= ")
    words = seg.split()
    clue = " ".join(words[-6:]).strip()
    return clue


def _missing_fields(s: dict) -> list:
    """Return SPECIFIC, human-readable names of the values that still need filling for
    this step — so Bench mode tells you exactly what to enter, not just a count.
    Irrelevant template placeholders (a spin speed on an 'order oligos' step) are
    excluded by the same common-sense filter."""
    txt = _step_text(s)
    fields: list = []
    for i in s.get("instructions", []) or []:
        si = str(i)
        n_ph = si.count(CONFIRM_TAG)
        if n_ph:
            clue = _confirm_clue(si)
            label = f"value in instruction: “…{clue}”" if clue else "a value in the instructions"
            fields.extend([label] * n_ph)
    for r in s.get("reagents", []) or []:
        if str(r.get("amount", "")).strip() == CONFIRM_TAG:
            fields.append(f"amount of {r.get('item', 'a reagent')}")
    cond = s.get("conditions", {}) or {}
    instr_text = " ".join(str(i) for i in s.get("instructions", []) or [])
    # a condition isn't "missing" if the value is already written in the instructions
    has_dur = bool(re.search(r"\b\d+(\.\d+)?\s?(s|sec|secs|second|seconds|min|mins|minute|"
                             r"minutes|h|hr|hrs|hour|hours|day|days)\b|\bovernight\b|\bo/n\b",
                             instr_text, re.I))
    has_temp = bool(re.search(r"\b\d+(\.\d+)?\s?°?\s?c\b|\broom temp|\brt\b|\bon ice\b",
                              instr_text, re.I))
    has_speed = bool(re.search(r"\b\d[\d,]*\s?(x\s?g|×g|rpm|rcf)\b", instr_text, re.I))
    needs_spin = any(k in txt for k in ("spin", "centrifug", "pellet", "rpm", "x g", "×g", "rcf"))
    needs_temp = any(k in txt for k in ("incubat", "°c", " ice", "heat", "warm", "chill",
                                        "thaw", "denatur", "anneal", "37", "65", "95", "4°"))
    needs_time = any(k in txt for k in ("incubat", "wash", "spin", "centrifug", "rotate",
                                        "shake", "min", "hour", "overnight", "sec"))
    if needs_spin and not has_speed and str(cond.get("speed", "")).strip() == CONFIRM_TAG:
        fields.append("centrifuge speed (× g / rpm)")
    if needs_temp and not has_temp and str(cond.get("temperature", "")).strip() == CONFIRM_TAG:
        fields.append("temperature")
    if needs_time and not has_dur and str(s.get("time_estimate", "")).strip() == CONFIRM_TAG:
        fields.append("time / duration")
    return fields


def _relevant_missing(s: dict) -> int:
    """Count of genuinely-needed unfilled values (see _missing_fields)."""
    return len(_missing_fields(s))


def _bench_uncertainty_objs(proto: dict, step: dict) -> list:
    """Non-confirmed uncertainty objects for this step, worst-risk first."""
    reg = uncertainty_slots.registry(proto)
    sid = step.get("step_id")
    objs = [o for o in reg.values()
            if o.get("step_id") == sid
            and o["status"] not in uncertainty_slots.CONFIRMED
            and o["status"] != "not_applicable"]
    objs.sort(key=lambda o: ({"high": 0, "medium": 1, "low": 2}.get(o["risk_level"], 1),
                             0 if o["status"] == "conflict" else 1))
    return objs


def _bench_blocking(objs: list) -> list:
    """High-risk slots that should block completion: unresolved or conflicting."""
    return [o for o in objs if o["risk_level"] == "high" and o["status"] in ("unresolved", "conflict")]


def _fmt_range(s: dict) -> str:
    lo, hi, unit = s.get("low"), s.get("high"), s.get("unit", "")
    if lo is None:
        return "—"
    if lo == hi:
        return f"{lo} {unit}".strip()
    return f"{lo}–{hi} {unit}".strip()


def _render_value_suggestions(step: dict, key: str):
    """AI-suggested TYPICAL RANGES for a step's values (spin g-force by cell type/
    delicacy, PCR temps, ligation ratio, digest U/µg …). Explicitly advisory — ranges
    to confirm, never gold-standard values from the user's protocol."""
    with st.expander("Suggest typical values (ranges — confirm before use)", expanded=False):
        st.caption("Every value is tagged with where it comes from — no black box. "
                   "= auditable built-in rule (common practice, with reasoning shown)  ·  "
                   "= AI-proposed (verify)  ·  none of these are read from your protocol, "
                   "so confirm against your source/kit before bench use.")
        sk = f"valsugg_{key}"
        if st.button("Get typical-value suggestions", key=f"vs_btn_{key}"):
            lvl = (st.session_state.input_meta or {}).get("experience_level", "intermediate")
            with st.spinner("Suggesting typical ranges…"):
                st.session_state[sk] = SuggestAgent().suggest_step(step, "", lvl)
            st.rerun()
        res = st.session_state.get(sk)
        if res and res.get("suggestions"):
            badge = {"reference": "built-in rule", "ai": "AI — verify",
                     "source": "from your protocol"}
            for s in res["suggestions"]:
                tag = badge.get(s.get("source", "reference"), "built-in rule")
                typ = (f"  ·  _typical {s['typical']} {s.get('unit','')}_".rstrip()
                       if s.get("typical") not in (None, s.get("low")) else "")
                st.markdown(f"- **{s.get('label','')}** — {_fmt_range(s)}{typ}  &nbsp; `{tag}`")
                if s.get("rationale"):
                    st.caption(s["rationale"])
            for src in res.get("sources", []) or []:
                url = src.get("url") if isinstance(src, dict) else str(src)
                if url:
                    st.caption(f"Source: {url}")
            if res.get("mode") == "offline":
                st.caption("These are auditable reference ranges. For AI-tailored additions, route "
                           "the **suggest** agent to a model in sidebar **Models · per-agent** — "
                           "they'll appear tagged so you always know what's a rule vs a guess.")
        elif res:
            st.caption("No typical-range match for this operation — enter the value from your source.")


def _looks_like_speed(v) -> bool:
    """True only for real centrifuge/shaker speeds — filters out junk that lands in
    the speed field (descriptive text, 'NA', a bare number, PCR cycling, etc.)."""
    v = str(v or "").lower()
    return bool(re.search(r"\d", v)) and any(
        u in v for u in ("x g", "×g", "xg", "rpm", "rcf", "g for", " g)"))


def _step_uses_item(step: dict, item: str) -> bool:
    if not item:
        return False
    txt = _step_text(step)
    toks = [t for t in re.split(r"[^a-z0-9]+", str(item).lower()) if len(t) > 3]
    return any(t in txt for t in toks) if toks else str(item).lower() in txt


def _field_propagated(proto: dict, getter) -> dict:
    """Count how many steps carry each value for a given field — values that repeat
    across many steps are usually mis-propagated from a combine/parse, not real."""
    counts: dict = {}
    for s in proto.get("workflow", []) or []:
        v = getter(s)
        if v:
            counts[v] = counts.get(v, 0) + 1
    return counts


def _relevant_reagents(proto: dict, step: dict) -> list:
    """Drop reagents that look mis-propagated: the same item appears on 2+ steps AND
    is never named in this step's title/instructions. Reagents unique to the step (or
    actually referenced in it) are always kept."""
    counts = {}
    for s in proto.get("workflow", []) or []:
        for r in s.get("reagents", []) or []:
            it = r.get("item", "")
            counts[it] = counts.get(it, 0) + 1
    out = []
    for r in step.get("reagents", []) or []:
        it = r.get("item", "")
        if counts.get(it, 0) >= 2 and not _step_uses_item(step, it):
            continue
        out.append(r)
    return out


def _relevant_other(proto: dict, step: dict) -> str:
    """Hide an 'other' condition that's repeated across steps and unreferenced here."""
    other = (step.get("conditions", {}) or {}).get("other", "")
    if not other:
        return ""
    counts = _field_propagated(proto, lambda s: (s.get("conditions", {}) or {}).get("other", ""))
    if counts.get(other, 0) >= 2 and not _step_uses_item(step, other):
        return ""
    return other


def _slot_display(proto: dict, slot_id: str):
    """Return (value, tag) for a slot: a confirmed tree value (no tag) or a registry
    SUGGESTION (recommended_candidate) with a short 'verify' tag, so the design page can
    show pre-filled suggestions inline without writing unconfirmed values into the tree."""
    o = uncertainty_slots.get(proto, slot_id)
    if not o:
        return None, None
    stt = o.get("status")
    if stt in uncertainty_slots.CONFIRMED:
        return _clean_val(o.get("current_value")), None
    if stt in uncertainty_slots.PARTIAL:
        tagmap = {"literature_supported": "lit · verify", "typical_range": "typical · verify",
                  "ai_suggested": "AI · verify"}
        return _clean_val(o.get("recommended_candidate")), tagmap.get(stt, "suggested · verify")
    return None, None


def _disp_amount(proto: dict, slot_id: str, fallback) -> str:
    """A displayable amount/concentration for a slot: confirmed/suggested value, else the
    tree value — blank for placeholders like '[confirm…]' or '(TBD …)'."""
    val, _ = _slot_display(proto, slot_id)
    val = val or _clean_val(fallback)
    return "" if (not val or str(val).startswith("(TBD")) else str(val)


def _step_reagents_for_display(proto: dict, step: dict):
    """Reagents to show for a step as (name, amount/conc): the reagents attached to the step,
    PLUS any global materials whose name is mentioned in the step text (so every step lists
    the reagents it uses even when the parser didn't attach them). Name + concentration only —
    vendor/catalog detail stays in the Materials table."""
    sid = step.get("step_id")
    out, seen = [], set()
    idx = {id(r): ri for ri, r in enumerate(step.get("reagents", []) or [])}
    for r in _relevant_reagents(proto, step):
        name = str(r.get("item", "reagent")).strip()
        if not name or name.lower() in seen:
            continue
        out.append((name, _disp_amount(proto, f"step:{sid}:reag:{idx.get(id(r), 0)}:amount",
                                       r.get("amount"))))
        seen.add(name.lower())
    for mi, m in enumerate(proto.get("materials", []) or []):
        name = str(m.get("item", "")).strip()
        if not name or name.lower() in seen or not _step_uses_item(step, name):
            continue
        out.append((name, _disp_amount(proto, f"mat:{mi}:amount", m.get("amount"))))
        seen.add(name.lower())
    return out


def _render_step_detail(s: dict):
    proto = st.session_state.get("protocol") or {}
    sid = s.get("step_id")
    cond = s.get("conditions", {}) or {}
    if s.get("purpose"):
        st.caption(s["purpose"])

    # conditions line — time / temperature / speed FIRST (at the top), each labelled so it's
    # unambiguous; only values that exist are shown (no '• n/a', no forced time).
    def _val_tag(tree_val, slot_id):
        tv = _clean_val(tree_val)
        if tv:
            return tv
        val, tag = _slot_display(proto, slot_id)
        return f"{val} _({tag})_" if val else ""

    bits = []
    t = _val_tag(s.get("time_estimate"), f"step:{sid}:time")
    if t:
        bits.append(f"**Time:** {t}")
    tp = _val_tag(cond.get("temperature"), f"step:{sid}:cond:temperature")
    if tp:
        bits.append(f"**Temp:** {tp}")
    if _looks_like_speed(cond.get("speed")):
        bits.append(f"**Speed:** {_clean_val(cond.get('speed'))}")
    else:
        sp = _val_tag("", f"step:{sid}:cond:speed")
        if sp:
            bits.append(f"**Speed:** {sp}")
    if bits:
        st.markdown(" · ".join(bits))

    st.markdown("**Instructions**")
    for i in s.get("instructions", []):
        st.write(f"- {i}")
    # reagents for THIS step — name + concentration/amount (products live in Materials table)
    reags = _step_reagents_for_display(proto, s)
    if reags:
        st.markdown("**Reagents**")
        for name, amt in reags:
            st.markdown(f"- **{name}**" + (f" — {amt}" if amt else ""))
    # only GENUINELY-unresolved slots remain a to-do; suggestions are shown above
    reg = uncertainty_slots.registry(proto)
    unresolved = [o for o in reg.values()
                  if str(o.get("slot_id", "")).startswith(f"step:{sid}:")
                  and o.get("status") in ("unresolved", "conflict")]
    if unresolved:
        names = ", ".join(sorted({o.get("field_name", "value") for o in unresolved}))
        st.warning(f"Still to confirm ({len(unresolved)}): {names}. "
                   "Use **Edit this step** below, or the **Fill** tab.")
        _render_value_suggestions(s, f"detail_{sid or 'x'}")
    if _clean_val(s.get("expected_observation")):
        st.write(f"**Expected:** {s['expected_observation']}")
    if _clean_val(s.get("checkpoint")):
        st.write(f"**Checkpoint:** {s['checkpoint']}")
    if s.get("pause_point"):
        st.info("Pause point")
    for hr in s.get("human_review_required", []) or []:
        st.warning(f"Human review: {hr}")
    for t in s.get("troubleshooting", []) or []:
        st.write(f"**If fails:** {t.get('problem','')} → {', '.join(t.get('actions', []))}")


# ---------------------------------------------------------------------- #
# Page F: Fill in missing details
# ---------------------------------------------------------------------- #
def page_fill():
    import pandas as pd

    proto = st.session_state.protocol
    if not proto:
        st.info("Generate or load a protocol first.")
        return
    hero("Fill in missing details",
         "Enter exact volumes, spin speeds, temperatures and times. Edits update the protocol in place.")

    n_confirm = count_confirm(proto)
    if n_confirm:
        c1, c2 = st.columns([3, 2])
        c1.warning(f"{n_confirm} value(s) still need filling.")
        if c2.button("Auto-resolve from source & kits", key="auto_resolve",
                     type="primary", use_container_width=True):
            with st.spinner("Resolving values from kits and the manufacturer's protocol…"):
                auto_resolve_confirms()
        if c2.button("Leave the rest blank (fill at the bench)", key="fill_later",
                     use_container_width=True):
            mark_fill_later()
        c1.caption("Custom reagents (in-house plasmids) and lot-specific values can be left to "
                   "fill during the experiment — they become editable '(TBD)' markers you "
                   "complete in Bench Mode.")
    else:
        st.success("No unconfirmed values remain. ")

    ar = st.session_state.pop("_auto_resolve_result", None)
    if ar:
        st.success(f"Filled {ar['filled']} value(s); {ar['remaining']} left.")
        if ar.get("demo"):
            st.caption("Demo mode filled from bundled kits only. For web-retrieved "
                       "manufacturer values + inference, run live (DEMO_MODE=false).")
        elif ar["remaining"] > 0:
            st.caption("Some values left depend on the kit format/version (e.g. ZymoPURE "
                       "spin vs vacuum) or are custom reagents. Add the format in the "
                       "**Context** box above and click **Suggest values with AI** again, "
                       "or fill them manually below.")
        for s in ar.get("sources", []) or []:
            url = s.get("url", "") if isinstance(s, dict) else str(s)
            title = s.get("title", url) if isinstance(s, dict) else url
            if url:
                st.markdown(f"- Source: [{title}]({url})")

    # --- Auto-fill from a commercial kit (non-destructive) ---
    # --- AI-assisted interactive fill ---
    with st.expander("AI-assisted fill — suggest values, then review & apply", expanded=False):
        slots = list_slots(proto)
        if not slots:
            st.caption("No unconfirmed quantitative fields to fill. ")
        else:
            st.caption(f"{len(slots)} field(s) need a value. The assistant proposes values; "
                       "you review and edit before applying. Nothing is changed until you click Apply.")
            # auto-detect multi-format kits and prompt for the format up front
            fmt_qs = detect_format_questions(proto)
            ctx_parts = []
            if fmt_qs:
                st.info("This kit comes in multiple formats/versions — pick yours so the "
                        "AI fills the **exact** values (not placeholders):")
                for q in fmt_qs:
                    ans = st.radio(q["question"], q["options"], key=f"fmt_{q['key']}",
                                   horizontal=True)
                    ctx_parts.append(f"{q['question']}: {ans}")
            manual = st.text_input(
                "More context for the AI (optional) — kit version, instrument, etc.",
                key="fill_context_manual",
                placeholder="e.g. NEB Monarch v2, Eppendorf 5424 rotor",
            )
            if manual.strip():
                ctx_parts.append(manual.strip())
            st.session_state.fill_context = "; ".join(ctx_parts)
            if st.session_state.fill_context:
                st.caption(f"AI context: _{st.session_state.fill_context}_")
            if st.button("Suggest values with AI", key="ai_fill_suggest"):
                with st.spinner("Fill Assistant: proposing values…"):
                    st.session_state.fill_suggestions = FillAgent().suggest(
                        proto, slots, st.session_state.fill_context,
                        source_text=st.session_state.get("raw_text", ""))
                log_event("fill_suggested",
                          {"mode": st.session_state.fill_suggestions.get("mode"),
                           "n": len(st.session_state.fill_suggestions.get("suggestions", {}))})
                st.rerun()

            res = st.session_state.fill_suggestions
            if res:
                if res.get("status") == "error":
                    st.error(f"Suggestion failed: {res.get('error')}")
                else:
                    if res.get("note"):
                        st.caption(res["note"])
                    srcs = res.get("sources", []) or []
                    if srcs:
                        st.markdown("**Sources** (manufacturer protocol):")
                        for s in srcs:
                            url = s.get("url", "") if isinstance(s, dict) else str(s)
                            title = s.get("title", url) if isinstance(s, dict) else url
                            st.markdown(f"- [{title}]({url})" if url else f"- {title}")
                    sugg = res.get("suggestions", {}) or {}
                    st.markdown(f"**{len(sugg)} suggestion(s)** — edit any value, untick to skip:")
                    sa1, sa2 = st.columns(2)
                    if sa1.button("Select all", key="ai_sel_all"):
                        for slot in slots:
                            st.session_state[f"aiacc_{slot['id']}"] = True
                        st.rerun()
                    if sa2.button("Clear all", key="ai_clear_all"):
                        for slot in slots:
                            st.session_state[f"aiacc_{slot['id']}"] = False
                        st.rerun()
                    with st.form("ai_fill_form"):
                        inputs = {}
                        for slot in slots:
                            sid = slot["id"]
                            suggested = sugg.get(sid, "")
                            default_acc = st.session_state.get(f"aiacc_{sid}", bool(suggested))
                            c1, c2 = st.columns([3, 1])
                            val = c1.text_input(slot["label"], suggested, key=f"aifill_{sid}")
                            acc = c2.checkbox("apply", value=default_acc, key=f"aiacc_{sid}")
                            inputs[sid] = (val, acc)
                        applied = st.form_submit_button("Apply accepted values", use_container_width=True)
                    if applied:
                        new = json.loads(json.dumps(proto))
                        vals = {sid: val.strip() for sid, (val, acc) in inputs.items()
                                if acc and val.strip()}
                        cnt = apply_values(new, vals)
                        st.session_state.protocol = new
                        if st.session_state.protocol_v1 and \
                                st.session_state.protocol_v1.get("protocol_version") == new.get("protocol_version"):
                            st.session_state.protocol_v1 = new
                        persist_protocol(new)
                        st.session_state.fill_suggestions = None
                        log_event("fill_applied", {"n": cnt})
                        st.success(f"Applied {cnt} value(s). Confirm against your source before bench use.")
                        st.rerun()

    # --- PCR designer: compute setup from primer sequences ---
    with st.expander("PCR designer — compute Tm / annealing / extension / reaction from primers"):
        st.caption("PCR setup is derivable, not a 'confirm with source' unknown. Enter your "
                   "documented primer sequences + the polymerase and it computes everything.")
        pc1, pc2 = st.columns(2)
        fseq = pc1.text_input("Forward primer (5'→3')", key="pcr_f")
        rseq = pc2.text_input("Reverse primer (5'→3')", key="pcr_r")
        pc3, pc4, pc5 = st.columns(3)
        amp = pc3.number_input("Amplicon size (bp)", min_value=50, value=1000, step=50, key="pcr_amp")
        pol = pc4.selectbox("Polymerase", polymerases(), key="pcr_pol")
        conc = pc5.number_input("Primer conc (µM)", min_value=0.05, value=0.5, step=0.05, key="pcr_conc")
        if st.button("Design PCR", key="pcr_design_btn"):
            st.session_state["_pcr"] = design_pcr(fseq, rseq, int(amp), pol, conc)
        d = st.session_state.get("_pcr")
        if d:
            if d.get("error"):
                st.error(d["error"])
            else:
                m = st.columns(4)
                m[0].metric("Tm F", f"{d['tm_forward']} °C")
                m[1].metric("Tm R", f"{d['tm_reverse']} °C")
                m[2].metric("Anneal", f"{d['annealing_C']} °C")
                m[3].metric("Extension", d["extension_time"])
                st.markdown("**Reaction (50 µL)**")
                st.table([{"Component": x["item"], "Amount": x["amount"]} for x in d["reaction"]])
                st.markdown("**Thermocycling**")
                for line in d["cycling"]:
                    st.write(f"- {line}")
                st.caption(d["note"])
                wf = proto.get("workflow", []) or []
                amap = {f"Step {s.get('step_number')} — {s.get('title')}": s.get("step_id") for s in wf}
                tgt = st.selectbox("Insert this design into step", list(amap.keys()), key="pcr_target")
                if st.button("Insert design into this step", key="pcr_insert"):
                    new = json.loads(json.dumps(proto))
                    step = next(s for s in new["workflow"] if s["step_id"] == amap[tgt])
                    step["instructions"] = design_to_instructions(d)
                    step.setdefault("conditions", {})["temperature"] = f"anneal {d['annealing_C']} °C"
                    step["reagents"] = d["reaction"]
                    if not step.get("time_estimate") or CONFIRM_TAG in str(step.get("time_estimate")):
                        step["time_estimate"] = "~1.5-2 h (thermocycler)"
                    st.session_state.protocol = new
                    persist_protocol(new)
                    st.session_state["_pcr"] = None
                    log_event("pcr_designed", {"step": amap[tgt], "anneal": d["annealing_C"]})
                    st.success("PCR design inserted into the step.")
                    st.rerun()

    # --- deterministic bench calculators ---
    with st.expander("Bench calculators — ligation, dilution, cell seeding"):
        tabs = st.tabs(["Ligation", "Dilution (C1V1=C2V2)", "Cell seeding"])
        with tabs[0]:
            l1, l2, l3, l4 = st.columns(4)
            v_ng = l1.number_input("Vector (ng)", min_value=0.0, value=50.0, key="lig_vng")
            v_bp = l2.number_input("Vector (bp)", min_value=0.0, value=5000.0, key="lig_vbp")
            i_bp = l3.number_input("Insert (bp)", min_value=0.0, value=1000.0, key="lig_ibp")
            ratio = l4.number_input("Insert:Vector ratio", min_value=0.1, value=3.0, step=0.5, key="lig_r")
            if st.button("Calculate insert ng", key="lig_btn"):
                r = ligation_insert_ng(v_ng, v_bp, i_bp, ratio)
                if r.get("error"):
                    st.error(r["error"])
                else:
                    st.metric("Insert to use", f"{r['insert_ng']} ng")
                    st.caption(r["explain"])
        with tabs[1]:
            st.caption("Leave exactly ONE field blank to solve for it.")
            d1, d2, d3, d4 = st.columns(4)
            c1 = d1.text_input("C1 (stock conc)", key="dil_c1")
            v1 = d2.text_input("V1 (stock vol)", key="dil_v1")
            c2 = d3.text_input("C2 (final conc)", key="dil_c2")
            v2 = d4.text_input("V2 (final vol)", key="dil_v2")
            if st.button("Solve", key="dil_btn"):
                r = dilution(c1 or None, v1 or None, c2 or None, v2 or None)
                if r.get("error"):
                    st.error(r["error"])
                else:
                    st.metric(r["field"], r["result"])
                    st.caption(r["explain"])
        with tabs[2]:
            s1, s2, s3, s4 = st.columns(4)
            dens = s1.number_input("Cells per well", min_value=1.0, value=200000.0, step=1000.0, key="seed_d")
            vol = s2.number_input("Volume/well (µL)", min_value=1.0, value=200.0, key="seed_v")
            nw = s3.number_input("# wells", min_value=1, value=12, key="seed_n")
            stock = s4.number_input("Stock (cells/mL)", min_value=1.0, value=1000000.0, step=10000.0, key="seed_s")
            if st.button("Calculate seeding", key="seed_btn"):
                r = cell_seeding(dens, vol, int(nw), stock)
                if r.get("error"):
                    st.error(r["error"])
                else:
                    mc = st.columns(3)
                    mc[0].metric("Total cells", f"{r['total_cells_needed']:,}")
                    mc[1].metric("Stock to add", f"{r['stock_to_add_uL']} µL")
                    mc[2].metric("Medium to add", f"{r['medium_to_add_uL']} µL")
                    if r.get("warning") and "undiluted" not in r["warning"]:
                        st.warning(r["warning"])
                    elif r.get("warning"):
                        st.info(r["warning"])
                    st.caption(r["explain"])

    with st.expander("Auto-fill missing values from commercial kit(s)", expanded=False):
        kits = list_kits()
        if kits:
            opts = {f"{k['title']} — {k['vendor']}": k["id"] for k in kits}
            picks = st.multiselect(
                "Kit(s) — applied in order; each fills only the values still missing",
                list(opts.keys()), key="kit_pick_fill",
            )
            for p in picks:
                prov = next((k.get("provenance", "") for k in kits if k["id"] == opts[p]), "")
                if prov:
                    st.caption(f"• {p}: {prov}")
            if st.button("Fill missing values from selected kit(s)", key="apply_kit_fill",
                         disabled=not picks):
                running = proto
                all_changes = []
                for p in picks:
                    running, changes = apply_kit(running, get_kit(opts[p]))
                    all_changes.extend(f"[{p.split(' — ')[0]}] {c}" for c in changes)
                st.session_state.protocol = running
                if st.session_state.protocol_v1 and \
                        st.session_state.protocol_v1.get("protocol_version") == running.get("protocol_version"):
                    st.session_state.protocol_v1 = running
                persist_protocol(running)
                log_event("kits_applied", {"kits": [opts[p] for p in picks], "changes": len(all_changes)})
                if all_changes:
                    st.success(f"Filled {len(all_changes)} field(s) from {len(picks)} kit(s).")
                    with st.expander("What changed", expanded=True):
                        for c in all_changes:
                            st.write(f"- {c}")
                else:
                    st.info("Nothing to fill — no matching unconfirmed fields.")
                st.rerun()
        else:
            st.caption("No kits available.")

    st.divider()

    # --- Manual editor (everything in one form) ---
    def _mark(v):
        return "" if (isinstance(v, str) and CONFIRM_TAG in v) else v

    with st.form("fill_form"):
        st.subheader("Materials")
        mat_df = pd.DataFrame(proto.get("materials", []) or [])
        if mat_df.empty:
            mat_df = pd.DataFrame(columns=["item", "vendor", "catalog_number", "amount", "required", "notes"])
        mat_df = mat_df.replace(CONFIRM_TAG, "")
        edited_mats = st.data_editor(
            mat_df, num_rows="dynamic", use_container_width=True, key="mat_editor"
        )

        st.subheader("Per-step settings & reagents")
        step_inputs = {}
        for s in proto.get("workflow", []) or []:
            sid = s["step_id"]
            cond = s.get("conditions", {}) or {}
            with st.expander(f"Step {s.get('step_number')} — {s.get('title')}", expanded=False):
                c1, c2, c3 = st.columns(3)
                t = c1.text_input("Time estimate", _mark(s.get("time_estimate", "")), key=f"time_{sid}")
                temp = c2.text_input("Temperature", _mark(cond.get("temperature", "")), key=f"temp_{sid}")
                spd = c3.text_input("Speed (xg / rpm)", _mark(cond.get("speed", "")), key=f"spd_{sid}")
                other = st.text_input("Other condition", _mark(cond.get("other", "")), key=f"oth_{sid}")
                reag_df = pd.DataFrame(s.get("reagents", []) or [])
                if reag_df.empty:
                    reag_df = pd.DataFrame(columns=["item", "amount"])
                reag_df = reag_df.replace(CONFIRM_TAG, "")
                reag_edit = st.data_editor(
                    reag_df, num_rows="dynamic", use_container_width=True, key=f"reag_{sid}",
                )
                instr = st.text_area(
                    "Instructions (one per line)",
                    "\n".join(s.get("instructions", []) or []),
                    key=f"instr_{sid}", height=120,
                )
                step_inputs[sid] = {
                    "time_estimate": t, "temperature": temp, "speed": spd,
                    "other": other, "reagents": reag_edit, "instructions": instr,
                }

        submitted = st.form_submit_button("Save all details", use_container_width=True)

    if submitted:
        new_proto = json.loads(json.dumps(proto))  # deep copy
        # materials
        try:
            new_proto["materials"] = [
                {k: ("" if v is None else v) for k, v in row.items()}
                for row in edited_mats.to_dict("records")
            ]
        except Exception:
            pass
        # steps
        for s in new_proto.get("workflow", []) or []:
            sid = s["step_id"]
            inp = step_inputs.get(sid)
            if not inp:
                continue
            if inp["time_estimate"].strip():
                s["time_estimate"] = inp["time_estimate"].strip()
            s.setdefault("conditions", {})
            for fld, key in (("temperature", "temperature"), ("speed", "speed"), ("other", "other")):
                if inp[key].strip():
                    s["conditions"][fld] = inp[key].strip()
            instr_lines = [l.strip() for l in inp["instructions"].split("\n") if l.strip()]
            if instr_lines:
                s["instructions"] = instr_lines
            try:
                reag = [
                    {"item": r.get("item", ""), "amount": r.get("amount", "")}
                    for r in inp["reagents"].to_dict("records")
                    if str(r.get("item", "")).strip()
                ]
                s["reagents"] = reag
            except Exception:
                pass
        st.session_state.protocol = new_proto
        if st.session_state.protocol_v1 and \
                st.session_state.protocol_v1.get("protocol_version") == new_proto.get("protocol_version"):
            st.session_state.protocol_v1 = new_proto
        persist_protocol(new_proto)
        log_event("details_filled", {"remaining_confirm": count_confirm(new_proto)})
        st.success("Saved. Protocol updated in place and artifacts re-written.")
        st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Back to protocol", use_container_width=True):
            st.session_state.page = "protocol"
            st.rerun()
    with c2:
        if st.button("▶ Go to Bench Mode", use_container_width=True, type="primary"):
            st.session_state.page = "bench"
            st.rerun()


# ---------------------------------------------------------------------- #
# Page G: Plan by day / session
# ---------------------------------------------------------------------- #
# ====================================================================== #
# Page: Route discovery (route uncertainty — choose the workflow first)
# ====================================================================== #
# --- readable status iconography: small inline SVG + text, no emoji ---------- #
_RISK_COLOR = {"high": "#DC2626", "medium": "#F59E0B", "low": "#9CA3AF"}
_RISK_WORD = {"high": "High risk", "medium": "Medium", "low": "Low"}
_BLOCK_WORD = {"must_ask_before_generation": "Must choose",
               "can_branch_and_continue": "Branchable", "can_fill_later": "Optional"}
_BLOCK_COLOR = {"must_ask_before_generation": "#DC2626",
                "can_branch_and_continue": "#F59E0B", "can_fill_later": "#9CA3AF"}


def _dot_svg(color: str, size: int = 9) -> str:
    r = size / 2
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'style="vertical-align:middle;margin-right:5px">'
            f'<circle cx="{r}" cy="{r}" r="{r}" fill="{color}"/></svg>')


def _risk_word(level: str) -> str:
    """Plain text for expander titles (Streamlit expanders don't render HTML)."""
    return _RISK_WORD.get(level, str(level).title())


def _risk_md(level: str) -> str:
    """HTML badge (dot + word) for st.markdown(unsafe_allow_html=True) contexts."""
    return f'{_dot_svg(_RISK_COLOR.get(level, "#9CA3AF"))}<b>{_risk_word(level)}</b>'


def _block_word(level: str) -> str:
    return _BLOCK_WORD.get(level, "Optional")


# value-provenance badge: source / user / suggested_default / needs_confirmation / N-A
_VALUE_STATUS = {
    "source_confirmed": ("Source value", "#16A34A"),
    "kit_confirmed": ("Kit value", "#16A34A"),
    "calculated": ("Calculated", "#16A34A"),
    "literature_supported": ("Literature", "#6D5BD0"),
    "user_confirmed": ("You confirmed", "#16A34A"),
    "typical_range": ("Suggested default", "#6D5BD0"),
    "ai_suggested": ("Suggested default (AI)", "#6D5BD0"),
    "unresolved": ("Needs confirmation", "#D97706"),
    "conflict": ("Conflict", "#DC2626"),
    "not_applicable": ("Not applicable", "#6B7280"),
}


def _conf_word(c) -> str:
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "low"
    return "high" if c >= 0.8 else ("medium" if c >= 0.4 else "low")


def _value_status_badge(obj: dict) -> str:
    label, color = _VALUE_STATUS.get(obj.get("status"), ("Needs confirmation", "#D97706"))
    if obj.get("legacy_imported"):
        label += " · legacy"
    conf = _conf_word(obj.get("confidence", 0))
    return (f'<span style="background:{color}1A;color:{color};border:1px solid {color}55;'
            f'border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:700">{label}</span>'
            f'<span style="color:#6B7280;font-size:11.5px;margin-left:7px">confidence {conf}</span>')


def _route_holder():
    """Where route_question objects live: the built protocol if present, else a
    session-only holder used during pre-generation route discovery."""
    return st.session_state.get("protocol") or st.session_state.setdefault("route_holder", {})


def _agent_rq_to_hits(res: dict) -> list:
    """Adapt ContextDigestAgent output (live or demo) into route_questions hits."""
    hits = []
    for q in res.get("route_questions", []) or []:
        hits.append({
            "surface_phrase": q.get("ambiguous_phrase") or q.get("surface_phrase", ""),
            "route_family": q.get("route_family", ""),
            "ambiguity_type": q.get("ambiguity_type", ""),
            "route_question": q.get("question") or q.get("route_question", ""),
            "blocking_level": q.get("blocking_level", "can_fill_later"),
            "match_confidence": q.get("match_confidence", 0.0),
            "why_matched": q.get("why_needed", ""),
            "step_id": q.get("step_id"),
            "source": q.get("source", "context_digest"),
            "routes": [{"route_id": o.get("option_id", ""), "label": o.get("label", ""),
                        "when_to_use": o.get("when_to_use", ""),
                        "route_summary": o.get("route_summary", []),
                        "creates_value_uncertainties": o.get("creates_value_uncertainties", []),
                        "risk_if_wrong": o.get("risk_if_wrong", "")}
                       for o in q.get("options", []) or []],
        })
    return hits


def _route_selections() -> list:
    """Selected routes (for feeding ProtocolAgent generation context)."""
    holder = _route_holder()
    out = []
    for o in route_questions.registry(holder).values():
        if o.get("status") == "selected":
            r = route_questions.selected_route(o) or {}
            out.append({"phrase": o.get("surface_phrase"), "chosen_route": r.get("label"),
                        "route_id": o.get("selected_option"), "route_summary": r.get("route_summary", [])})
    return out


def page_digest():
    hero("Route discovery",
         "Many bench phrases ('plate cells', 'clean up reaction') hide several real "
         "workflows. Choose the route first; missing values are filled later.")
    proto = st.session_state.get("protocol")
    holder = _route_holder()

    if st.button("Discover routes", type="primary", key="run_digest"):
        with st.spinner("Context Digest Agent: finding hidden route choices…"):
            if proto and proto.get("workflow"):
                res = ContextDigestAgent().digest(protocol=proto)
            else:
                docs = st.session_state.get("parsed_docs") or []
                goal = (st.session_state.input_meta or {}).get("goal", "") or ""
                text = " ".join((d.get("summary", "") or "") + " "
                                + " ".join(_li_text(s) for s in (d.get("major_steps", []) or []))
                                for d in docs)
                text = ((goal + ". " if goal else "") + text + " "
                        + (st.session_state.get("raw_text", "") or ""))[:6000]
                res = ContextDigestAgent().digest(text=text, context={"goal": goal})
        route_questions.build_from_hits(holder, _agent_rq_to_hits(res))
        if proto is not None:
            persist_protocol(proto)
        log_event("route_discovery", route_questions.summary(holder))
        st.rerun()

    reg = route_questions.registry(holder)
    if not reg:
        st.caption("Run discovery to detect route-ambiguous phrases in your protocol "
                   "or request. Executable steps (e.g. 'incubate at 37 C') won't trigger.")
        return

    summ = route_questions.summary(holder)
    metric_cards([
        ("Route choices", str(summ["total"])),
        ("Chosen", str(summ["selected"])),
        ("Blocking open", str(summ["blocking_open"]), "must choose before generating"),
    ])
    if summ["blocking_open"]:
        st.warning(f"{summ['blocking_open']} blocking route choice(s) needed before generating "
                   "the protocol.")
    else:
        st.success("All blocking route choices made — safe to generate the protocol.")

    email = _user_email()
    order = sorted(reg.values(), key=lambda o: (
        0 if o["blocking_level"] == "must_ask_before_generation" else 1,
        o["status"] != "needs_user_choice"))
    for o in order:
        if o["status"] == "dismissed":
            continue
        qid = o["question_id"]
        exp = o["status"] == "needs_user_choice" and o["blocking_level"] == "must_ask_before_generation"
        with st.expander(f"[{_block_word(o['blocking_level'])}] {o['question']}  ·  ({o['ambiguity_type']})", expanded=exp):
            st.caption(f"Phrase: \"{o['surface_phrase']}\"" + (f"  ·  {o['why_needed']}" if o.get("why_needed") else ""))
            if o["status"] == "selected":
                chosen = route_questions.selected_route(o) or {}
                st.success(f"Chosen route: **{chosen.get('label','')}**")
                if chosen.get("route_summary"):
                    st.caption("Steps: " + " → ".join(chosen["route_summary"]))
                if st.button("Change choice", key=f"rqchg_{qid}"):
                    o["status"] = "needs_user_choice"; o["selected_option"] = None
                    if proto is not None:
                        persist_protocol(proto)
                    st.rerun()
            else:
                labels = [opt["label"] for opt in o["options"]]
                ids = [opt["option_id"] for opt in o["options"]]
                if not labels:
                    st.caption("No route options were proposed.")
                    continue
                pick = st.radio("Choose the route", range(len(labels)),
                                format_func=lambda i: labels[i], key=f"rqpick_{qid}")
                opt = o["options"][pick]
                if opt.get("when_to_use"):
                    st.caption(f"When to use: {opt['when_to_use']}")
                if opt.get("route_summary"):
                    st.caption("Route: " + " → ".join(opt["route_summary"]))
                if opt.get("risk_if_wrong"):
                    st.warning(f"Risk if wrong: {opt['risk_if_wrong']}")
                cc = st.columns(2)
                if cc[0].button("Select route", key=f"rqsel_{qid}", type="primary"):
                    route_questions.select_option(holder, qid, ids[pick], email)
                    if proto is not None:
                        persist_protocol(proto)
                    log_event("route_selected", {"question_id": qid, "route": ids[pick]})
                    st.rerun()
                if cc[1].button("Not ambiguous — dismiss", key=f"rqdis_{qid}"):
                    route_questions.dismiss(holder, qid, email)
                    if proto is not None:
                        persist_protocol(proto)
                    st.rerun()
            with st.popover("Audit trail"):
                for e in (o.get("audit_trail") or [])[-8:]:
                    st.caption(f"{e['ts'][:16]} · {e['actor']} · {e.get('from_status')}→{e.get('to_status')} · {e.get('value') or ''}")

    st.divider()
    if route_questions.safe_to_generate(holder):
        nxt = "protocol" if proto else "parsed"
        if st.button("Continue →", type="primary", key="digest_continue"):
            st.session_state.page = nxt
            st.rerun()


# ====================================================================== #
# Page F2: Resolve missing values (active uncertainty layer)
# ====================================================================== #
_STATUS_LABEL = {
    "source_confirmed": "Source-confirmed", "kit_confirmed": "Kit-confirmed",
    "calculated": "Calculated", "user_confirmed": "You confirmed",
    "literature_supported": "Literature", "typical_range": "Typical range",
    "ai_suggested": "AI suggestion", "unresolved": "Unresolved",
    "conflict": "CONFLICT", "not_applicable": "Not applicable",
}
_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
_TYPE_RE_MAP = {"volume": _VOLUME, "mass": _MASS, "temperature": _TEMP,
                "speed": _SPEED, "time": _TIME}


def _user_email() -> str:
    return st.session_state.get("user_email") or "lab-user"


def _slot_step(proto: dict, obj: dict) -> dict:
    for s in proto.get("workflow", []) or []:
        if s.get("step_id") == obj.get("step_id"):
            return s
    return {}


def _slot_step_text(proto: dict, obj: dict) -> str:
    s = _slot_step(proto, obj)
    return _step_text(s) if s else (proto.get("protocol_title", "") or "")


def _context_terms(obj: dict, proto: dict) -> set:
    s = _slot_step(proto, obj)
    base = re.split(r"[^a-z0-9]+", _step_text(s).lower()) if s else []
    return {t for t in base if len(t) >= 4}


def _resolve_sources() -> dict:
    """Bundle the evidence sources available this session for evidence_resolver."""
    return {
        "source_text": st.session_state.get("raw_text", "") or "",
        "parsed_docs": st.session_state.get("parsed_docs", []) or [],
        "reference_text": st.session_state.get("reference_text", "") or "",
    }


def _knowledge_broker():
    """Build a live KnowledgeBroker when the user has opted in (default off, so the
    MVP is unchanged). Sources: the user's UPLOADED manuals/docs (ToS-safe) + PubMed
    (public NCBI API). Manufacturer sites are NOT scraped."""
    if not st.session_state.get("knowledge_enabled"):
        return None
    try:
        import knowledge_sources as ks
        from knowledge_sources import base_provider as _bp
        from knowledge_sources.pdf_manual_provider import PDFManualProvider
        from knowledge_sources.pubmed_provider import PubMedProvider
        from knowledge_sources.uniprot_provider import UniProtProvider
        from knowledge_sources.ensembl_provider import EnsemblProvider
        from knowledge_sources.chembl_provider import ChEMBLProvider
    except Exception:
        return None
    _bp.NETWORK_ENABLED = True                       # user opted in to live retrieval
    manuals = PDFManualProvider()
    for d in (st.session_state.get("source_docs", []) or []):
        if d.get("text"):
            manuals.add_manual(d["text"], title=d.get("title", d.get("name", "manual")),
                               product=d.get("title", ""))
    providers = [manuals, PubMedProvider(email=(st.session_state.get("user_email") or "lab@local")),
                 UniProtProvider(), EnsemblProvider(), ChEMBLProvider()]
    return ks.KnowledgeBroker(providers=providers, enabled=True)


def _evidence_chip(obj: dict) -> str:
    st_ = obj.get("status")
    chip = _STATUS_LABEL.get(st_, st_)
    if obj.get("legacy_imported"):
        chip += " · legacy"
    if obj.get("source_name"):
        chip += f" · {obj['source_name']}"
    return chip


def _resolve_persist(proto: dict, slot_id: str, action: str, value=None):
    persist_protocol(proto)
    log_event("value_resolved", {"slot_id": slot_id, "action": action, "value": value})


def page_resolve():
    proto = st.session_state.protocol
    if not proto:
        st.info("Build a protocol first.")
        return
    reg = uncertainty_slots.enumerate_slots(proto)   # idempotent refresh
    hero("Resolve missing values",
         "Confirm uncertain values with evidence. AI may suggest — only you, your "
         "source, kit, or a calculation make a value count.")

    objs = [o for o in reg.values()]
    counted = [o for o in objs if o["status"] != "not_applicable"]
    n_unres = sum(1 for o in counted if o["status"] == "unresolved")
    n_conf = sum(1 for o in counted if o["status"] in uncertainty_slots.CONFIRMED)
    n_guess = sum(1 for o in counted if o["status"] in ("ai_suggested", "typical_range"))
    n_conflict = sum(1 for o in counted if o["status"] == "conflict")
    n_legacy = uncertainty_slots.legacy_imported_count(proto)

    metric_cards([
        ("To resolve", str(n_unres + n_conflict), "unresolved + conflicts"),
        ("Evidence-confirmed", str(n_conf)),
        ("AI / typical only", str(n_guess)),
        ("Conflicts", str(n_conflict)),
    ])
    if n_legacy:
        st.info(f"{n_legacy} legacy value(s) were imported as **you-confirmed** (no source "
                f"quote on record). Filter to *You confirmed · legacy* below to review them.")

    # ---- bulk auto-resolve: let the agent answer what it can, so you only see
    #      the few flags that truly need a human -------------------------------
    if st.session_state.get("_resolve_flash"):
        st.success(st.session_state.pop("_resolve_flash"))
    st.session_state.knowledge_enabled = st.toggle(
        "Use knowledge sources (your uploaded manuals + PubMed)",
        value=st.session_state.get("knowledge_enabled", False),
        help="Opt-in live retrieval: searches your UPLOADED kit manuals/docs and PubMed "
             "(public NCBI API) for cited values. Manufacturer sites are never scraped.")
    ar1, ar2 = st.columns([3, 2])
    ar1.caption("Don't hand-answer every flag. Auto-resolve confirms what your source, "
                "kit, knowledge sources, or a calculation already prove, and proposes typical "
                "ranges for the rest — leaving you only the genuinely unknown, high-risk values.")
    if ar2.button("Auto-fill all (evidence · defaults · AI)", type="primary", key="bulk_autoresolve",
                  help="Pass 1 deterministic: source/kit/knowledge/calc -> confirmed (cited), then "
                       "standard defaults + typical ranges. Pass 2: AI proposes the long tail as "
                       "labeled suggestions. Vendor/catalog are never invented."):
        with st.spinner("Auto-filling values (evidence · defaults · AI · consistency)…"):
            r = run_bulk_autofill(proto, broker=_knowledge_broker(), srcs=_resolve_sources())
        st.session_state["_resolve_flash"] = (
            f"Filled {r['evidence']} from evidence, {r['catalog']} standard defaults, "
            f"{r['typical']} typical, {r['ai']} AI suggestions (incl. consistent vendor/kit); "
            f"aligned {r['consistency']} for consistency. {r['still']} still need you "
            "(high-risk + anything unverifiable).")
        st.rerun()

    # ---- triage: let the AI decision-tree retire flags that don't apply to
    #      their step (e.g. a centrifuge speed on a plating step) --------------
    tr1, tr2 = st.columns([3, 2])
    tr1.caption("Some flags are schema artifacts — a value the step never uses (a spin "
                "speed on a plating step). Triage runs a decision tree that retires those "
                "as Not-applicable, with a reason and an audit trail, so you don't answer them.")
    if tr2.button("Triage flags (retire what doesn't apply)", key="bulk_triage",
                  help="Decision tree decides if each condition actually applies to its step; "
                       "clearly-inapplicable ones are marked N/A (reversible, audited)."):
        with st.spinner("Slot Triage Agent: deciding what applies…"):
            res = SlotTriageAgent().triage(proto)
        n_na = 0
        for sid, d in (res.get("decisions", {}) or {}).items():
            if d.get("decision") == "not_applicable" and d.get("auto_safe"):
                ob = uncertainty_slots.get(proto, sid)
                if ob and ob.get("status") == "unresolved":
                    value_promoter.mark_not_applicable(proto, sid, _user_email())
                    ob["audit_trail"][-1]["note"] = "triage: " + d.get("reason", "not applicable")
                    n_na += 1
        persist_protocol(proto)
        log_event("slot_triage", {"marked_na": n_na, "mode": res.get("mode")})
        st.session_state["_resolve_flash"] = (
            f"Triage retired {n_na} flag(s) as Not-applicable (the step doesn't use that value). "
            "Each is reversible — change its Status filter to *Not applicable* to review.")
        st.rerun()

    # per-slot applicability hints (deterministic tree, for inline guidance)
    _triage_map = {t["slot_id"]: t for t in slot_triage.triage_protocol(proto)}

    # filters
    fc1, fc2 = st.columns(2)
    f_risk = fc1.multiselect("Risk", ["high", "medium", "low"], default=["high", "medium", "low"])
    f_status = fc2.multiselect("Status", list(_STATUS_LABEL.keys()),
                               default=["unresolved", "conflict", "ai_suggested", "typical_range"])
    rows = [o for o in counted if o["risk_level"] in f_risk and o["status"] in f_status]
    rows.sort(key=lambda o: (_RISK_ORDER.get(o["risk_level"], 1),
                             0 if o["status"] == "conflict" else 1, o["slot_id"]))

    if not rows:
        st.success("Nothing matches the current filter.")
        return

    email = _user_email()
    for o in rows:
        sid = o["slot_id"]
        head = (f"[{_risk_word(o['risk_level'])}] {o.get('step_id') or 'material'} · "
                f"{o['field_name']} ({o['expected_type']}) — {_STATUS_LABEL.get(o['status'], o['status'])}")
        with st.expander(head, expanded=(o["risk_level"] == "high" and o["status"] in ("unresolved", "conflict"))):
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"**Current in protocol:** `{o.get('current_value')}`")
            c1.markdown(_value_status_badge(o), unsafe_allow_html=True)
            if o.get("source_name"):
                c1.caption(f"From: {o['source_name']}")
            _loc = o.get("source_location")
            if isinstance(_loc, dict):
                _cit = " · ".join(str(v) for v in (
                    _loc.get("company"), _loc.get("product"), _loc.get("catalog_number"),
                    _loc.get("document_version")) if v)
                if _cit:
                    c1.caption(f"Citation: {_cit}")
                if _loc.get("url"):
                    c1.caption(_loc["url"])
            if o.get("recommended_candidate"):
                c2.markdown(f"**Best candidate:** {o['recommended_candidate']}")
            if o.get("source_quote"):
                c1.caption(f"“{o['source_quote'][:160]}”")
            if o["risk_level"] == "high":
                st.warning(f"High risk — {o['risk_if_wrong']}")
            if o["status"] == "conflict":
                st.error("Sources disagree. Enter the correct value and Accept to resolve.")
            _tr = _triage_map.get(sid)
            if _tr and _tr["decision"] == "not_applicable":
                st.info(f"Likely **not applicable**: {_tr['reason']} → consider **Mark N/A**.")

            # ---- propose a default so the user CONFIRMS instead of answering cold ----
            prefill = o.get("recommended_candidate") or (
                o.get("current_value") if uncertainty_slots._looks_filled(o.get("current_value")) else "")
            _auto = []
            if not prefill and o["status"] == "unresolved":
                _auto = suggest_value.typical_candidates(proto, o)
                if _auto:
                    prefill = _auto[0]["value"]
            # explain what to enter (the #1 "I don't know what to answer" fix)
            if _auto:
                _why = _auto[0].get("evidence", {}).get("rationale", "")
                st.markdown(f"**Suggested answer:** `{prefill}`  "
                            + (f"— {_why}" if _why else "") )
                st.caption("This is a typical-practice range (not from your protocol). "
                           "Accept to record it as YOUR confirmation, or edit it.")
            elif not prefill:
                st.caption(f"No value found in your source, kit, or typical-practice tables. "
                           f"What to do: enter your value below, click **AI suggest** for a model "
                           f"proposal, **Search source** again, or — if this step has no real "
                           f"{o['expected_type']} — click **Mark N/A**.")
            _ph = {"speed": "e.g. 4000 x g", "temperature": "e.g. 37 C", "time": "e.g. 10 min",
                   "material_amount": "e.g. 200 µL", "concentration": "e.g. 10 ng/µL",
                   "volume": "e.g. 200 µL", "mass": "e.g. 5 µg", "cell_number": "e.g. 1e6 cells"}
            val = st.text_input("Value to confirm", value=str(prefill or ""),
                                key=f"resval_{sid}",
                                placeholder=_ph.get(o["expected_type"], "enter the value"))

            _suggestable = o["expected_type"] not in uncertainty_slots.NON_SUGGESTABLE_TYPES
            b = st.columns(7)
            if b[0].button("Accept", key=f"acc_{sid}", type="primary",
                           help="Record YOUR confirmation of this value"):
                if val.strip():
                    value_promoter.user_confirm(proto, sid, val.strip(), email)
                    _resolve_persist(proto, sid, "user_confirm", val.strip())
                    st.rerun()
                else:
                    st.warning("Enter a value first.")
            if b[1].button("Search source", key=f"src_{sid}",
                           help="Search uploaded source / parsed docs / kit library / knowledge sources"):
                prop = evidence_resolver.best_proposal(o, proto, _resolve_sources(),
                                                       broker=_knowledge_broker())
                if prop:
                    value_promoter.auto_resolve(proto, sid, prop)
                    _resolve_persist(proto, sid, f"evidence:{prop['proposed_status']}", prop["value"])
                    st.rerun()
                else:
                    st.info("No exact value found in your source, parsed docs, or kit library.")
            if b[2].button("Use typical range", key=f"typ_{sid}", disabled=not _suggestable,
                           help="Apply a typical range from common practice (stays unconfirmed)"):
                cands = suggest_value.typical_candidates(proto, o)
                if cands:
                    value_promoter.auto_resolve(proto, sid, cands[0])
                    o2 = uncertainty_slots.get(proto, sid)
                    o2.setdefault("candidate_values", []).extend(cands)
                    _resolve_persist(proto, sid, "typical_range", cands[0]["value"])
                    st.rerun()
                else:
                    st.info("No built-in typical range matches this field.")
            if b[3].button("AI suggest", key=f"ai_{sid}", disabled=not _suggestable,
                           help="Ask the Fill agent for a likely value (stays AI-suggested, unconfirmed)"):
                prop = suggest_value.ai_candidate(proto, o, FillAgent(),
                                                  context=st.session_state.get("fill_context", ""),
                                                  source_text=st.session_state.get("raw_text", ""))
                if prop:
                    value_promoter.auto_resolve(proto, sid, prop)
                    uncertainty_slots.get(proto, sid).setdefault("candidate_values", []).append(prop)
                    _resolve_persist(proto, sid, "ai_suggested", prop["value"])
                    st.rerun()
                else:
                    st.info("The AI did not return a usable suggestion for this field.")
            if b[4].button("Open calculator", key=f"calc_{sid}",
                           help="Calculators live on the Fill page"):
                st.session_state.page = "fill"
                st.rerun()
            if b[5].button("Keep unresolved", key=f"keep_{sid}"):
                value_promoter.keep_unresolved(proto, sid, email)
                _resolve_persist(proto, sid, "keep_unresolved")
                st.rerun()
            if b[6].button("Mark N/A", key=f"na_{sid}",
                           help="This value does not apply to this protocol"):
                value_promoter.mark_not_applicable(proto, sid, email)
                _resolve_persist(proto, sid, "not_applicable")
                st.rerun()

            with st.popover("Audit trail"):
                for e in (o.get("audit_trail") or [])[-10:]:
                    st.caption(f"{e['ts'][:16]} · {e['actor']} · "
                               f"{e.get('from_status')}→{e.get('to_status')} · {e.get('value') or ''}")


def _retire_inapplicable_conditions(proto: dict) -> int:
    """Mark N/A any condition slot (speed/temperature) the deterministic tree is sure the
    step doesn't use — a spin speed on a plating step, a temperature on a non-thermal step.
    Runs before/independent of filling so we never suggest a value the step can't use, and
    cleans up any already-suggested ones. Confirmed values are never touched. Idempotent."""
    n = 0
    for t in slot_triage.triage_protocol(proto, only_unresolved=False):
        if not (t["decision"] == "not_applicable" and t["auto_safe"]):
            continue
        ob = uncertainty_slots.get(proto, t["slot_id"])
        if ob and ob.get("status") not in uncertainty_slots.CONFIRMED \
                and ob.get("status") != "not_applicable":
            value_promoter.mark_not_applicable(proto, t["slot_id"], _user_email())
            if ob.get("audit_trail"):
                ob["audit_trail"][-1]["note"] = "triage: " + t.get("reason", "not applicable")
            n += 1
    return n


def page_parse_routes():
    """Combined tab: parsed documents + route discovery (phrase + route together)."""
    t1, t2 = st.tabs(["Parsed documents", "Route discovery"])
    with t1:
        page_parsed()
    with t2:
        page_digest()


def run_bulk_autofill(proto: dict, broker=None, srcs=None, with_ai: bool = True) -> dict:
    """Fill every unresolved slot, UI-free so it can run on page load:
      pass 1 — deterministic ladder (evidence → catalog → typical),
      pass 2 — ONE batched AI call for the long tail (labeled suggestions),
      pass 3 — cross-step consistency alignment.
    Confirmed values are written to the tree; suggestions stay in the registry (labeled).
    Returns counts. Mirrors the Resolve tab's 'Auto-fill all' so both share one engine."""
    reg = uncertainty_slots.registry(proto)
    srcs = srcs if srcs is not None else _resolve_sources()
    n_na = _retire_inapplicable_conditions(proto)   # pass 0
    # pass 0.5 — correct obviously-wrong KNOWN-reagent values (e.g. polybrene as a bare volume)
    # by resetting them so the known-reagent tier below refills the standard working conc. Only
    # touches UNVERIFIED values (no source on record); source-backed values are left alone. This
    # means no redundant "check this" flag for something we can resolve from the reagent table.
    for ob in list(reg.values()):
        if ob.get("field_name") != "amount":
            continue
        if not known_reagents.lookup(sanity_check._resolve_item_name(proto, ob)):
            continue
        cur = ob.get("current_value") or ob.get("recommended_candidate")
        q = standard_units.parse_quantity(str(cur or ""))
        # only auto-correct values the agent put there (legacy auto-import or AI/typical guess) —
        # never an explicit user confirmation or a source-backed value.
        unverified = ob.get("legacy_imported") or ob.get("status") in uncertainty_slots.PARTIAL
        if q and q.dimension == "volume" and unverified and ob.get("status") != "unresolved":
            value_promoter.keep_unresolved(proto, ob["slot_id"], _user_email())
    n_ev = n_cat = n_typ = n_ai = 0
    for ob in list(reg.values()):
        if ob.get("status") != "unresolved":
            continue
        prop = evidence_resolver.best_proposal(ob, proto, srcs, broker=broker)
        tier = "ev"
        if not prop and ob.get("field_name") == "amount":
            # standard working concentration for a known RAW reagent (polybrene, antibiotics…)
            kr = known_reagents.suggest(sanity_check._resolve_item_name(proto, ob))
            if kr and uncertainty_slots.dimension_ok(ob.get("expected_type"), kr["value"]) is not False:
                prop = kr; tier = "typ"
        if not prop:
            prop = defaults_engine._catalog_proposal(proto, ob); tier = "cat"
        if not prop:
            cands = suggest_value.typical_candidates(proto, ob)
            prop = cands[0] if cands else None; tier = "typ"
        if prop:
            value_promoter.auto_resolve(proto, ob["slot_id"], prop)
            o2 = uncertainty_slots.get(proto, ob["slot_id"])
            if prop.get("inference_basis"):
                o2["inference_basis"] = prop["inference_basis"]
            if prop.get("citation"):
                o2["citation"] = prop["citation"]
            n_ev += tier == "ev"; n_cat += tier == "cat"; n_typ += tier == "typ"
    if with_ai:
        remaining = [{"id": o["slot_id"],
                      "label": f"{o.get('step_id') or 'material'} · {o['field_name']} ({o['expected_type']})",
                      "context": ""}
                     for o in reg.values() if o.get("status") == "unresolved"
                     and o["expected_type"] not in uncertainty_slots.NON_SUGGESTABLE_TYPES]
        if remaining:
            res = FillAgent().suggest(proto, remaining, st.session_state.get("fill_context", ""),
                                      source_text=st.session_state.get("raw_text", ""))
            props = res.get("proposals", {}) or {}
            for sid, v in (res.get("suggestions", {}) or {}).items():
                if not str(v).strip():
                    continue
                p = props.get(sid, {})
                status = "typical_range" if p.get("evidence_class") == "typical_range" else "ai_suggested"
                try:
                    value_promoter.apply(proto, sid, status, str(v),
                                         {"evidence_class": status, "source_name": "agent:Fill Assistant",
                                          "confidence": p.get("confidence", 0.35),
                                          "rationale": p.get("rationale", "")},
                                         "system:agent:Fill Assistant")
                    n_ai += 1
                except value_promoter.PromotionError:
                    pass
    n_consistent = len(consistency.normalize(proto))
    persist_protocol(proto)
    log_event("bulk_auto_resolve", {"evidence": n_ev, "catalog": n_cat, "typical": n_typ,
                                    "ai": n_ai, "consistency": n_consistent, "not_applicable": n_na})
    still = sum(1 for x in reg.values() if x.get("status") in ("unresolved", "conflict"))
    return {"evidence": n_ev, "catalog": n_cat, "typical": n_typ, "ai": n_ai,
            "consistency": n_consistent, "not_applicable": n_na, "still": still,
            "filled": n_ev + n_cat + n_typ + n_ai}


def _maybe_autofill_on_open(proto: dict):
    """When a protocol opens in Design with unresolved values, pre-fill them once so the
    page already shows suggested + scaled values — no per-step clicking. Runs a single
    time per protocol version (guarded), and is fully reversible on the Resolve tab."""
    if not proto:
        return
    reg = uncertainty_slots.registry(proto)
    # always (cheap, deterministic, idempotent): retire inapplicable speed/temperature slots,
    # so reopening a protocol cleans up any previously mis-suggested condition values too.
    changed = bool(_retire_inapplicable_conditions(proto))
    # field hygiene on reopen too (idempotent): clean parse artifacts in protocols built before
    # this existed — temp-in-time-field, leaked storage temps, amounts copied across reagents.
    try:
        dirty = bool(field_hygiene.clean(proto))
        dirty = bool(reagent_placement.apply(proto)) or dirty
        if dirty:
            proto.pop("uncertainty", None)
            reg = uncertainty_slots.enumerate_slots(proto)   # REBUILD the registry (not just fetch)
            changed = True
    except Exception:
        pass
    # ensure the registry is actually populated (registry() only fetches; enumerate builds it) —
    # otherwise completeness reads 0 slots and shows a false '100% filled'.
    if not reg:
        reg = uncertainty_slots.enumerate_slots(proto)
    # capture embedded sequences (Twist orders, primers, FASTA) for protocols built before this
    # existed — so reopening an old run still surfaces the WT/Mut insert & primer sequences.
    if not proto.get("sequences"):
        seqs = sequence_scan.scan_docs(st.session_state.get("source_docs") or [])
        if seqs:
            sequence_scan.attach_to_materials(proto, seqs)
            changed = True
    if changed:
        persist_protocol(proto)
    if not any(o.get("status") == "unresolved" for o in reg.values()):
        return
    # PERSISTED guard: once a protocol version has been auto-filled and saved, don't re-run on
    # every reload (that wasted a pass and "didn't change anything"). Reset when a new version
    # is generated. A session guard also avoids re-running within the same session.
    ver = str(proto.get("protocol_version", "v1"))
    if proto.get("autofill_done") == ver:
        return
    key = f"{proto.get('protocol_title','')}::{ver}"
    done = st.session_state.setdefault("_autofilled_versions", set())
    if key in done:
        return
    n_unres = sum(1 for o in reg.values() if o.get("status") == "unresolved")
    with st.spinner(f"Pre-filling {n_unres} value(s) with standardized + per-reaction-scaled "
                    "suggestions (you confirm the high-risk ones)…"):
        r = run_bulk_autofill(proto, broker=_knowledge_broker(), srcs=_resolve_sources())
    done.add(key)
    proto["autofill_done"] = ver
    persist_protocol(proto)
    st.session_state["_autofill_flash"] = (
        f"Pre-filled {r['filled']} value(s) as labeled suggestions — "
        f"{r['still']} high-risk/unverifiable left for you to confirm.")


def page_design_hub():
    """The main Design hub — protocol review, value filling, and uncertainty
    resolution in one place. Review has an optional RIGHT-hand Tools panel you can
    show/hide for a clean canvas."""
    _maybe_autofill_on_open(st.session_state.get("protocol"))
    t1, t2, t3, t4 = st.tabs(["Review protocol", "Fill details", "Resolve values",
                              "Design from scratch"])
    with t1:
        proto = st.session_state.get("protocol")
        if st.session_state.get("_reagent_flash"):
            st.info(st.session_state.pop("_reagent_flash"))
        if st.session_state.get("_seq_flash"):
            st.info(st.session_state.pop("_seq_flash"))
        if st.session_state.get("_flow_fix_flash"):
            st.info(st.session_state.pop("_flow_fix_flash"))
        if st.session_state.get("_autofill_flash"):
            st.success(st.session_state.pop("_autofill_flash"))
        show_tools = st.toggle("Tools panel", value=st.session_state.get("show_tools", True),
                               key="show_tools",
                               help="Show/hide the right-hand panel: scaling, provenance, analysis "
                                    "& lookups. Off = everything inline on one column.")
        if proto:
            main_col, tools_col = st.columns([0.68, 0.32], gap="medium")
            with tools_col:
                if not show_tools:
                    # marker → CSS hides this whole column and widens the main one
                    st.markdown("<span class='aux-sink'></span>", unsafe_allow_html=True)
                st.markdown("### Tools")
                st.caption("Only tools relevant to this assay are shown. Toggle off to hide.")
                _render_design_tools(proto)
            with main_col:
                page_protocol(tools_col=tools_col)   # analysis panels render in the right column
            if not show_tools:
                st.markdown(
                    "<style>"
                    "[data-testid='stHorizontalBlock']:has(.aux-sink)>[data-testid='stColumn']:last-child"
                    "{display:none !important;}"
                    "[data-testid='stHorizontalBlock']:has(.aux-sink)>[data-testid='stColumn']:first-child"
                    "{flex:1 1 100% !important;width:100% !important;}"
                    "</style>", unsafe_allow_html=True)
        else:
            page_protocol()
    with t2:
        page_fill()
    with t3:
        page_resolve()
    with t4:
        page_design()


def _plan_step_ids(proto: dict) -> dict:
    return {s.get("step_number"): s.get("step_id") for s in proto.get("workflow", []) or []}


def _session_progress(proto: dict, sess: dict) -> tuple:
    """(steps_done, steps_total) for a plan session, from live bench completion."""
    ids = _plan_step_ids(proto)
    comp = st.session_state.get("completed_steps", set()) or set()
    steps = sess.get("steps", []) or []
    done = sum(1 for s in steps if ids.get(s.get("step_number")) in comp)
    return done, len(steps)


def _render_plan_calendar(proto: dict, plan: dict):
    """An in-app calendar that maps each plan session to a date and shows live
    progress (derived from bench step completion + manual day completion)."""
    import datetime as _dt
    sessions = plan.get("sessions", []) or []
    if not sessions:
        return
    start = st.date_input("Start date for this plan",
                          value=st.session_state.get("plan_start_date", _dt.date.today()),
                          key="plan_start_date")
    dates = [start + _dt.timedelta(days=i) for i in range(len(sessions))]
    by_date = {d: i for i, d in enumerate(dates)}
    prog = [_session_progress(proto, s) for s in sessions]
    manual = st.session_state.setdefault("plan_done", set())

    def _done(i):
        d, t = prog[i]
        return (t > 0 and d >= t) or (i in manual)

    done_days = sum(1 for i in range(len(sessions)) if _done(i))
    st.progress(done_days / len(sessions) if sessions else 0.0,
                text=f"{done_days}/{len(sessions)} day(s) complete")

    today = _dt.date.today()
    first = dates[0].replace(day=1)
    grid_start = dates[0] - _dt.timedelta(days=dates[0].weekday())
    grid_end = dates[-1] + _dt.timedelta(days=(6 - dates[-1].weekday()))
    colors = {"done": "#16A34A", "today": "#2563EB", "past": "#DC2626", "up": "#6B7280"}
    css = ("<style>.cal{font-family:inherit;margin:6px 0 2px}"
           ".cal-h{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}"
           ".cal-h div{font-size:10.5px;font-weight:700;color:#6B7280;text-align:center}"
           ".cal-row{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}"
           ".cal-cell{min-height:54px;border:1px solid #E5E7EB;border-radius:8px;padding:3px 4px;background:#fff}"
           ".cal-cell.dim{background:#FAFAFA;color:#C0C4CC}"
           ".cal-d{font-size:10.5px;color:#9CA3AF;text-align:right}"
           ".cal-s{margin-top:2px;border-radius:6px;padding:2px 4px;color:#fff;font-size:10.5px;font-weight:700;line-height:1.15}"
           ".cal-s span{font-weight:500;opacity:.95}</style>")
    head = "<div class='cal-h'>" + "".join(f"<div>{d}</div>" for d in
                                           ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) + "</div>"
    rows = []
    cur = grid_start
    while cur <= grid_end:
        cells = []
        for _ in range(7):
            dim = " dim" if cur.month != first.month else ""
            inner = f"<div class='cal-d'>{cur.day}</div>"
            if cur in by_date:
                i = by_date[cur]
                d, t = prog[i]
                status = ("done" if _done(i) else
                          ("today" if cur == today else ("past" if cur < today else "up")))
                inner += (f"<div class='cal-s' style='background:{colors[status]}'>"
                          f"Day {i + 1}<br><span>{d}/{t} steps</span></div>")
            cells.append(f"<div class='cal-cell{dim}'>{inner}</div>")
            cur += _dt.timedelta(days=1)
        rows.append("<div class='cal-row'>" + "".join(cells) + "</div>")
    st.markdown(css + "<div class='cal'>" + head + "".join(rows) + "</div>", unsafe_allow_html=True)
    st.caption("Green = complete · Blue = today · Red = past-due · Grey = upcoming. "
               "Progress updates live from Bench step completion.")
    return dates, manual, _done


def page_plan():
    proto = st.session_state.protocol
    if not proto:
        st.info("Generate or load a protocol first.")
        return
    hero("Execution plan",
         "Day-by-day schedule with safe stops, overnight incubations, and hands-on vs walk-away time.")

    n_confirm = count_confirm(proto)
    if n_confirm:
        st.warning(f"{n_confirm} step value(s) are unconfirmed (incl. some times). "
                   "Fill exact times on the Fill page for an accurate schedule.")

    c1, c2 = st.columns(2)
    with c1:
        hours = st.number_input("Hands-on hours available per day", min_value=1.0,
                                max_value=24.0, value=6.0, step=0.5)
    with c2:
        allow_overnight = st.checkbox("Allow overnight incubations (end day there)", value=True)
    notes = st.text_area("Scheduling notes (optional)", "",
                         placeholder="e.g. I can't start before 10am; cells must be processed same day")

    if st.button("Generate day-by-day plan", type="primary"):
        constraints = {"hours_per_day": float(hours), "allow_overnight": allow_overnight, "notes": notes}
        with st.spinner("Planner Agent (fast model): chunking into sessions…"):
            plan = PlannerAgent().plan(proto, constraints)
        st.session_state.plan = plan
        if plan.get("status") == "success" and st.session_state.run_dir:
            ver = proto.get("protocol_version", "v1")
            save_json(st.session_state.run_dir, f"plan_{ver}.json", plan)
            save_text(st.session_state.run_dir, f"plan_{ver}.md", plan_to_markdown(plan))
        log_event("plan_generated", {"sessions": plan.get("num_sessions"),
                                     "status": plan.get("status")})
        st.rerun()

    plan = st.session_state.plan
    if not plan:
        return
    if plan.get("status") == "error":
        st.error(f"Planning failed: {plan.get('error')}")
        return

    st.divider()
    metric_cards([
        ("Sessions / days", str(plan.get("num_sessions", len(plan.get("sessions", []))))),
        ("Total time", plan.get("total_estimated_time", "—")),
        ("Hands-on", plan.get("total_hands_on", "—"), "active bench"),
        ("Walk-away", plan.get("total_walk_away", "—"), "unattended"),
    ])
    a = plan.get("assumptions", {}) or {}
    st.caption(f"Assumptions: {a.get('hours_per_day','?')} h/day · overnight "
               f"{'allowed' if a.get('allow_overnight', True) else 'not allowed'}.")

    # live calendar (maps sessions to dates; progress from bench completion)
    _cal = _render_plan_calendar(proto, plan)
    _dates = _cal[0] if _cal else []
    _manual = _cal[1] if _cal else set()
    _done_fn = _cal[2] if _cal else (lambda i: False)

    with st.expander("Context-aware scaling — what if I change vessel?"):
        st.caption("Change the vessel and the dependent values re-derive automatically "
                   "(growth-area for cells, working-volume for media), each explaining why.")
        names = [v["name"] for v in vessels.list_vessels()]
        sc1, sc2 = st.columns(2)
        from_v = sc1.selectbox("Current vessel", names,
                               index=names.index("T75 flask") if "T75 flask" in names else 0,
                               key="scale_from")
        to_v = sc2.selectbox("Scale to", names,
                             index=names.index("6-well plate") if "6-well plate" in names else 0,
                             key="scale_to")
        cells_txt = st.text_input("Cells currently in this vessel (optional)", "7.5e6",
                                  key="scale_cells")
        if st.button("Recompute for the new vessel", key="scale_go"):
            cells_num = standard_units.parse_number(cells_txt) or 0.0
            g = (protocol_graph.DependencyGraph()
                 .add("seeding", ["vessel"], "vessel_area",
                      {"base_value": cells_num, "from_vessel": from_v}, label="seeding number")
                 .add("media_mL", ["vessel"], "vessel_media", {}, label="media volume (mL)"))
            base = {"vessel": from_v, "seeding": cells_num,
                    "media_mL": (vessels.get_vessel(from_v) or {}).get("working_volume_mL")}
            out = protocol_graph.recompute(g, base, {"vessel": to_v})
            if not out["changes"]:
                st.info("No change (same vessel).")
            for ch in out["changes"]:
                new = ch["new"]
                shown = f"{new:.2e}" if isinstance(new, (int, float)) and new >= 1e4 else (
                    f"{new:.3g}" if isinstance(new, (int, float)) else new)
                st.markdown(f"- **{ch['label']}** → {shown}")
                st.caption(ch["explanation"])

    st.divider()
    for i, sess in enumerate(plan.get("sessions", []) or []):
        with st.container(border=True):
            ho, wa = sess.get("estimated_hands_on"), sess.get("estimated_walk_away")
            split = f"  ·  hands-on {ho}  ·  walk-away {wa}" if (ho or wa) else ""
            _date = f"  ·  {_dates[i].strftime('%a %b %d')}" if i < len(_dates) else ""
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"#### {sess.get('title','Day')} — {sess.get('estimated_time','')}{split}{_date}")
            _d, _t = _session_progress(proto, sess)
            _checked = hc2.checkbox("Done", value=_done_fn(i), key=f"planday_{i}",
                                    help=f"{_d}/{_t} steps done in Bench")
            if _checked:
                _manual.add(i)
            else:
                _manual.discard(i)
            for s in sess.get("steps", []) or []:
                stage = f"  ·  _{s['stage']}_" if s.get("stage") else ""
                icon = "" if s.get("activity") == "walk_away" else ""
                st.markdown(f"- {icon} **Step {s.get('step_number','?')}**: {s.get('title','')}  "
                            f"· {s.get('time_estimate','')}{stage}")
            if sess.get("reagents_to_prepare"):
                st.caption("Prepare: " + ", ".join(sess["reagents_to_prepare"]))
            st.info(f"Break after: {sess.get('break_after','')}")
            for w in sess.get("warnings", []) or []:
                st.warning(f"{w}")
            for nnote in sess.get("notes", []) or []:
                st.caption(nnote)

    if plan.get("open_questions"):
        st.markdown("**Open questions**")
        for q in plan["open_questions"]:
            st.write(f"- {q}")

    st.divider()
    ver = proto.get("protocol_version", "v1")
    d1, d2 = st.columns(2)
    with d1:
        st.download_button("⬇ Plan (.md)", plan_to_markdown(plan),
                           file_name=f"plan_{ver}.md", mime="text/markdown",
                           use_container_width=True)
    with d2:
        st.download_button("⬇ Plan (.json)", json.dumps(plan, indent=2, ensure_ascii=False),
                           file_name=f"plan_{ver}.json", mime="application/json",
                           use_container_width=True)
    if st.button("▶ Go to Bench Mode", use_container_width=True):
        st.session_state.page = "bench"
        st.rerun()


# ---------------------------------------------------------------------- #
# Page D: Bench Mode
# ---------------------------------------------------------------------- #
def page_bench():
    proto = st.session_state.protocol
    normalize_protocol(proto)
    workflow = proto.get("workflow", []) or []
    hero("Bench Mode",
         f"{proto.get('protocol_title','')} · {proto.get('protocol_version','v1')} — one step at a time.")

    if not workflow:
        st.info("No steps to run.")
        return

    total = len(workflow)
    # self-heal: drop completed/flagged ids that no longer exist (after merge/split/
    # delete/reorder), and clamp the progress ratio to [0, 1].
    valid_ids = {s.get("step_id") for s in workflow}
    st.session_state.completed_steps = {c for c in st.session_state.completed_steps if c in valid_ids}
    st.session_state.flagged = {k: v for k, v in st.session_state.flagged.items() if k in valid_ids}
    done = len(st.session_state.completed_steps)
    ratio = min(1.0, max(0.0, done / total)) if total else 0.0
    st.progress(ratio, text=f"{done}/{total} steps complete")
    if st.session_state.bench_idx >= total:
        st.session_state.bench_idx = max(0, total - 1)

    # Welcome-back / resume banner
    if st.session_state.get("_resumed") and done:
        first_incomplete = next(
            (i for i, s in enumerate(workflow)
             if s["step_id"] not in st.session_state.completed_steps), total - 1)
        cb1, cb2 = st.columns([3, 1])
        cb1.info(f"Welcome back — you last worked here on {st.session_state['_resumed'][:16].replace('T',' ')} "
                 f"({done}/{total} steps done).")
        if cb2.button(f"Resume at step {first_incomplete + 1}", type="primary", use_container_width=True):
            st.session_state.bench_idx = first_incomplete
            st.session_state._resumed = None
            save_progress()
            st.rerun()

    # Step navigation
    idx = st.session_state.bench_idx
    idx = max(0, min(idx, total - 1))
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("← Prev", disabled=idx == 0, use_container_width=True):
            st.session_state.bench_idx = idx - 1
            st.rerun()
    with nav2:
        labels = [
            f"{'' if s['step_id'] in st.session_state.completed_steps else '◻'} "
            f"Step {s.get('step_number')} — {s.get('title')}"
            for s in workflow
        ]
        chosen = st.selectbox("Jump to step", range(total), index=idx, format_func=lambda i: labels[i])
        if chosen != idx:
            st.session_state.bench_idx = chosen
            st.rerun()
    with nav3:
        if st.button("Next →", disabled=idx == total - 1, use_container_width=True):
            st.session_state.bench_idx = idx + 1
            st.rerun()

    step = workflow[idx]
    sid = step["step_id"]
    safety = (proto.get("preconditions", {}) or {}).get("safety_notes", [])
    if idx == 0 and safety:
        # split long safety blobs into scannable bullets, tucked in a collapsed
        # expander so they don't dominate the bench view
        notes = safety if isinstance(safety, list) else [safety]
        bullets = []
        for n in notes:
            for part in re.split(r"(?<=[.!])\s+", str(n).strip()):
                part = part.strip()
                if part and part not in bullets:
                    bullets.append(part)
        with st.expander(f"Safety — read before starting ({len(bullets)} points)",
                         expanded=False):
            for b in bullets:
                st.markdown(f"- {b}")

    cond = step.get("conditions", {}) or {}
    if step.get("stage"):
        st.caption(f"Stage: {step['stage']}")
    st.subheader(f"Step {step.get('step_number')} / {total} — {step.get('title')}")
    if step.get("purpose"):
        st.caption(f"Purpose: {step['purpose']}")

    _speed = _clean_val(cond.get("speed"))
    _speed = _speed if _looks_like_speed(_speed) else ""
    cA, cB, cC = st.columns(3)
    cA.info(f"Time\n\n{_clean_val(step.get('time_estimate')) or '—'}")
    cB.info(f"Temp\n\n{_clean_val(cond.get('temperature')) or '—'}")
    cC.info(f"Speed\n\n{_speed or '—'}")
    _other = _relevant_other(proto, step)
    if _other:
        st.caption(f"Condition: {_other}")

    _missing = _missing_fields(step)
    if _missing:
        cwarn, cbtn = st.columns([3, 1])
        cwarn.warning("**Fill these before running this step:**"
                      + "".join(f"\n- {m}" for m in _missing))
        if cbtn.button("Fill details", key=f"fill_from_bench_{sid}"):
            st.session_state.page = "fill"
            st.rerun()
        _render_value_suggestions(step, f"bench_{sid}")

    # --- active uncertainty objects for this step (evidence-aware) ---------- #
    _unc_objs = _bench_uncertainty_objs(proto, step)
    if _unc_objs:
        st.markdown("**Values to confirm for this step**")
        _email = _user_email()
        for o in _unc_objs:
            usid = o["slot_id"]
            box = st.container(border=True)
            label = f"{o['field_name']} ({o['expected_type']}) — {_STATUS_LABEL.get(o['status'], o['status'])}"
            box.markdown(_risk_md(o['risk_level']) + f" — **{label}**", unsafe_allow_html=True)
            if o.get("recommended_candidate"):
                box.caption(f"Best candidate: **{o['recommended_candidate']}**  ·  {_evidence_chip(o)}")
            else:
                box.caption(f"No candidate yet · {_evidence_chip(o)}")
            if o["risk_level"] == "high" and o["status"] in ("unresolved", "conflict"):
                box.error(f"High risk: {o['risk_if_wrong']} — confirm before running.")
            elif o["risk_level"] == "high":
                box.warning(f"High risk, relying on a suggestion: {o['risk_if_wrong']}")
            bc = box.columns([3, 1, 1])
            bval = bc[0].text_input("Confirm value", value=str(o.get("recommended_candidate") or ""),
                                    key=f"benchval_{usid}", label_visibility="collapsed",
                                    placeholder="enter exact value")
            if bc[1].button("Accept", key=f"benchacc_{usid}", type="primary"):
                if bval.strip():
                    value_promoter.user_confirm(proto, usid, bval.strip(), _email)
                    persist_protocol(proto)
                    log_event("value_resolved", {"slot_id": usid, "action": "bench_accept",
                                                 "value": bval.strip()})
                    st.rerun()
                else:
                    box.warning("Enter a value first.")
            if bc[2].button("Resolve…", key=f"benchres_{usid}"):
                st.session_state.page = "resolve"
                st.rerun()

    # Reagent checklist with exact amounts (tick as you add each one) — mis-propagated
    # reagents (same item on many unrelated steps) are filtered out as common sense.
    reagents = _relevant_reagents(proto, step)
    if reagents:
        st.markdown("**Reagents for this step** — check off as you add each")
        for ri, r in enumerate(reagents):
            amount = r.get("amount", "")
            tag = " confirm amount" if CONFIRM_TAG in str(amount) else ""
            st.checkbox(
                f"{r.get('item','')}  ·  **{amount or '—'}**{tag}",
                key=f"reag_chk_{sid}_{ri}",
            )

    # Each instruction is its own checkable action
    st.markdown("**Step actions** — check off as you go")
    instrs = step.get("instructions", []) or []
    done_actions = 0
    for ii, instr in enumerate(instrs):
        flag = " confirm value" if CONFIRM_TAG in str(instr) else ""
        if st.checkbox(f"{instr}{flag}", key=f"act_chk_{sid}_{ii}"):
            done_actions += 1
    if instrs:
        st.caption(f"{done_actions}/{len(instrs)} actions checked")
    render_expand_step(step, f"bench_{sid}")

    st.success(f"**Expected observation:** {step.get('expected_observation','')}")
    st.markdown(f"**Checkpoint:** {step.get('checkpoint','')}")
    if step.get("pause_point"):
        st.info("**Pause point** — safe to stop here.")
    hrs = step.get("human_review_required", []) or []
    for hi, hr in enumerate(hrs):
        wc1, wc2 = st.columns([5, 1])
        wc1.warning(f"Human review: {hr}")
        if wc2.button("Resolve", key=f"hr_{sid}_{hi}", use_container_width=True):
            step["human_review_required"] = [h for j, h in enumerate(hrs) if j != hi]
            persist_protocol(proto)
            log_event("human_review_resolved", {"step_id": sid})
            st.rerun()

    # inline human edit of this step (fill values, then warnings can be cleared)
    with st.expander("Edit this step (human fill)"):
        cond = step.get("conditions", {}) or {}
        e1, e2, e3 = st.columns(3)
        new_t = e1.text_input("Time", step.get("time_estimate", ""), key=f"edit_t_{sid}")
        new_temp = e2.text_input("Temperature", cond.get("temperature", ""), key=f"edit_temp_{sid}")
        new_spd = e3.text_input("Speed", cond.get("speed", ""), key=f"edit_spd_{sid}")
        new_instr = st.text_area("Instructions (one per line)",
                                 "\n".join(step.get("instructions", []) or []),
                                 key=f"edit_instr_{sid}", height=140)
        if st.button("Save step", key=f"edit_save_{sid}"):
            step["time_estimate"] = new_t.strip()
            step.setdefault("conditions", {})["temperature"] = new_temp.strip()
            step["conditions"]["speed"] = new_spd.strip()
            step["instructions"] = [l.strip() for l in new_instr.split("\n") if l.strip()]
            persist_protocol(proto)
            log_event("step_edited_bench", {"step_id": sid})
            st.success("Step saved.")
            st.rerun()
        st.caption("After filling exact values here, use Resolve above to clear the matching "
                   "human-review warning.")

    with st.expander("Troubleshooting for this step"):
        for t in step.get("troubleshooting", []) or []:
            st.write(f"**{t.get('problem','')}**")
            if t.get("possible_causes"):
                st.caption("Causes: " + ", ".join(t["possible_causes"]))
            st.write("Actions: " + ", ".join(t.get("actions", [])))
            if t.get("escalate_if"):
                st.caption("Escalate if: " + t["escalate_if"])
            st.divider()

    calc_idx = _suggested_calc(step)
    calc_names = ["PCR", "Ligation", "Dilution", "Cell seeding"]
    relevant = any(k in (step.get("title", "") + " " + " ".join(step.get("instructions", []) or [])).lower()
                   for k in ("pcr", "amplif", "ligat", "seed", "transduc", "dilut", "resuspend", "anneal"))
    with st.expander(f"Bench calculators{' · ' + calc_names[calc_idx] + ' looks relevant here' if relevant else ''}",
                     expanded=relevant):
        if relevant:
            st.caption(f"This step looks like a **{calc_names[calc_idx]}** step — that tab is the one you want.")
        render_calculators(f"bench_{sid}", default_tab=calc_idx)

    st.divider()
    # Mark complete — blocked while a high-risk value is unresolved/conflicting
    _blocking = _bench_blocking(_bench_uncertainty_objs(proto, step))
    checked = sid in st.session_state.completed_steps
    if _blocking and not checked:
        names = ", ".join(f"{b['field_name']} ({b['expected_type']})" for b in _blocking)
        st.error(f"Locked — confirm high-risk value(s) before completing this step: {names}. "
                 "Accept above, mark N/A, or Keep-unresolved on the Resolve page.")
        st.checkbox("Mark step complete", value=False, key=f"chk_{sid}", disabled=True)
    else:
        new_checked = st.checkbox("Mark step complete", value=checked, key=f"chk_{sid}")
        if new_checked and not checked:
            st.session_state.completed_steps.add(sid)
            log_event("step_completed", {"step_id": sid})
            if idx < total - 1:
                st.session_state.bench_idx = idx + 1
            st.rerun()
        elif not new_checked and checked:
            st.session_state.completed_steps.discard(sid)
            st.rerun()

    # Flag issue
    st.markdown("**Flag an issue with this step**")
    fc1, fc2 = st.columns([1, 2])
    with fc1:
        issue_type = st.selectbox("Issue type", FLAG_OPTIONS, key=f"flag_{sid}")
    with fc2:
        observation = st.text_input("Observation note", key=f"obs_{sid}",
                                    placeholder="What did you see?")
    if st.button("Add flag", key=f"addflag_{sid}"):
        st.session_state.flagged[sid] = {
            "step_id": sid,
            "step_title": step.get("title", ""),
            "issue_type": issue_type,
            "observation": observation,
        }
        log_event("issue_flagged", st.session_state.flagged[sid])
        st.rerun()

    if st.session_state.flagged:
        st.error(f"{len(st.session_state.flagged)} flagged step(s): "
                 + ", ".join(st.session_state.flagged.keys()))
        if st.button("→ Trigger Protocol Revision", type="primary"):
            st.session_state.page = "revision"
            st.rerun()

    # persist position/progress every render so the user can leave anytime
    save_progress()

    st.divider()
    render_chat(current_step=step, key="chat_bench")

    st.divider()
    if st.button("← Back to protocol overview"):
        st.session_state.page = "protocol"
        st.rerun()


# ---------------------------------------------------------------------- #
# Page E: Revision
# ---------------------------------------------------------------------- #
def page_revision():
    hero("Protocol Revision", "Surgically revise only the flagged step(s) — the rest stays unchanged.")
    proto = st.session_state.protocol
    flagged = st.session_state.flagged

    if not flagged:
        st.info("No issues flagged. Go to Bench Mode and flag a step first.")
        if st.button("← Bench Mode"):
            st.session_state.page = "bench"
            st.rerun()
        return

    st.markdown("**Flagged issues**")
    for sid, f in flagged.items():
        st.write(f"- `{sid}` **{f['step_title']}** — {f['issue_type']}: {f.get('observation','')}")

    notes = st.text_area("Additional notes for the revision agent", "")
    constraints = st.session_state.input_meta.get("lab_constraints", "")

    if st.button("Generate revised protocol", type="primary"):
        cur_version = proto.get("protocol_version", "v1")
        target = _bump(cur_version)
        request = {
            "prior_protocol": proto,
            "troubleshooting_input": {
                "flagged_steps": list(flagged.values()),
                "additional_notes": notes,
                "protocol_version": cur_version,
            },
            "user_constraints": {"notes": constraints},
            "target_version": target,
        }
        with st.spinner(f"Protocol Agent (fast model): surgically revising {cur_version} → {target}…"):
            revised = ProtocolAgent().revise(request)

        if revised.get("status") == "error":
            st.error(f"Revision failed: {revised.get('error')}")
            return

        run_dir = st.session_state.run_dir
        ver = revised.get("protocol_version", target)
        save_json(run_dir, f"protocol_{ver}.json", revised)
        save_text(run_dir, f"protocol_{ver}.md", protocol_to_markdown(revised))
        save_text(run_dir, f"protocol_bench_{ver}.md", bench_to_markdown(revised))
        log_event("protocol_revised", {
            "from": cur_version, "to": ver,
            "changed_step_ids": revised.get("changed_step_ids", []),
        })
        st.session_state.protocol = revised
        st.session_state.flagged = {}
        st.session_state["_last_revision"] = revised
        st.rerun()

    last = st.session_state.get("_last_revision")
    if last:
        st.success(f"Revised to {last.get('protocol_version')}.")
        st.markdown(f"**Root-cause diagnosis:** {last.get('root_cause_diagnosis','')}")
        st.markdown(f"**Summary of changes:** {last.get('summary_of_changes','')}")
        st.markdown(f"**Changed steps:** {', '.join(last.get('changed_step_ids', [])) or 'none'}")
        with st.expander("Revision log"):
            for r in last.get("revision_log", []):
                st.write(f"- **{r.get('version')}** — {r.get('reason')} "
                         f"(changed: {', '.join(r.get('changed_step_ids', [])) or 'none'})")
        _download_buttons(last)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("← Return to Bench Mode (revised)", type="primary"):
                st.session_state["_last_revision"] = None
                st.session_state.page = "bench"
                st.rerun()
        with c2:
            if st.button("View protocol overview"):
                st.session_state["_last_revision"] = None
                st.session_state.page = "protocol"
                st.rerun()


# ---------------------------------------------------------------------- #
# Shared helpers
# ---------------------------------------------------------------------- #
def _bump(version: str) -> str:
    import re
    m = re.search(r"(\d+)", version or "v1")
    n = int(m.group(1)) if m else 1
    return f"v{n + 1}"


def _download_buttons(proto: dict):
    ver = proto.get("protocol_version", "v1")
    st.markdown("**Downloads**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "⬇ Full protocol (.md)",
            protocol_to_markdown(proto),
            file_name=f"protocol_{ver}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "⬇ Bench mode (.md)",
            bench_to_markdown(proto),
            file_name=f"protocol_bench_{ver}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "⬇ Protocol (.json)",
            json.dumps(proto, indent=2, ensure_ascii=False),
            file_name=f"protocol_{ver}.json",
            mime="application/json",
            use_container_width=True,
        )


# ---------------------------------------------------------------------- #
# Router
# ---------------------------------------------------------------------- #
def _status_badge(status: str) -> str:
    color = {"worked": "#15803D", "failed": "#B91C1C", "in_progress": "#B45309"}.get(status, "#667085")
    bg = {"worked": "#E9F7EF", "failed": "#FDECEC", "in_progress": "#FDF4E7"}.get(status, "#EEF1FF")
    return (f'<span style="background:{bg};color:{color};font-weight:700;font-size:11px;'
            f'padding:3px 9px;border-radius:999px;">{status or "—"}</span>')


def load_project_experiment(slug: str, exp_id: str):
    rec = proj.load_experiment(slug, exp_id)
    if not rec:
        st.error("Could not load that experiment.")
        return
    reset_run()
    st.session_state.run_dir = new_run_dir()
    st.session_state.protocol = rec.get("protocol")
    st.session_state.protocol_v1 = rec.get("protocol")
    st.session_state.input_meta = rec.get("input_meta", {})
    st.session_state.plan = rec.get("plan")
    src = rec.get("source_documents", []) or []
    st.session_state.source_docs = src
    # Restore the Parsed view so the user can SEE/EDIT what was uploaded.
    # Prefer a saved parsed snapshot; otherwise reconstruct from source documents.
    parsed_docs = rec.get("parsed_docs") or [
        {"protocol_title": d.get("title") or d.get("name", "document"),
         "doc_type": d.get("doc_type", "reference"),
         "assay_type": rec.get("assay_type", ""),
         "summary": (d.get("text", "") or "")[:600],
         "major_steps": [], "materials": [],
         "source_file": d.get("name", "")}
        for d in src
    ]
    st.session_state.parsed_docs = parsed_docs
    st.session_state.parsed = parsed_docs[0] if parsed_docs else None
    st.session_state.doc_include = {}
    st.session_state.current_project = slug
    st.session_state.current_exp_id = exp_id   # so further saves update this record
    st.session_state.input_reveal = True       # show the pre-filled Input form (not the landing)
    persist_protocol(rec.get("protocol", {}))
    log_event("experiment_reloaded", {"project": slug, "exp_id": exp_id, "n_docs": len(parsed_docs)})
    st.session_state.page = "protocol"
    st.rerun()


def _learn_source_docs():
    """All reference docs available for context: session uploads + active project."""
    docs = list(st.session_state.get("source_docs", []) or [])
    slug = st.session_state.get("current_project")
    if slug:
        try:
            docs = docs + proj.get_project_sources(slug)
            for e in proj.full_experiments(slug):
                docs += e.get("source_documents", []) or []
        except Exception:
            pass
    # dedup by title
    seen, out = set(), []
    for d in docs:
        t = d.get("title") or d.get("name", "")
        if t not in seen:
            seen.add(t); out.append(d)
    return out


_LEARN_CACHE = {"summary": "learn_summary", "literature": "learn_lit",
                "education": "learn_edu", "brief": "learn_brief"}


def build_project_brief():
    """Orchestrate the whole onboarding chain ONCE: summarize -> teach -> literature
    -> audit/critique -> improve -> document. Returns an assembled brief dict.
    Cached to project memory by the caller so it isn't re-run (token-saving)."""
    proto = st.session_state.protocol or {}
    meta = st.session_state.input_meta or {}
    level = meta.get("experience_level", "intermediate")
    docs = _learn_source_docs()
    name = _project_display_name() or proto.get("protocol_title", "this project")
    exps = _project_experiments()
    gt = next((d.get("text", "") for d in docs
               if "ground-truth" in d.get("title", "").lower()
               or "study notes" in d.get("title", "").lower()), "")
    topic = proto.get("core_experiment") or proto.get("assay_type") or name

    prog = st.progress(0.0, text="Gathering project materials…")
    summary = SummaryAgent().summarize(proto, docs, exps, name)
    prog.progress(0.18, text="Summarized the project")
    education = EducatorAgent().teach(proto, level, docs)
    prog.progress(0.38, text="Built the onboarding lesson")
    literature = LiteratureAgent().review_literature(
        topic, {"assay_type": proto.get("assay_type"), "core_experiment": proto.get("core_experiment"),
                "objective": proto.get("objective")}, docs)
    prog.progress(0.58, text="Reviewed background literature")
    audit = AuditAgent().audit(docs=st.session_state.get("parsed_docs", []), protocol=proto, ground_truth=gt)
    prog.progress(0.74, text="Audited for redundancy / contradictions")
    review = st.session_state.get("review") or ReviewAgent().review(proto, st.session_state.get("parsed") or {})
    prog.progress(0.86, text="Critiqued design & safety")
    improve = ImproveAgent().suggest(proto, review)
    prog.progress(0.96, text="Drafted design improvements")

    brief = {
        "status": "success", "project": name, "level": level,
        "timestamp": utc_timestamp(),
        "summary": summary, "education": education, "literature": literature,
        "audit": audit, "review": review, "improve": improve,
        "markdown": _assemble_brief_md(name, level, proto, summary, education,
                                       literature, audit, review, improve),
    }
    prog.progress(1.0, text="Project brief ready")
    return brief


def _assemble_brief_md(name, level, proto, summary, education, literature, audit, review, improve) -> str:
    L = [f"# Project brief — {name}", f"_Onboarding / training brief · audience level: {level} · "
         f"generated {utc_timestamp()}_\n"]
    if summary.get("status") == "success":
        L.append("## What this project is")
        L.append(summary.get("summary") or summary.get("one_liner", ""))
        if summary.get("design_logic"):
            L.append(f"\n**Design logic.** {summary['design_logic']}")
        if summary.get("arms_or_conditions"):
            L.append("\n**Arms / conditions:** " + "; ".join(summary["arms_or_conditions"]))
    if education.get("status") == "success":
        L.append("\n## Learn this (concepts to understand)")
        if education.get("overview"):
            L.append(education["overview"])
        for les in (education.get("lessons", []) or [])[:8]:
            L.append(f"- **{les.get('title','')}** — {les.get('why_it_matters','')}")
    if literature.get("status") == "success" and literature.get("papers"):
        L.append("\n## Background literature")
        for p in literature["papers"][:8]:
            cite = " · ".join(x for x in [p.get("authors", ""), str(p.get("year", "")), p.get("venue", "")] if x)
            L.append(f"- **{p.get('title','')}** {('('+cite+')') if cite else ''} — {p.get('summary','')}")
    if audit.get("status") == "success" and audit.get("findings"):
        L.append("\n## Consistency check (redundancy / contradictions / logic)")
        for f in audit["findings"]:
            L.append(f"- **[{f.get('severity','')}] {f.get('type','')}** ({f.get('where','')}): "
                     f"{f.get('issue','')} → _{f.get('suggested_fix','')}_")
    if review.get("status") == "success" and review.get("findings"):
        L.append("\n## Design critique")
        L.append(f"**Decision:** {review.get('decision','')} — {review.get('rationale','')}")
        for f in review["findings"][:10]:
            L.append(f"- [{f.get('severity','')}] {f.get('category','')}: {f.get('issue','')}")
    if improve.get("status") == "success":
        adds = (improve.get("add_controls", []) + improve.get("add_qc_checkpoints", [])
                + improve.get("add_open_questions", []))
        if adds:
            L.append("\n## Suggested improvements (review before applying)")
            for a in adds[:12]:
                L.append(f"- {a if isinstance(a, str) else a.get('checkpoint_name') or a.get('issue') or a}")
    L.append("\n## Protocol plan (steps)")
    for s in proto.get("workflow", []) or []:
        L.append(f"{s.get('step_number','?')}. {s.get('title','')}")
    return "\n".join(L)


def _render_brief(brief):
    if not brief:
        return
    if brief.get("status") != "success":
        st.error("Brief failed."); return
    cnt = (brief.get("audit", {}) or {}).get("counts", {}) or {}
    rev = (brief.get("review", {}) or {}).get("decision", "—")
    st.markdown(f"**Audience:** {brief.get('level','')}  ·  **Review:** {rev}  ·  "
                f"**Consistency flags:** {cnt.get('high',0)} {cnt.get('medium',0)} {cnt.get('low',0)}")
    if brief.get("_cached"):
        st.caption(f"from project memory ({brief['_cached']}). Use ↻ to rebuild.")
    st.markdown(brief.get("markdown", ""))
    st.download_button("⬇ Download brief (.md)", brief.get("markdown", ""),
                       file_name="project_brief.md", mime="text/markdown")


def _save_learn_cache(key: str, value: dict):
    """Persist a Learn output to the active project's memory (token-saving)."""
    slug = st.session_state.get("current_project")
    if slug and isinstance(value, dict) and value.get("status") == "success":
        try:
            proj.set_project_memory(slug, key, value)
        except Exception:
            pass


def _load_learn_cache():
    """On the Learn page, hydrate session from project memory if not already loaded."""
    slug = st.session_state.get("current_project")
    if not slug or st.session_state.get("_learn_cache_for") == slug:
        return
    try:
        mem = proj.get_project_memory(slug)
    except Exception:
        mem = {}
    for key, sskey in _LEARN_CACHE.items():
        entry = mem.get(key)
        if entry and not st.session_state.get(sskey):
            val = dict(entry.get("value", {}))
            val["_cached"] = entry.get("saved_at", "")
            st.session_state[sskey] = val
    st.session_state["_learn_cache_for"] = slug


def page_learn():
    hero("Learn & Understand", "Get up to speed on this project — summary, background literature, "
         "and a guided explanation of the experiment. (No hypotheses — search & teaching only.)")
    proto = st.session_state.protocol
    if not proto:
        slug = st.session_state.get("current_project")
        exps = proj.list_experiments(slug) if slug else []
        # show the project's cached brief even without a loaded protocol
        if slug:
            try:
                mem = proj.get_project_memory(slug)
            except Exception:
                mem = {}
            be = mem.get("brief")
            if be and isinstance(be.get("value"), dict):
                b = dict(be["value"]); b["_cached"] = be.get("saved_at", "")
                st.success("Showing this project's saved onboarding brief.")
                _render_brief(b)
                st.divider()
        if exps:
            st.info("Open an experiment to study it in full (summary, lesson, literature, brief):")
            for e in exps[:8]:
                if st.button(f"↻ {e['title'][:40]}  ({e['status']}, {e['n_steps']} steps)",
                             key=f"learn_load_{e['exp_id']}", use_container_width=True):
                    load_project_experiment(slug, e["exp_id"])
        else:
            st.info("Load or build a protocol first (or open a project with a saved experiment).")
        return
    meta = st.session_state.input_meta or {}
    level = meta.get("experience_level", "intermediate")
    docs = _learn_source_docs()
    st.caption(f"Depth set from your experience level: **{level}** · {len(docs)} reference doc(s) available.")

    # MEMORY: load cached Learn outputs from the project so we don't re-spend tokens
    _load_learn_cache()

    # One-click onboarding/training brief: runs the whole chain once, caches to memory
    with st.container(border=True):
        brief = st.session_state.get("learn_brief")
        bc1, bc2 = st.columns([3, 2])
        bc1.markdown('<div class="lab-sec">Project brief</div>', unsafe_allow_html=True)
        bc1.caption("One pass: summarize → teach → literature → critique (audit + review) → "
                    "improvements → protocol plan. Built once and remembered (no re-spend).")
        if bc2.button("Rebuild brief" if brief else "Build project brief",
                      key="build_brief", type="primary", use_container_width=True):
            with st.spinner("Running the onboarding chain…"):
                res = build_project_brief()
            st.session_state["learn_brief"] = res
            _save_learn_cache("brief", res)
            st.rerun()
        if brief:
            with st.expander("Project brief", expanded=True):
                _render_brief(brief)

    t_sum, t_lit, t_edu = st.tabs(["Project summary", "Literature", "Learn the experiment"])

    with t_sum:
        st.caption("A get-up-to-speed brief built from this project's protocol and reference documents. "
                   "Cached to project memory — regenerate only when something changes.")
        s0 = st.session_state.get("learn_summary")
        lbl = "↻ Regenerate summary" if s0 else "Generate project summary"
        if st.button(lbl, key="learn_sum_btn", type="primary"):
            with st.spinner("Project Summarizer: reading the project…"):
                res = SummaryAgent().summarize(proto, docs, _project_experiments(), _project_display_name())
            st.session_state["learn_summary"] = res
            _save_learn_cache("summary", res)
            st.rerun()
        s = st.session_state.get("learn_summary")
        if s and s.get("_cached"):
            st.caption(f"From project memory ({s.get('_cached')}). Use Regenerate to refresh.")
        if s and s.get("status") == "success":
            if s.get("one_liner"): st.markdown(f"**{s['one_liner']}**")
            if s.get("summary"): st.write(s["summary"])
            if s.get("goal"): st.markdown(f"**Goal.** {s['goal']}")
            if s.get("design_logic"): st.markdown(f"**Design logic.** {s['design_logic']}")
            if s.get("arms_or_conditions"):
                st.markdown("**Arms / conditions**")
                for a in s["arms_or_conditions"]: st.write(f"- {a}")
            if s.get("stages"):
                st.markdown("**Stages**")
                for a in s["stages"]: st.write(f"- {a}")
            wk = s.get("whats_known_vs_open") or {}
            if wk:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Established**")
                    for x in wk.get("established", []): st.write(f"- {x}")
                with c2:
                    st.markdown("**To confirm**")
                    for x in wk.get("to_confirm", []): st.write(f"- {x}")
            if s.get("mode") == "offline":
                st.caption("Offline brief — run live (DEMO_MODE=false) for a full narrative.")
        elif s:
            st.error(f"Summary failed: {s.get('error') or 'model returned no usable summary'}")
            with st.expander("Details"):
                st.json({k: v for k, v in s.items() if k != "text"})

    with t_lit:
        st.caption("Searches published literature on your targets/methods and summarizes it. "
                   "Search & summarize only — it does not generate hypotheses.")
        default_topic = proto.get("core_experiment") or proto.get("assay_type") or proto.get("protocol_title", "")
        topic = st.text_input("Topic / focus", value=default_topic, key="learn_lit_topic")
        if st.button("Search literature", key="learn_lit_btn", type="primary", disabled=not topic.strip()):
            ctx = {"assay_type": proto.get("assay_type"), "core_experiment": proto.get("core_experiment"),
                   "objective": proto.get("objective")}
            with st.spinner("Literature Agent: searching…"):
                res = LiteratureAgent().review_literature(topic, ctx, docs)
            st.session_state["learn_lit"] = res
            _save_learn_cache("literature", res)
            st.rerun()
        L = st.session_state.get("learn_lit")
        if L and L.get("_cached"):
            st.caption(f"From project memory ({L.get('_cached')}).")
        if L and L.get("status") == "success":
            if L.get("summary"): st.write(L["summary"])
            if L.get("themes"):
                st.markdown("**Themes:** " + ", ".join(L["themes"]))
            for p in L.get("papers", []):
                title = p.get("title", "")
                url = p.get("url", "")
                head = f"[{title}]({url})" if url else title
                meta_bits = " · ".join(x for x in [p.get("authors", ""), str(p.get("year", "")), p.get("venue", "")] if x)
                st.markdown(f"- **{head}**" + (f"  \n  _{meta_bits}_" if meta_bits else ""))
                if p.get("summary"): st.caption(p["summary"])
                if p.get("why_relevant"): st.caption(f"Relevance: {p['why_relevant']}")
            if L.get("background_for_intro"):
                with st.expander("Draft background paragraph (for Intro)"):
                    st.write(L["background_for_intro"])
            if L.get("note"): st.caption(L["note"])
        elif L:
            st.error(L.get("error", "Search failed."))

    with t_edu:
        st.caption(f"A guided explanation of the experiment, pitched at **{level}** level "
                   "(set from your project's experience level). Concepts, why each step matters, "
                   "and common pitfalls — not new design.")
        e0 = st.session_state.get("learn_edu")
        if st.button("↻ Regenerate lesson" if e0 else "Explain this experiment",
                     key="learn_edu_btn", type="primary"):
            with st.spinner("Experiment Educator: preparing the lesson…"):
                res = EducatorAgent().teach(proto, level, docs)
            st.session_state["learn_edu"] = res
            _save_learn_cache("education", res)
            st.rerun()
        E = st.session_state.get("learn_edu")
        if E and E.get("_cached"):
            st.caption(f"From project memory ({E.get('_cached')}).")
        if E and E.get("status") == "success":
            if E.get("overview"): st.write(E["overview"])
            for les in E.get("lessons", []):
                with st.container(border=True):
                    st.markdown(f"**Step {les.get('step_number','')} — {les.get('title','')}**")
                    if les.get("why_it_matters"): st.markdown(f"*Why it matters:* {les['why_it_matters']}")
                    if les.get("concept"): st.markdown(f"*Concept:* {les['concept']}")
                    if les.get("common_pitfalls"):
                        st.markdown("*Pitfalls:* " + "; ".join(x for x in les["common_pitfalls"] if x))
                    if les.get("what_to_check"):
                        st.markdown("*Check:* " + "; ".join(les["what_to_check"]))
            if E.get("glossary"):
                with st.expander("Glossary"):
                    for g in E["glossary"]:
                        st.markdown(f"- **{g.get('term','')}** — {g.get('definition','')}")
            if E.get("what_to_learn_next"):
                st.markdown("**Learn next:** " + ", ".join(E["what_to_learn_next"]))
            if E.get("mode") == "offline":
                st.caption("Offline outline — run live for full explanations + glossary.")
        elif E:
            st.error(E.get("error", "Could not generate the lesson."))


def _project_display_name():
    slug = st.session_state.get("current_project")
    if not slug:
        return (st.session_state.input_meta or {}).get("experiment_name", "")
    return next((p["name"] for p in proj.list_projects() if p["slug"] == slug), slug)


def _project_experiments():
    slug = st.session_state.get("current_project")
    if not slug:
        return []
    try:
        return proj.full_experiments(slug)
    except Exception:
        return []


def _outline_to_protocol(design: dict) -> dict:
    """Turn an experimental design's stage-level protocol_outline into a protocol dict
    the execution pipeline understands (so 'suggest the protocol to run' actually flows
    into Parse → Fill → Bench). Stages become steps with values left to confirm."""
    outline = design.get("protocol_outline") or []
    # match outline stages to designed validation assays so those steps carry the expected
    # result + the assay method (so the validation flows into the protocol, not just the design)
    vmap = {str(v.get("name", "")).strip().lower(): v for v in (design.get("validation_assays") or [])}
    wf = []
    for i, st_ in enumerate(outline, 1):
        title = st_.get("stage", f"Stage {i}") if isinstance(st_, dict) else str(st_)
        summary = st_.get("summary", "") if isinstance(st_, dict) else ""
        va = vmap.get(str(title).strip().lower())
        instructions = [summary or title]
        expected = ""
        if va:
            if va.get("method"):
                instructions.append(va["method"])
            exp = va.get("expected_results") or {}
            expected = ("; ".join(f"{k}: {v}" for k, v in exp.items()) if isinstance(exp, dict)
                        else str(exp))
        wf.append({
            "step_id": f"step_{i:02d}", "step_number": i, "title": title,
            "purpose": summary, "instructions": instructions,
            "time_estimate": CONFIRM_TAG,
            "conditions": {"temperature": "", "speed": "", "other": ""},
            "reagents": [], "expected_observation": expected, "checkpoint": "",
            "pause_point": False, "human_review_required": [], "troubleshooting": [],
            "notes": ["Generated from the experiment design — expand and fill exact values."]
            + ([f"Validation assay · source: {va.get('provenance','')}"] if va else []),
        })
    # validation assays become QC checkpoints too (the pass criteria = expected result)
    qc = []
    for v in (design.get("validation_assays") or []):
        exp = v.get("expected_results") or {}
        qc.append({
            "checkpoint_name": v.get("name", "Validation"),
            "when": "validation / readout",
            "measurements": [v.get("method", "")],
            "pass_criteria": [f"{k}: {val}" for k, val in exp.items()] if isinstance(exp, dict)
                             else [str(exp)],
            "fail_signals": ["result does not match the expected pattern"],
            "recommended_action_on_fail": "re-check construct identity, antibody, and controls.",
        })
    title = design.get("title", "Designed experiment")
    return {
        "protocol_title": title, "protocol_version": "v1",
        "assay_type": (design.get("system", {}) or {}).get("perturbation_modality", ""),
        "core_experiment": title, "objective": design.get("research_question", ""),
        "summary": design.get("rationale", ""),
        "design_rationale": design.get("rationale", ""),
        "preconditions": {"sample_requirements": [], "reagent_requirements": [],
                          "equipment_requirements": [], "safety_notes": [],
                          "lab_specific_fields_to_confirm": []},
        "materials": [], "workflow": wf, "qc_checkpoints": qc,
        "decision_points": [], "failure_branches": [], "artifact_outputs": [],
        "open_questions_for_human": design.get("open_questions", []),
        "confidence": "low",
    }


def _design_ctx():
    """Context passed to the designer (from the input form + any sidebar level)."""
    meta = st.session_state.input_meta or {}
    return {
        "cell_models": meta.get("design_cell_models", ""),
        "perturbation_modality": meta.get("design_modality", ""),
        "sample_type": meta.get("sample_type", ""),
        "lab_constraints": meta.get("lab_constraints", ""),
    }


def page_design():
    hero("Design an experiment",
         "The stage before a protocol: turn a research question into a rigorous design — "
         "arms, controls, readouts, replicates — then design guides and generate a protocol to run.")
    docs = _learn_source_docs()
    level = (st.session_state.input_meta or {}).get(
        "experience_level", st.session_state.get("user_level", "intermediate"))
    slug = st.session_state.get("current_project")

    # hydrate cached design outputs from project memory (so they persist per project)
    if slug and st.session_state.get("_design_cache_for") != slug:
        try:
            mem = proj.get_project_memory(slug)
        except Exception:
            mem = {}
        for key, sk in (("design", "design_result"), ("design_guides", "design_guides"),
                        ("design_critique", "design_critique")):
            ent = mem.get(key)
            if ent and not st.session_state.get(sk):
                st.session_state[sk] = dict(ent.get("value", {}))
        st.session_state["_design_cache_for"] = slug

    def _cache(key, sk, val):
        st.session_state[sk] = val
        if slug:
            try:
                proj.set_project_memory(slug, key, val)
            except Exception:
                pass

    st.caption(f"Depth pitched for **{_level_label(level)}** · {len(docs)} reference doc(s) available.")

    # Decision tree: if a protocol already exists, prefer ADDITIVE design (close the gaps in it)
    # over generating a replacement — designing from scratch shouldn't blow away current work.
    cur_proto = st.session_state.get("protocol")
    if cur_proto and (cur_proto.get("workflow")):
        gaps = flow_check.detect(cur_proto)
        with st.container(border=True):
            if gaps:
                st.markdown(f"**Your current protocol has {len(gaps)} logic gap(s).** "
                            "Close them *without* rebuilding — this adds/repairs only the missing steps.")
                for g in gaps[:6]:
                    st.caption(f"• {g['where']}: {g['issue']}")
                if st.button(f"Add / fix the {len(gaps)} missing step(s) in my current protocol",
                             key="design_additive", type="primary"):
                    fixes = flow_check.apply_fixes(cur_proto)
                    normalize_protocol(cur_proto)
                    st.session_state.protocol = cur_proto
                    persist_protocol(cur_proto)
                    log_event("design_additive_fix", {"n": len(fixes)})
                    st.success(f"Added/updated {len(fixes)} step(s) in place: "
                               + "; ".join(f['title'] for f in fixes) + ". Review on the Review tab.")
                    st.rerun()
            else:
                st.markdown("**Your current protocol has no detected logic gaps.** "
                            "Use the tools below only to design a *new* experiment from a goal.")
            st.caption("Note: 'Design from a goal' below generates a NEW protocol (it does not edit "
                       "the current one) — use it to start a fresh design, not to patch this one.")

    t_design, t_guides, t_crit = st.tabs(
        ["Design from a goal", "gRNA / molecular design", "Critique a design"])

    # ---- Tab 1: design from a goal --------------------------------------- #
    with t_design:
        goal = st.text_area(
            "Research question / goal",
            key="design_goal",
            placeholder="e.g. Which chromatin regulators control H3K27ac at active enhancers in "
                        "MCF7 vs MCF10A, and how does CRISPRi knockdown reshape it?")
        c1, c2 = st.columns(2)
        cells = c1.text_input("Cell model(s) / system", key="design_cells",
                              placeholder="e.g. MCF7, MCF10A (dCas9-KRAB)")
        modality = c2.selectbox("Perturbation modality",
                                ["CRISPRi (dCas9-KRAB)", "CRISPR-KO (Cas9)", "CRISPRa",
                                 "Overexpression", "Small molecule", "Other / none"],
                                key="design_modality_sel")
        if st.button("Design the experiment", key="design_run", type="primary",
                     disabled=not goal.strip()):
            meta = st.session_state.input_meta or {}
            meta["design_cell_models"] = cells
            meta["design_modality"] = modality
            st.session_state.input_meta = meta
            with st.spinner("Experiment Designer: proposing arms, controls and a protocol outline…"):
                res = ExperimentDesignAgent().design(goal.strip(), _design_ctx(), docs, level)
            _cache("design", "design_result", res)
            st.rerun()
        d = st.session_state.get("design_result")
        if d and d.get("status") == "success":
            _render_design(d)

    # ---- Tab 2: gRNA / molecular design ---------------------------------- #
    with t_guides:
        lib_genes = ExperimentDesignAgent._scan_library(docs).get("genes", [])
        default_targets = ", ".join(lib_genes[:40]) if lib_genes else ""
        if lib_genes:
            st.caption(f"Detected an uploaded library: **{len(lib_genes)} gene target(s)**.")
        targets = st.text_input("Target genes / request", value=default_targets,
                                key="design_targets",
                                placeholder="paste gene symbols, or upload a gRNA library spreadsheet")
        if st.button("Get design guidance", key="design_guides_run", type="primary"):
            with st.spinner("Designing gRNA/oligo criteria + ordering checklist…"):
                res = ExperimentDesignAgent().guides(targets.strip(), _design_ctx(), docs)
            _cache("design_guides", "design_guides", res)
            st.rerun()
        g = st.session_state.get("design_guides")
        if g and g.get("status") == "success":
            _render_guides(g)

    # ---- Tab 3: critique -------------------------------------------------- #
    with t_crit:
        st.caption("Review the design (or the loaded protocol) for missing controls, confounds, "
                   "power and readout validity.")
        target_obj = st.session_state.get("design_result") or st.session_state.get("protocol")
        if not target_obj:
            st.info("Design an experiment above, or load a protocol, then critique it.")
        else:
            label = "the current design" if st.session_state.get("design_result") else "the loaded protocol"
            if st.button(f"Critique {label}", key="design_crit_run", type="primary"):
                target_text = json.dumps(target_obj, ensure_ascii=False)[:14000]
                with st.spinner("Design Reviewer: checking controls, confounds and power…"):
                    res = ExperimentDesignAgent().critique(target_text, docs)
                _cache("design_critique", "design_critique", res)
                st.rerun()
            c = st.session_state.get("design_critique")
            if c and c.get("status") == "success":
                _render_critique(c)


def _render_design(d: dict):
    if d.get("mode") == "offline":
        st.caption("Offline template — run live (Live toggle on) for a goal-specific design.")
    if d.get("note"):
        st.caption(d["note"])
    if d.get("hypothesis"):
        st.markdown(f"**Hypothesis.** {d['hypothesis']}")
    if d.get("rationale"):
        st.write(d["rationale"])
    sysd = d.get("system", {}) or {}
    if sysd:
        bits = [f"**{k.replace('_',' ')}:** {', '.join(v) if isinstance(v, list) else v}"
                for k, v in sysd.items() if v]
        if bits:
            st.markdown("**System** — " + " · ".join(bits))
    if d.get("arms"):
        st.markdown("**Arms / conditions**")
        for a in d["arms"]:
            st.write(f"- **{a.get('name','')}** — {a.get('purpose', a.get('description',''))}")
    ctrls = d.get("controls", {}) or {}
    if any(ctrls.values()):
        st.markdown("**Controls**")
        for k in ("positive", "negative", "non_targeting", "technical"):
            if ctrls.get(k):
                st.write(f"- _{k.replace('_',' ')}:_ " + "; ".join(ctrls[k]))
    v = d.get("variables", {}) or {}
    if any(v.values()):
        st.markdown("**Variables**")
        for k in ("independent", "dependent_readouts", "controlled"):
            if v.get(k):
                st.write(f"- _{k.replace('_',' ')}:_ " + ", ".join(v[k]))
    rep = d.get("replicates", {}) or {}
    if rep:
        st.markdown(f"**Replication & power.** biological: {rep.get('biological','?')}, "
                    f"technical: {rep.get('technical','?')}. {rep.get('power_note','')}")
    if d.get("confounds_to_control"):
        st.markdown("**Confounds to control:** " + "; ".join(d["confounds_to_control"]))
    if d.get("validation_assays"):
        st.markdown("**Validation / readout assays — how the result is proven**")
        for va in d["validation_assays"]:
            st.markdown(f"- **{va.get('name','')}** — {va.get('rationale','')}")
            if va.get("method"):
                st.caption(f"Method: {va['method']}")
            exp = va.get("expected_results") or {}
            if isinstance(exp, dict) and exp:
                st.caption("Expected: " + "; ".join(f"**{k}** → {v}" for k, v in exp.items()))
            elif exp:
                st.caption(f"Expected: {exp}")
            if va.get("provenance"):
                st.caption(f"Source: {va['provenance']}")
    if d.get("phases"):
        st.markdown("**Phased plan**")
        for p in d["phases"]:
            st.write(f"- **{p.get('phase','')}** — {p.get('goal','')}")
    if d.get("protocol_outline"):
        st.markdown("**Suggested protocol outline**")
        for s in d["protocol_outline"]:
            st.write(f"- **{s.get('stage','')}** — {s.get('summary','')}")
    if d.get("readouts"):
        st.markdown("**Readouts:** " + ", ".join(d["readouts"]))
    if d.get("risks"):
        st.markdown("**Risks:** " + "; ".join(d["risks"]))
    if d.get("open_questions"):
        st.markdown("**Open questions**")
        for q in d["open_questions"]:
            st.write(f"- {q}")
    st.divider()
    if d.get("protocol_outline") and st.button("→ Generate a protocol from this design",
                                               key="design_to_proto", type="primary"):
        proto = _outline_to_protocol(d)
        normalize_protocol(proto)
        stub = {"agent": "Experiment Designer", "status": "success",
                "protocol_title": proto["protocol_title"], "assay_type": proto.get("assay_type", ""),
                "source_file": "designed_from_goal", "summary": proto.get("summary", ""),
                "materials": [], "equipment": [], "sample_requirements": [],
                "major_steps": [s["title"] for s in proto["workflow"]],
                "safety_notes": [], "uncertain_fields": []}
        _install_protocol(proto, stub, "designed_from_goal")


def _render_guides(g: dict):
    if g.get("mode") == "offline":
        st.caption("Offline guidance — run live for target-specific criteria.")
    lib = g.get("library_detected", {}) or {}
    if g.get("library_summary"):
        st.markdown(f"**Library status.** {g['library_summary']}")
    elif lib.get("n_genes"):
        st.markdown(f"**Library status.** {lib['n_genes']} gene(s) designed"
                    + (f", {lib['n_oligos']} oligos" if lib.get("n_oligos") else "")
                    + (f" (from {lib['source']})" if lib.get("source") else "") + ".")
    for label, key in (("Design criteria", "criteria"), ("Position rules", "position_rules"),
                       ("Off-target checklist", "off_target_checklist"),
                       ("Ordering checklist", "ordering_checklist")):
        if g.get(key):
            st.markdown(f"**{label}**")
            for x in g[key]:
                st.write(f"- {x}")
    if g.get("pairing_scheme"):
        st.markdown(f"**Pairing scheme.** {g['pairing_scheme']}")
    if g.get("oligo_architecture"):
        st.markdown(f"**Oligo architecture.** {g['oligo_architecture']}")
    if g.get("notes"):
        st.caption(g["notes"])


def _render_critique(c: dict):
    if c.get("mode") == "offline":
        st.caption("Offline heuristic review — run live for a full critique.")
    if c.get("summary"):
        st.markdown(f"**Overall.** {c['summary']}")
    sev = {"high": ":red[HIGH]", "medium": ":orange[MED]", "low": ":grey[LOW]"}
    for f in c.get("findings", []) or []:
        st.markdown(f"{sev.get(f.get('severity','low'),'•')} **{f.get('category','').title()}** — "
                    f"{f.get('issue','')}")
        if f.get("fix"):
            st.caption(f"Fix: {f['fix']}")
    if c.get("strengths"):
        st.markdown("**Strengths**")
        for s in c["strengths"]:
            st.write(f"- {s}")


def page_projects():
    hero("Projects", "Group what you're working on — experiments and reference docs — reload anytime, "
         "build an onboarding brief, and draft a Methods section.")

    # create
    with st.expander("New project", expanded=not proj.list_projects()):
        nm = st.text_input("Project name", key="proj_new_name",
                          placeholder="e.g. Single-cell CUT&Tag — cell line A")
        if st.button("Create project", key="proj_create"):
            if nm.strip():
                slug = proj.create_project(nm.strip())
                st.session_state.current_project = slug
                st.success(f"Created '{nm.strip()}'.")
                st.rerun()
            else:
                st.error("Enter a name.")

    projects = proj.list_projects()
    if not projects:
        st.info("No projects yet. Create one above, or use **Save to project** on the Protocol page.")
        return

    slugs = [p["slug"] for p in projects]
    names = [f"{p['name']}  ·  {p['n_experiments']} exp" for p in projects]
    default_idx = slugs.index(st.session_state.current_project) if st.session_state.current_project in slugs else 0
    pick = st.selectbox("Project", range(len(projects)), index=default_idx,
                        format_func=lambda i: names[i], key="proj_pick")
    slug = slugs[pick]
    st.session_state.current_project = slug

    exps = proj.list_experiments(slug)
    metric_cards([
        ("Experiments", str(len(exps))),
        ("Worked", str(sum(1 for e in exps if e["status"] == "worked"))),
        ("In progress", str(sum(1 for e in exps if e["status"] == "in_progress"))),
        ("Failed", str(sum(1 for e in exps if e["status"] == "failed"))),
    ])

    # Onboarding brief first — what a new student should read on opening the project
    try:
        _mem = proj.get_project_memory(slug)
    except Exception:
        _mem = {}
    _brief_entry = _mem.get("brief")
    if _brief_entry and isinstance(_brief_entry.get("value"), dict):
        b = dict(_brief_entry["value"]); b["_cached"] = _brief_entry.get("saved_at", "")
        with st.expander("Project brief — start here (onboarding)", expanded=True):
            st.caption("Auto-generated onboarding brief for this project — summary, what to learn, "
                       "literature, consistency check, and the protocol plan.")
            _render_brief(b)
    else:
        st.info("No onboarding brief yet. Load an experiment below, open **Learn**, and click "
                "**Build project brief** — it's then cached here for anyone who opens this project.")

    if not exps:
        st.caption("No experiments saved here yet. Save one from the Protocol page.")
        return

    for e in exps:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{e['title']}**  ({e['version']})  "
                            + _status_badge(e["status"]), unsafe_allow_html=True)
                meta = f"{e['n_steps']} steps · {e['assay_type'] or '—'} · saved {e['saved_at'][:10]}"
                st.caption(meta)
                if e["notes"]:
                    st.write(f"{e['notes']}")
            with c2:
                if st.button("Reload", key=f"reload_{e['exp_id']}", use_container_width=True):
                    load_project_experiment(slug, e["exp_id"])
                if st.button("Delete", key=f"delexp_{e['exp_id']}", use_container_width=True,
                             help="Delete this experiment"):
                    proj.delete_experiment(slug, e["exp_id"])
                    log_event("experiment_deleted", {"project": slug, "exp_id": e["exp_id"]})
                    st.rerun()

    with st.expander("Delete this project"):
        st.warning("Permanently removes this project and all its experiments.")
        if st.checkbox("Yes, I'm sure", key=f"delproj_confirm_{slug}"):
            if st.button("Delete project permanently", key=f"delproj_{slug}", type="primary"):
                proj.delete_project(slug)
                st.session_state.current_project = ""
                log_event("project_deleted", {"project": slug})
                st.success("Project deleted.")
                st.rerun()

    st.divider()
    st.markdown("### Document for paper writing")
    st.caption("Drafts a Methods section from this project's experiments and reference "
               "documents. It writes only from recorded values and the documents below.")

    # --- Reference/source documents: add at ANY stage, no re-run needed --------
    proj_sources = proj.get_project_sources(slug)
    with st.expander(f"Reference documents for Methods ({len(proj_sources)}) — "
                     "add background, onboarding, papers, kit manuals", expanded=not proj_sources):
        st.caption("Drop in any file that carries context the protocol may not — e.g. a "
                   "parental cell-line genotype (KRAB-Cas9-mCherry), antibody clones, catalog "
                   "numbers, or a gRNA-library / oligo-order spreadsheet (.xlsx/.csv) so the "
                   "agents know your gene targets. The Methods writer reads these before "
                   "drafting. Saved with the project.")
        up = st.file_uploader("Upload reference document(s)",
                              type=["pdf", "docx", "txt", "md", "xlsx", "xls", "csv"],
                              accept_multiple_files=True, key="proj_src_upload")
        if up and st.button("Add to project", key="proj_src_add"):
            new_docs = []
            for f in up:
                try:
                    txt = extract_text(path="", raw_bytes=f.getvalue(), file_name=f.name)
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Couldn't read {f.name}: {exc}")
                    continue
                if not txt or not txt.strip():
                    st.warning(f"{f.name}: no extractable text (scanned image?). Skipped.")
                    continue
                try:
                    dtype = classify_doc(txt, f.name)
                except Exception:
                    dtype = "reference"
                new_docs.append({"name": f.name, "title": f.name, "doc_type": dtype, "text": txt})
            if new_docs:
                proj.add_project_sources(slug, new_docs)
                log_event("project_sources_added", {"project": slug, "n": len(new_docs)})
                st.success(f"Added {len(new_docs)} document(s).")
                st.rerun()
        for d in proj_sources:
            cols = st.columns([6, 1])
            cols[0].markdown(f"- **[{d.get('doc_type','ref')}]** {d.get('title','')} "
                             f"· {len(d.get('text',''))} chars")
            if cols[1].button("", key=f"rmsrc_{d.get('name','')}_{d.get('title','')}"):
                proj.remove_project_source(slug, d.get("name", ""), d.get("title", ""))
                st.rerun()

    mc1, mc2 = st.columns(2)
    style = mc1.selectbox(
        "Journal / style",
        ["High-impact (Nature/Cell) Methods voice",
         "Molecular biology / Bio-protocol detailed style",
         "Brief Methods summary (supplementary-style)"],
        key="methods_style")
    length = mc2.selectbox(
        "Length", ["Concise but reproducible", "Detailed", "Very brief"],
        key="methods_length")
    if st.button("Generate Methods writeup", type="primary"):
        full = proj.full_experiments(slug)
        pname = next((p["name"] for p in projects if p["slug"] == slug), slug)
        with st.spinner("Methods Writer: drafting…"):
            res = MethodsAgent().write(full, project_name=pname, style=style, length=length,
                                       extra_documents=proj.get_project_sources(slug))
        st.session_state.methods_md = res.get("markdown") if res.get("status") == "success" \
            else f"(error: {res.get('error')})"
        log_event("methods_generated", {"project": slug})
        st.rerun()

    if st.session_state.methods_md:
        st.markdown(st.session_state.methods_md)
        st.download_button("⬇ Methods (.md)", st.session_state.methods_md,
                           file_name=f"methods_{slug}.md", mime="text/markdown")


def inject_theme():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
        :root {
          --accent:#5B4FE0; --accent-2:#7A6FF0; --accent-soft:#EFEDFD;
          --ink:#15181F; --ink-soft:#3F4451; --muted:#6B7280;
          --card:#FFFFFF; --border:#ECECF1; --bg:#FCFCFD;
          --pill:#F3F4F7; --pill-hover:#E9EBF1;
          --ok:#15803D; --ok-bg:#E9F7EF; --warn:#B45309; --warn-bg:#FDF4E7;
          --info-bg:#EEF1FF;
          --font:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          --radius:16px;
        }
        /* base surfaces — light, airy, near-white (consensus-style) */
        .stApp { background: var(--bg); }
        [data-testid="stHeader"] { background: transparent !important; }
        .block-container { padding-top: 1.1rem; padding-bottom: 3rem;
          max-width: none; padding-left: 2.5rem; padding-right: 2.5rem; }  /* full-width */
        html, body, .stApp {
          font-family: var(--font) !important;
          -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
        }
        [data-testid="stMarkdownContainer"], .stMarkdown, p, li, label, .stText,
        .stTextInput input, .stTextArea textarea, .stNumberInput input,
        .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
          font-family: var(--font) !important;
          color: var(--ink) !important;
          font-size: 15px; line-height: 1.6;
        }
        /* never override Streamlit's Material icon fonts (chevrons, arrows, etc.) */
        [data-testid="stIconMaterial"], .material-icons, .material-symbols-outlined,
        .material-symbols-rounded, span[class*="material-symbols"], i[class*="material-"] {
          font-family: 'Material Symbols Outlined','Material Symbols Rounded','Material Icons' !important;
          font-size: 1.25rem !important; line-height: 1 !important;
        }
        h1,h2,h3,h4,h5 { font-family:var(--font) !important; color: var(--ink) !important;
          letter-spacing:-0.02em; font-weight:700; }
        h1 { font-weight: 800; font-size: 1.85rem; margin-bottom:.2rem; }
        h2 { font-size: 1.35rem; font-weight:750; }
        h3 { font-size: 1.12rem; font-weight:700; }
        a, a:visited { color: var(--accent) !important; text-decoration: none; }
        a:hover { text-decoration: underline; }
        /* captions / secondary text: muted but still readable */
        [data-testid="stCaptionContainer"], .stCaption, small {
          color: var(--muted) !important; font-size: 13px !important;
        }
        /* buttons — soft gray pill secondary (consensus-style) */
        .stButton > button, .stDownloadButton > button {
          border-radius: 10px !important; font-weight: 600 !important;
          border: 1px solid transparent !important; background: var(--pill) !important;
          color: var(--ink-soft) !important; transition: background .12s ease, color .12s ease;
          box-shadow: none !important; min-height: 40px; padding: 6px 14px !important;
        }
        .stButton > button:hover { background: var(--pill-hover) !important;
          color: var(--ink) !important; transform: none; border-color: transparent !important; }
        /* nav tab bar — clean pill segmented control (scoped via :has marker) */
        .lab-navlabel { font-size:.66rem; font-weight:800; letter-spacing:.12em;
          color:var(--muted); margin:0 0 7px 2px; }
        .lab-nav-marker { display:none; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) {
          background:#FFFFFF; padding:7px 9px !important; box-shadow:0 1px 2px rgba(16,24,40,.04);
          border:1px solid var(--border) !important; border-radius:14px !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button {
          min-height:42px; font-size:12px; font-weight:600 !important;
          border:1px solid transparent !important; background:transparent !important;
          color:var(--ink-soft) !important; border-radius:9px !important; box-shadow:none !important;
          padding:6px 4px !important; white-space:nowrap !important; }
        /* keep nav labels on ONE line — never break mid-word */
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button p,
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button div,
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button span {
          white-space:nowrap !important; overflow-wrap:normal !important; word-break:keep-all !important;
          margin:0 !important; overflow:hidden; text-overflow:ellipsis; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button:hover {
          background:var(--accent-soft) !important; color:var(--accent) !important; transform:none; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) button[kind="primary"],
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) [data-testid="stBaseButton-primary"] {
          background:var(--accent) !important; color:#fff !important;
          box-shadow:0 2px 8px rgba(91,79,224,.28) !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-nav-marker) .stButton > button:disabled {
          opacity:.4 !important; }
        /* collapse the invisible nav marker's element slot so the pills are vertically centered */
        [data-testid="stElementContainer"]:has(.lab-nav-marker),
        [data-testid="stElementContainer"]:has(.lab-ws-marker) {
          display:none !important; height:0 !important; margin:0 !important; }
        /* in a started run, drop the borderless WORKSPACE pills down by the
           WORKFLOW box's top padding so both tab rows sit on the same level */
        [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .lab-ws-aligned) {
          padding-top:16px !important; }
        /* ROBUST no-wrap for every nav pill (workflow + workspace), keyed per button */
        [class*="st-key-nav_"] button { padding-left:6px !important; padding-right:6px !important; }
        [class*="st-key-nav_"] button p, [class*="st-key-nav_"] button div,
        [class*="st-key-nav_"] button span {
          white-space:nowrap !important; overflow-wrap:normal !important; word-break:keep-all !important;
          margin:0 !important; text-overflow:ellipsis; overflow:hidden; }
        /* WORKSPACE group — no box, just free-standing pills */
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) {
          background:transparent !important; padding:0 !important; border:none !important;
          border-radius:0 !important; box-shadow:none !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) .stButton > button {
          min-height:50px; font-size:13px; font-weight:650 !important;
          background:#F4F4FB !important; border:1px solid transparent !important;
          color:var(--ink) !important; border-radius:13px !important; box-shadow:none !important;
          transition:background .12s ease, transform .12s ease; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) .stButton > button p {
          white-space:nowrap !important; margin:0 !important; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) .stButton > button:hover {
          background:var(--accent-soft) !important; color:var(--accent) !important; transform:translateY(-1px); }
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) button[kind="primary"],
        [data-testid="stVerticalBlockBorderWrapper"]:has(> div .lab-ws-marker) [data-testid="stBaseButton-primary"] {
          background:linear-gradient(100deg,#6E61F0,#9A86F6) !important; color:#fff !important; border:none !important;
          box-shadow:0 6px 16px rgba(110,97,240,.30) !important; }
        /* WORKSPACE pills (no box) — clean white, accent icon, springy hover */
        .st-key-nav_projects button, .st-key-nav_learn button {
          min-height:52px !important; background:#FFFFFF !important; color:var(--ink) !important;
          border:1px solid var(--border) !important; border-radius:16px !important;
          font-weight:700 !important; font-size:13.5px !important;
          box-shadow:0 1px 2px rgba(16,24,40,.04) !important;
          transition:transform .16s cubic-bezier(.34,1.56,.64,1), box-shadow .16s ease, background .12s ease !important;
          display:flex !important; align-items:center !important; justify-content:center !important; }
        .st-key-nav_projects button:hover, .st-key-nav_learn button:hover {
          background:var(--accent-soft) !important; border-color:#DAD5FB !important;
          transform:translateY(-2px) scale(1.02); box-shadow:0 8px 20px rgba(91,79,224,.16) !important; }
        .st-key-nav_projects button:active, .st-key-nav_learn button:active {
          transform:translateY(0) scale(.98); }
        /* icon always accent-tinted (not just on hover) */
        .st-key-nav_projects button::before, .st-key-nav_learn button::before {
          background-color: var(--accent) !important; }
        /* active (selected) workspace tab = purple bg → icon turns white for contrast */
        .st-key-nav_projects button[kind="primary"]::before,
        .st-key-nav_learn button[kind="primary"]::before,
        .st-key-nav_projects [data-testid="stBaseButton-primary"]::before,
        .st-key-nav_learn [data-testid="stBaseButton-primary"]::before {
          background-color: #FFFFFF !important; }
        /* clickable brand → Home: invisible button overlaying the logo/name */
        [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .lab-brand) {
          position: relative !important; }
        .st-key-brand_home { position:absolute !important; top:0; left:0; right:0;
          height:58px; margin:0 !important; z-index:6; }
        .st-key-brand_home button { width:100% !important; height:58px !important;
          min-height:0 !important; opacity:0 !important; cursor:pointer !important;
          padding:0 !important; border:none !important; background:transparent !important; }
        /* hidden per-step jump buttons driven by clicks on the workflow chart nodes */
        [class*="st-key-chartjump_"] { display:none !important; }
        .st-key-nav_projects button p, .st-key-nav_learn button p { margin:0 !important; }
        /* + New run — same height/level as Projects & Learn, keep the accent gradient */
        .st-key-nav_newrun button {
          min-height:52px !important; border-radius:16px !important;
          font-weight:750 !important; font-size:13.5px !important;
          background:linear-gradient(100deg,#6E61F0,#9A86F6) !important; color:#fff !important;
          border:none !important; box-shadow:0 6px 16px rgba(110,97,240,.30) !important;
          display:flex !important; align-items:center !important; justify-content:center !important;
          transition:transform .16s cubic-bezier(.34,1.56,.64,1), box-shadow .16s ease !important; }
        .st-key-nav_newrun button:hover {
          transform:translateY(-2px) scale(1.02);
          box-shadow:0 10px 24px rgba(110,97,240,.42) !important; }
        .st-key-nav_newrun button p { margin:0 !important; color:#fff !important; }
        /* keep all 4 workspace pills readable in narrow windows (no "Pr…/Le…") */
        .st-key-nav_newrun button, .st-key-nav_design button,
        .st-key-nav_projects button, .st-key-nav_learn button {
          font-size:12px !important; padding-left:4px !important; padding-right:4px !important; }
        .st-key-nav_projects button::before, .st-key-nav_learn button::before {
          width:15px !important; height:15px !important; margin-right:5px !important; }
        /* sub-tabs (Project summary / Literature / Learn) — roomier spacing */
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap:26px !important; }
        [data-testid="stTabs"] button[data-baseweb="tab"] { padding-left:2px !important; padding-right:2px !important; }
        .st-key-nav_projects button::before, .st-key-nav_learn button::before {
          content:""; width:19px; height:19px; margin-right:9px; flex:0 0 auto;
          background-color: currentColor;
          -webkit-mask: center/contain no-repeat var(--ic); mask: center/contain no-repeat var(--ic); }
        .st-key-nav_projects button { --ic: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linejoin='round'%3E%3Cpath%20d='M3%207a2%202%200%200%201%202-2h4l2%202h8a2%202%200%200%201%202%202v8a2%202%200%200%201-2%202H5a2%202%200%200%201-2-2z'/%3E%3C/svg%3E"); }
        .st-key-nav_learn button { --ic: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='black'%20stroke-width='1.8'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M22%2010%2012%205%202%2010l10%205z'/%3E%3Cpath%20d='M6%2012v5c3%202%209%202%2012%200v-5'/%3E%3C/svg%3E"); }
        button[kind="primary"], [data-testid="baseButton-primary"],
        [data-testid="stBaseButton-primary"], .stFormSubmitButton > button {
          background: var(--accent) !important; border: 1px solid var(--accent) !important;
          color: #FFFFFF !important; box-shadow: 0 3px 10px rgba(91,79,224,.25) !important;
        }
        button[kind="primary"] *, [data-testid="baseButton-primary"] * { color:#fff !important; }
        /* cute, playful Start button — gradient, lift on hover, shine slide */
        .st-key-nav_start_btn button, .st-key-landing_start button {
          background: linear-gradient(100deg,#6E61F0 0%, #8B7BF5 55%, #9A86F6 100%) !important;
          border: none !important; color:#fff !important; border-radius: 16px !important;
          font-weight: 750 !important; min-height: 52px !important; font-size: 14.5px !important;
          position: relative; overflow: hidden;
          box-shadow: 0 8px 22px rgba(110,97,240,.34) !important;
          transition: transform .16s cubic-bezier(.34,1.56,.64,1), box-shadow .16s ease !important;
        }
        .st-key-nav_start_btn button:hover, .st-key-landing_start button:hover {
          transform: translateY(-2px) scale(1.025);
          box-shadow: 0 12px 30px rgba(110,97,240,.46) !important;
        }
        .st-key-nav_start_btn button:active, .st-key-landing_start button:active {
          transform: translateY(0) scale(.98); }
        .st-key-nav_start_btn button::after, .st-key-landing_start button::after {
          content:""; position:absolute; top:0; left:-65%; width:45%; height:100%;
          background: linear-gradient(120deg, transparent, rgba(255,255,255,.5), transparent);
          transform: skewX(-20deg); transition: left .55s ease; pointer-events:none; }
        .st-key-nav_start_btn button:hover::after, .st-key-landing_start button:hover::after {
          left: 130%; }
        /* inputs: white fill + visible border so fields are clearly visible */
        .stTextInput input, .stTextArea textarea, .stNumberInput input,
        [data-baseweb="input"], [data-baseweb="textarea"],
        [data-baseweb="select"] > div, [data-baseweb="base-input"] {
          background: #FFFFFF !important;
          border: 1px solid #CFCFE0 !important;
          border-radius: 10px !important;
          color: var(--ink) !important;
        }
        .stTextInput input::placeholder, .stTextArea textarea::placeholder {
          color: #9AA0AE !important;
        }
        .stTextInput input:focus, .stTextArea textarea:focus {
          border-color: var(--accent) !important;
          box-shadow: 0 0 0 2px rgba(91,79,224,.15) !important;
        }
        /* labels above inputs */
        [data-testid="stWidgetLabel"] label, .stTextInput label, .stTextArea label,
        .stNumberInput label, .stSelectbox label, .stMultiSelect label {
          color: var(--ink-soft) !important; font-weight: 600 !important;
        }
        /* bordered containers -> clean, airy cards */
        [data-testid="stVerticalBlockBorderWrapper"] {
          border-radius: 18px !important; border:1px solid var(--border) !important;
          background: var(--card); box-shadow: 0 1px 2px rgba(16,24,40,.03);
          padding: 8px 12px;
        }
        /* alerts: soft, readable */
        [data-testid="stAlert"] { border-radius: 12px !important; border:1px solid var(--border) !important; }
        /* expanders + tabs */
        [data-testid="stExpander"] { border-radius: 12px !important; border:1px solid var(--border) !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 4px; }
        .stTabs [aria-selected="true"] { color: var(--accent) !important; }
        /* dataframe */
        [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border:1px solid var(--border); }
        /* sidebar */
        [data-testid="stSidebar"] { background:#FBFBFE; border-right:1px solid var(--border); }
        [data-testid="stSidebar"] * { color: var(--ink) !important; }
        [data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
        .lab-brand { display:flex; align-items:center; gap:11px; margin-bottom:14px; }
        .lab-brand-icon { width:40px; height:40px; border-radius:12px; flex:0 0 auto;
          background:linear-gradient(135deg,var(--accent),#8B7BF5); color:#fff;
          display:flex; align-items:center; justify-content:center; font-size:20px;
          box-shadow:0 4px 12px rgba(91,79,224,.30); }
        .lab-brand-name { font-weight:800; font-size:1.05rem; line-height:1.15; color:var(--ink); }
        .lab-brand-sub { font-size:11.5px; color:var(--muted); }
        .lab-status { display:inline-flex; align-items:center; gap:7px; font-size:12px;
          font-weight:700; padding:6px 12px; border-radius:999px; margin:2px 0 14px; }
        .lab-status .dot { width:8px; height:8px; border-radius:50%; }
        .lab-status.on  { background:#E9F7EF; color:#15803D; }
        .lab-status.on .dot { background:#22C55E; }
        .lab-status.live{ background:var(--accent-soft); color:var(--accent); }
        .lab-status.live .dot { background:var(--accent); }
        .lab-section { font-size:10.5px; font-weight:800; letter-spacing:.1em;
          text-transform:uppercase; color:var(--muted); margin:14px 0 8px; }
        .lab-model { display:flex; align-items:center; justify-content:space-between;
          background:#fff; border:1px solid var(--border); border-radius:10px;
          padding:8px 11px; margin-bottom:7px; }
        .lab-model .tier { font-size:11px; font-weight:800; text-transform:uppercase;
          letter-spacing:.04em; }
        .lab-model .tier.s { color:var(--accent); }
        .lab-model .tier.c { color:#0E9488; }
        .lab-model .name { font-size:11.5px; color:var(--ink-soft);
          font-family:ui-monospace,Menlo,monospace; }
        .lab-run { display:flex; align-items:center; gap:8px; font-size:12px;
          color:var(--ink-soft); padding:6px 9px; border-radius:8px; margin-bottom:3px;
          background:#fff; border:1px solid var(--border); }
        /* hero — compact card with an accent rail (calmer than full gradient) */
        .lab-hero { position:relative; background:var(--card);
          border:1px solid var(--border); border-left:4px solid var(--accent);
          border-radius:var(--radius); padding:15px 20px; margin-bottom:18px;
          box-shadow:0 1px 2px rgba(16,24,40,.04); }
        .lab-hero h1 { color:var(--ink) !important; font-size:1.4rem; margin:0; font-weight:800;
          letter-spacing:-0.02em; }
        .lab-hero p { color:var(--muted) !important; margin:5px 0 0; font-size:13.5px; line-height:1.5; }
        /* consistent section heading (matches hero typography, smaller) */
        .lab-sec { color:var(--ink); font-size:1.15rem; font-weight:800; letter-spacing:-0.02em;
          margin:2px 0 4px; line-height:1.3; }
        /* custom metric cards */
        .lab-metrics { display:flex; gap:14px; flex-wrap:wrap; margin:8px 0 14px; }
        .lab-metric { flex:1; min-width:150px; background:var(--card);
          border:1px solid var(--border); border-radius:16px; padding:16px 18px;
          box-shadow:0 1px 3px rgba(16,24,40,.05); }
        .lab-metric-label { font-size:.72rem; color:var(--muted); font-weight:700;
          text-transform:uppercase; letter-spacing:.05em; }
        .lab-metric-value { font-size:1.85rem; font-weight:800; line-height:1.1;
          margin-top:6px; color:var(--ink); }
        .lab-metric-sub { font-size:.74rem; color:var(--muted); margin-top:4px; }
        .lab-metric.accent { background:linear-gradient(135deg,var(--accent) 0%,var(--accent-2) 100%);
          border:none; box-shadow:0 6px 18px rgba(91,79,224,.28); }
        .lab-metric.accent .lab-metric-label { color:#E7E4FF; }
        .lab-metric.accent .lab-metric-value, .lab-metric.accent .lab-metric-sub { color:#fff; }
        /* chat bubbles (fallback path) */
        .lab-chat { background:var(--card); border:1px solid var(--border);
          border-radius:14px; padding:8px 12px; margin:6px 0; }
        .lab-chat.user { background:var(--accent-soft); border-color:#DAD5FB; }
        .lab-chat .role { font-size:.7rem; font-weight:800; color:var(--accent);
          text-transform:uppercase; letter-spacing:.05em; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = ""):
    st.markdown(
        f'<div class="lab-hero"><h1>{title}</h1>'
        + (f"<p>{subtitle}</p>" if subtitle else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def render_workflow_chart(proto: dict):
    """Live workflow diagram built from the current steps (Mermaid, rendered in-app).
    It mirrors the protocol exactly — reorder/edit/split/delete steps in the list below
    and the chart updates on the next rerun. Exportable as .json / .mmd below."""
    import streamlit.components.v1 as components
    from tools.protocol_check import to_mermaid, to_structured
    wf = proto.get("workflow", []) or []
    if not wf:
        return
    with st.expander("Workflow chart (live — click a node to open that step)", expanded=True):
        # Worded explanation of the experiment + its flow (moved here from a separate panel)
        ce = proto.get("core_experiment")
        if ce:
            st.markdown(f"**What this runs:** {ce}")
        titles = [str(s.get("title", "")).strip() for s in wf if s.get("title")]
        if titles:
            st.markdown("**Flow:** " + "  →  ".join(titles))
        dr = proto.get("design_rationale")
        if dr:
            st.caption(dr)
        rr = proto.get("redundancies_resolved")
        if rr:
            st.caption("Redundancies resolved: " + "; ".join(str(r) for r in rr))
        if ce or titles or dr or rr:
            st.divider()
        st.caption("Auto-built from your steps. Click any node to jump to that step.")
        # hidden per-step buttons: a node click in the chart triggers the matching button
        # (same-origin iframe → no page reload, session state preserved).
        for _i in range(1, len(wf) + 1):
            if st.button("jump", key=f"chartjump_{_i}"):
                st.session_state.bench_idx = _i - 1
                st.session_state.page = "bench"
                st.rerun()
        import json as _json
        code = to_mermaid(proto)
        height = min(1500, 120 + len(wf) * 60)
        code_js = _json.dumps(code)  # safe JS string
        html = (
            '<style>.mermaid{display:flex;justify-content:center;}'
            '.mermaid svg{max-width:100%!important;height:auto!important;}</style>'
            '<div style="background:#fff;border-radius:10px;padding:10px;font-family:sans-serif;">'
            '<div class="mermaid"></div>'
            '<div id="mmerr" style="color:#b91c1c;font-size:12px;"></div></div>'
            '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>'
            '<script>'
            f'var CODE={code_js};'
            'mermaid.initialize({startOnLoad:false,theme:"neutral",securityLevel:"loose",'
            'flowchart:{useMaxWidth:true,htmlLabels:false,nodeSpacing:28,rankSpacing:32}});'
            'function wire(){document.querySelectorAll(".mermaid .node").forEach(function(n){'
            'var m=(n.id||"").match(/S(\\d+)/);if(!m)return;n.style.cursor="pointer";'
            'n.onclick=function(){try{var b=window.top.document.querySelector('
            '".st-key-chartjump_"+m[1]+" button");if(b)b.click();}catch(e){}};});}'
            'function draw(){var el=document.querySelector(".mermaid");if(!el||el.clientWidth<10){return;}'
            'el.removeAttribute("data-processed");el.innerHTML=CODE;'
            'try{mermaid.run({querySelector:".mermaid"}).then(wire);}'
            'catch(e){document.getElementById("mmerr").textContent="chart error: "+e.message;}}'
            'if(document.fonts&&document.fonts.ready){document.fonts.ready.then(draw);}'
            'setTimeout(draw,250);setTimeout(draw,800);'
            'var _t;window.addEventListener("resize",function(){clearTimeout(_t);_t=setTimeout(draw,150);});'
            '</script>'
        )
        components.html(html, height=height, scrolling=True)
        # machine-readable export (typed steps + workflow graph) — human + machine + AI readable
        ec1, ec2 = st.columns(2)
        ec1.download_button(
            "⬇ Structured (.json)",
            data=json.dumps(to_structured(proto), ensure_ascii=False, indent=2),
            file_name=f"{(proto.get('protocol_title','protocol')[:40] or 'protocol').replace(' ','_')}_structured.json",
            mime="application/json", key="dl_structured", use_container_width=True)
        ec2.download_button(
            "⬇ Graph (.mmd)", data=to_mermaid(proto),
            file_name="workflow_graph.mmd", mime="text/plain",
            key="dl_mermaid", use_container_width=True)


def render_chat(current_step=None, key="chat"):
    """Reusable AI chat panel scoped to the current protocol."""
    st.markdown("#### Ask the AI about this protocol")
    _clvl = (st.session_state.input_meta or {}).get(
        "experience_level", st.session_state.get("user_level", "intermediate"))
    st.caption(f"Guidance pitched for **{_level_label(_clvl)}** — change it in the sidebar.")
    if DEMO_MODE:
        st.caption("Offline mode: answers are drawn from the loaded protocol. "
                   "Set DEMO_MODE=false + API key for full conversational Q&A (Haiku).")
    has_chat_msg = hasattr(st, "chat_message")
    for msg in st.session_state.chat_history[-12:]:
        is_user = msg.get("role") == "user"
        if has_chat_msg:
            with st.chat_message("user" if is_user else "assistant"):
                st.markdown(msg.get("content", ""))
        else:
            st.markdown(f'<div class="lab-chat {"user" if is_user else ""}">'
                        f'<div class="role">{"You" if is_user else "Assistant"}</div></div>',
                        unsafe_allow_html=True)
            st.markdown(msg.get("content", ""))

    with st.form(key + "_form", clear_on_submit=True):
        q = st.text_input("Your question", key=key + "_q",
                          placeholder="e.g. spin speed for step 5?  ·  how much Buffer P2?  ·  what if low yield?")
        sent = st.form_submit_button("Ask")
    if sent and q.strip():
        st.session_state.chat_history.append({"role": "user", "content": q.strip()})
        _lvl = (st.session_state.input_meta or {}).get(
            "experience_level", st.session_state.get("user_level", "intermediate"))
        with st.spinner("Thinking…"):
            res = ChatAgent().ask(q.strip(), st.session_state.protocol,
                                  st.session_state.chat_history, current_step, level=_lvl)
        ans = res.get("answer") if res.get("status") == "success" \
            else f"(couldn't answer: {res.get('error')})"
        st.session_state.chat_history.append({"role": "assistant", "content": ans})
        log_event("chat", {"q": q.strip(), "mode": res.get("mode")})
        st.rerun()

    # If the user's last message was a correction ("this is X not Y", "we use…"),
    # let them turn it into a logged protocol revision in one click.
    last_user = next((m for m in reversed(st.session_state.chat_history)
                      if m.get("role") == "user"), None)
    if last_user:
        st.caption("Spotted a mistake in the protocol above? Turn your last "
                   "message into a tracked revision (new version, change log).")
        if st.button("Apply my last message as a protocol revision",
                     key=key + "_apply", use_container_width=True):
            ok = apply_correction(last_user.get("content", ""),
                                  st.session_state.chat_history)
            if ok:
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "Applied as a new protocol version — see the "
                               "revision banner and updated steps above.",
                })
            st.rerun()

    _render_correction_flash()

    if st.session_state.chat_history:
        if st.button("Clear chat", key=key + "_clear"):
            st.session_state.chat_history = []
            st.rerun()


def _render_audit(res):
    """Render consistency-audit findings (redundancy / contradiction / logic)."""
    if not res:
        return
    if res.get("status") != "success":
        st.error(res.get("error", "Audit failed."))
        return
    findings = res.get("findings", []) or []
    if not findings:
        st.success("No redundancy or contradictions flagged. ")
        if res.get("summary"):
            st.caption(res["summary"])
        return
    c = res.get("counts", {}) or {}
    st.markdown(f"**{len(findings)} flag(s)** — "
                f"{c.get('high',0)} high · {c.get('medium',0)} medium · {c.get('low',0)} low")
    _icon = {"high": ":red[HIGH]", "medium": ":orange[MED]", "low": ":grey[LOW]"}
    _label = {"redundancy": "Redundant", "repetition": "Repeated",
              "contradiction": "Contradiction", "possible_contradiction": "Possible contradiction",
              "illogical_order": "Out-of-order", "false_logic": "False logic"}
    for f in findings:
        sev = f.get("severity", "low")
        typ = _label.get(f.get("type", ""), f.get("type", "issue").title())
        with st.container(border=True):
            st.markdown(f"{_icon.get(sev,'')} **{typ}** · _{f.get('where','')}_")
            st.write(f.get("issue", ""))
            if f.get("suggested_fix"):
                st.caption(f"Fix: {f['suggested_fix']}")
    if res.get("summary"):
        st.caption(res["summary"])
    if res.get("mode") == "offline":
        st.caption("Offline heuristic — run live for full contradiction/logic checking.")


def _render_correction_flash():
    """Show the result of the most recent apply_correction(), once."""
    flash = st.session_state.pop("_correction_flash", None)
    if not flash:
        return
    kind, data = flash
    if kind == "error":
        st.error(f"Couldn't apply the correction: {data}")
        return
    st.success(f"Revised {data['from']} → {data['to']} from your correction.")
    src = data.get("ref_source", "none")
    if src == "pasted/uploaded":
        st.caption("Rewrote steps from the reference protocol you provided.")
    elif src == "web":
        st.caption("Read the linked protocol and rewrote steps from it.")
    elif data.get("had_url"):
        st.warning("Couldn't read the linked page (live web search needs the "
                   "Anthropic provider + ANTHROPIC_API_KEY). Rewrote from your text only — "
                   "paste the real steps or upload the protocol file and re-apply for exact detail.")
    if data.get("diagnosis"):
        st.markdown(f"**What was wrong:** {data['diagnosis']}")
    if data.get("summary"):
        st.markdown(f"**Changes:** {data['summary']}")
    if data.get("changed"):
        st.caption("Changed steps: " + ", ".join(data["changed"]))


def render_calculators(key_prefix: str, default_tab: int = 0):
    """Reusable bench calculators: PCR, ligation, dilution, cell seeding."""
    t = st.tabs(["PCR", "Ligation", "Dilution", "Cell seeding"])
    with t[0]:
        pc1, pc2 = st.columns(2)
        fseq = pc1.text_input("Forward primer", key=f"{key_prefix}_pcr_f")
        rseq = pc2.text_input("Reverse primer", key=f"{key_prefix}_pcr_r")
        a, b, c = st.columns(3)
        amp = a.number_input("Amplicon bp", min_value=50, value=1000, step=50, key=f"{key_prefix}_pcr_amp")
        pol = b.selectbox("Polymerase", polymerases(), key=f"{key_prefix}_pcr_pol")
        conc = c.number_input("Primer µM", min_value=0.05, value=0.5, step=0.05, key=f"{key_prefix}_pcr_conc")
        if st.button("Design PCR", key=f"{key_prefix}_pcr_btn"):
            st.session_state[f"_pcr_{key_prefix}"] = design_pcr(fseq, rseq, int(amp), pol, conc)
        d = st.session_state.get(f"_pcr_{key_prefix}")
        if d and not d.get("error"):
            m = st.columns(4)
            m[0].metric("Tm F", f"{d['tm_forward']} °C"); m[1].metric("Tm R", f"{d['tm_reverse']} °C")
            m[2].metric("Anneal", f"{d['annealing_C']} °C"); m[3].metric("Extension", d["extension_time"])
            for line in d["cycling"]:
                st.write(f"- {line}")
        elif d:
            st.error(d["error"])
    with t[1]:
        l = st.columns(4)
        vng = l[0].number_input("Vector ng", min_value=0.0, value=50.0, key=f"{key_prefix}_l_vng")
        vbp = l[1].number_input("Vector bp", min_value=0.0, value=5000.0, key=f"{key_prefix}_l_vbp")
        ibp = l[2].number_input("Insert bp", min_value=0.0, value=1000.0, key=f"{key_prefix}_l_ibp")
        rr = l[3].number_input("Ratio I:V", min_value=0.1, value=3.0, step=0.5, key=f"{key_prefix}_l_r")
        if st.button("Insert ng", key=f"{key_prefix}_l_btn"):
            r = ligation_insert_ng(vng, vbp, ibp, rr)
            st.error(r["error"]) if r.get("error") else (st.metric("Insert", f"{r['insert_ng']} ng"), st.caption(r["explain"]))
    with t[2]:
        st.caption("Leave one field blank to solve it.")
        d = st.columns(4)
        c1 = d[0].text_input("C1", key=f"{key_prefix}_d_c1"); v1 = d[1].text_input("V1", key=f"{key_prefix}_d_v1")
        c2 = d[2].text_input("C2", key=f"{key_prefix}_d_c2"); v2 = d[3].text_input("V2", key=f"{key_prefix}_d_v2")
        if st.button("Solve", key=f"{key_prefix}_d_btn"):
            r = dilution(c1 or None, v1 or None, c2 or None, v2 or None)
            st.error(r["error"]) if r.get("error") else (st.metric(r["field"], r["result"]), st.caption(r["explain"]))
    with t[3]:
        s = st.columns(4)
        dens = s[0].number_input("Cells/well", min_value=1.0, value=200000.0, step=1000.0, key=f"{key_prefix}_s_d")
        vol = s[1].number_input("µL/well", min_value=1.0, value=200.0, key=f"{key_prefix}_s_v")
        nw = s[2].number_input("# wells", min_value=1, value=12, key=f"{key_prefix}_s_n")
        stock = s[3].number_input("Stock cells/mL", min_value=1.0, value=1000000.0, step=10000.0, key=f"{key_prefix}_s_s")
        if st.button("Seeding", key=f"{key_prefix}_s_btn"):
            r = cell_seeding(dens, vol, int(nw), stock)
            if r.get("error"):
                st.error(r["error"])
            else:
                mc = st.columns(3)
                mc[0].metric("Cells", f"{r['total_cells_needed']:,}")
                mc[1].metric("Stock µL", r["stock_to_add_uL"]); mc[2].metric("Medium µL", r["medium_to_add_uL"])
                st.caption(r["explain"])


def _suggested_calc(step: dict) -> int:
    """Pick the most relevant calculator tab for a step (0 PCR,1 lig,2 dil,3 seed)."""
    text = (step.get("title", "") + " " + " ".join(step.get("instructions", []) or [])).lower()
    if any(k in text for k in ("pcr", "amplif", "thermocycl", "anneal")):
        return 0
    if "ligat" in text:
        return 1
    if any(k in text for k in ("seed", "plate cells", "cells/well", "transduc", "infect")):
        return 3
    if any(k in text for k in ("dilut", "resuspend", "concentration", "final conc", "stock")):
        return 2
    return 0


def render_expand_step(step: dict, key_prefix: str):
    """Per-step 'Expand into detailed steps (AI)' control with revert."""
    proto = st.session_state.protocol
    sid = step.get("step_id")
    level = (st.session_state.input_meta or {}).get("experience_level", "intermediate")
    orig_map = st.session_state._orig_instr
    c1, c2 = st.columns([1, 1])
    if c1.button(f"Expand into detailed steps · {_level_profile(level)['audience']}",
                 key=f"exp_{key_prefix}",
                 help="Detail length follows your sidebar experience level."):
        orig_map.setdefault(sid, list(step.get("instructions", []) or []))
        with st.spinner("Step Detailer: writing full detail…"):
            res = StepExpandAgent().expand(proto, step, level)
        if res.get("status") == "success":
            step["instructions"] = res["instructions"]
            for nnote in res.get("notes", []) or []:
                step.setdefault("notes", []).append(nnote)
            persist_protocol(proto)
            log_event("step_expanded", {"step_id": sid, "mode": res.get("mode")})
            st.rerun()
        else:
            st.error(f"Expand failed: {res.get('error')}")
    if sid in orig_map:
        if c2.button("↩ Revert to original", key=f"rev_{key_prefix}"):
            step["instructions"] = orig_map.pop(sid)
            persist_protocol(proto)
            st.rerun()


def metric_cards(items):
    """items: list of (label, value) or (label, value, sub). First card accented."""
    html = ['<div class="lab-metrics">']
    for i, it in enumerate(items):
        label, value = it[0], it[1]
        sub = it[2] if len(it) > 2 else ""
        cls = "lab-metric accent" if i == 0 else "lab-metric"
        html.append(
            f'<div class="{cls}"><div class="lab-metric-label">{label}</div>'
            f'<div class="lab-metric-value">{value}</div>'
            + (f'<div class="lab-metric-sub">{sub}</div>' if sub else "")
            + "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _apply_routing():
    """Push the user's per-agent model choices into the environment so every agent
    instance picks them up (ROLE_PROVIDER / ROLE_MODEL win over tier + FORCE_CHEAP)."""
    for role, cfg in (st.session_state.get("routing") or {}).items():
        ru = role.upper()
        if cfg.get("provider"):
            os.environ[f"{ru}_PROVIDER"] = cfg["provider"]
        if cfg.get("model"):
            os.environ[f"{ru}_MODEL"] = cfg["model"]


def main():
    init_state()
    inject_theme()
    sidebar()
    _apply_routing()   # apply the routing chosen in the sidebar this run
    # apply Live/Offline toggle so every agent constructed this run follows it
    os.environ["DEMO_MODE"] = "false" if st.session_state.get("live_mode", not DEMO_MODE) else "true"

    # clickable stage navigation — jump back to earlier stages anytime
    nav_clickable()
    # save-to-project available at every step once a protocol exists
    render_save_bar()

    page = st.session_state.page
    # Ensure the active protocol carries a structured uncertainty registry before
    # any page renders. Idempotent + lazy: migrates legacy CONFIRM strings once,
    # then only refreshes the inline mirror on subsequent renders.
    if st.session_state.get("protocol"):
        uncertainty_slots.migrate_protocol(st.session_state.protocol)
    if page == "input":
        page_input()
    elif page == "parse_routes":
        page_parse_routes()
    elif page == "design_hub":
        page_design_hub()
    elif page == "parsed":          # legacy keys (cross-links) -> consolidated tabs
        page_parse_routes()
    elif page == "digest":
        page_parse_routes()
    elif page == "protocol":
        page_design_hub()
    elif page == "fill":
        page_design_hub()
    elif page == "resolve":
        page_design_hub()
    elif page == "plan":
        page_plan()
    elif page == "bench":
        page_bench()
    elif page == "revision":
        page_revision()
    elif page == "learn":
        page_learn()
    elif page == "design":
        page_design()
    elif page == "projects":
        page_projects()
    else:
        page_input()


def render_save_bar():
    """Compact 'save progress to a project' bar shown on every step once a protocol
    exists. Repeated saves UPDATE the same experiment (no duplicates)."""
    proto = st.session_state.get("protocol")
    if not proto or st.session_state.page == "home":
        return
    cur_slug = st.session_state.get("current_exp_id") and st.session_state.get("current_project")
    cur_name = ""
    if st.session_state.get("current_project"):
        cur_name = next((p["name"] for p in proj.list_projects()
                         if p["slug"] == st.session_state["current_project"]), "")
    title = (f"Save progress · updating **{cur_name}**" if cur_slug
             else "Save progress to a project")
    with st.expander(title, expanded=False):
        existing = {p["name"]: p["slug"] for p in proj.list_projects()}
        opts = list(existing.keys()) + ["New project…"]
        default_idx = (list(existing.keys()).index(cur_name)
                       if cur_name in existing else (len(opts) - 1 if opts else 0))
        c1, c2, c3 = st.columns([3, 2, 2])
        choice = c1.selectbox("Project", opts, index=default_idx, key="savebar_proj")
        target = (c1.text_input("New project name", key="savebar_new").strip()
                  if choice == "New project…" else choice)
        status = c2.selectbox("Status", ["in_progress", "worked", "failed"], key="savebar_status")
        new_record = c3.checkbox("New version", value=False, key="savebar_newrec",
                                 help="Off = update the same saved experiment; On = save a new copy.")
        if c3.button("Save", key="savebar_save", type="primary",
                     disabled=not target, use_container_width=True):
            same_proj = target == cur_name
            eid = (st.session_state.get("current_exp_id")
                   if (same_proj and not new_record) else None)
            new_id = proj.save_experiment(
                target, proto, st.session_state.input_meta, status=status,
                plan=st.session_state.get("plan"),
                source_documents=st.session_state.get("source_docs", []),
                parsed_docs=st.session_state.get("parsed_docs", []),
                exp_id=eid)
            st.session_state.current_project = proj._slug(target)
            st.session_state.current_exp_id = new_id
            log_event("experiment_saved", {"project": target, "exp_id": new_id,
                                           "status": status, "updated": bool(eid)})
            st.success(("Updated" if eid else "Saved") + f" in '{target}'.")
            st.rerun()


def nav_clickable():
    """Two nav groups: the sequential WORKFLOW pipeline, and a parallel WORKSPACE
    (Learn / Projects) that isn't part of the step-by-step flow."""
    ss = st.session_state
    # map legacy/sub-page keys to their consolidated nav pill for highlighting
    cur = {"protocol": "design_hub", "fill": "design_hub", "resolve": "design_hub",
           "parsed": "parse_routes", "digest": "parse_routes"}.get(ss.page, ss.page)

    def _navbar(label, pages, marker, boxed=True):
        st.markdown(f'<div class="lab-navlabel">{label}</div>', unsafe_allow_html=True)
        box = st.container(border=True) if boxed else st.container()
        with box:
            # marker is always emitted (collapsed to 0 height) purely as a CSS hook
            st.markdown(f'<span class="{marker}"></span>', unsafe_allow_html=True)
            cols = st.columns(len(pages))
            for col, (key, lbl, enabled) in zip(cols, pages):
                with col:
                    if key == "__new__":           # New run action (not a page)
                        if st.button(lbl, key="nav_newrun", use_container_width=True,
                                     type="primary"):
                            reset_run()
                            ss.page = "input"
                            st.rerun()
                        continue
                    if key == "__start__":         # reveal the new-experiment form
                        if st.button(lbl, key="nav_start", use_container_width=True,
                                     type="primary"):
                            ss.input_reveal = True
                            ss.page = "input"
                            st.rerun()
                        continue
                    is_cur = key == cur
                    if st.button(lbl, key=f"nav_{key}", disabled=not enabled or is_cur,
                                 use_container_width=True,
                                 type="primary" if is_cur else "secondary"):
                        ss.page = key
                        st.rerun()

    workflow = [
        ("input", "Input", True),
        ("parse_routes", "Parse", (ss.parsed is not None) or (ss.protocol is not None)),
        ("design_hub", "Design", ss.protocol is not None),
        ("plan", "Plan", ss.protocol is not None),
        ("bench", "Bench", ss.protocol is not None),
        ("revision", "Revise", ss.protocol is not None),
    ]
    started = (ss.parsed is not None) or (ss.protocol is not None)
    home = ss.page == "home"
    workspace = ([("__new__", "＋ New run", True)] if (started and not home) else []) + [
        ("projects", "Projects", True),
        ("learn", "Learn", (ss.protocol is not None) or bool(ss.get("current_project"))),
    ]

    # The sequential pipeline only appears once a run has started (parsed) or an
    # old run is open (protocol). Before that — or when the user clicks the logo to
    # go Home — the front page stays clean: just the workspace next to the Start action.
    if not started or home:
        # WORKSPACE box on the left, the Start action on the same horizontal level
        c_ws, c_act, _ = st.columns([0.30, 0.34, 0.36])
        with c_ws:
            _navbar("WORKSPACE", workspace, "lab-ws-marker", boxed=False)
        with c_act:
            st.markdown('<div class="lab-navlabel">&nbsp;</div>', unsafe_allow_html=True)
            if st.button("＋  Start a new experiment", type="primary",
                         use_container_width=True, key="nav_start_btn"):
                reset_run()            # clean slate — no prior project/memory carries over
                ss.input_reveal = True
                ss.page = "input"
                st.rerun()
        st.write("")
        return

    side, main = st.columns([0.40, 0.60])
    with side:
        _navbar("WORKSPACE", workspace, "lab-ws-marker lab-ws-aligned", boxed=False)
    with main:
        _navbar("WORKFLOW", workflow, "lab-nav-marker")
    st.write("")


if __name__ == "__main__":
    main()
