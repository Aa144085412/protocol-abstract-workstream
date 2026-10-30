"""
projects
========
Lightweight project store so a researcher can group experiments that worked,
keep them under a named project, and document them later (e.g. for a paper's
Methods section).

Layout (under memory/projects/):
    <project>/project.json                 # project metadata
    <project>/experiments/<exp_id>.json    # one saved experiment (protocol + outcome)

No model calls here — pure local file IO.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

_MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")
PROJECTS_DIR = os.path.join(_MEMORY_DIR, "projects")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip()).strip("_")
    return s or "project"


def list_projects() -> List[Dict[str, Any]]:
    out = []
    if not os.path.isdir(PROJECTS_DIR):
        return out
    for d in sorted(os.listdir(PROJECTS_DIR)):
        pdir = os.path.join(PROJECTS_DIR, d)
        if not os.path.isdir(pdir):
            continue
        meta = {}
        mp = os.path.join(pdir, "project.json")
        if os.path.exists(mp):
            try:
                with open(mp, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                meta = {}
        out.append({
            "slug": d,
            "name": meta.get("name", d),
            "created": meta.get("created", ""),
            "n_experiments": len(list_experiments(d)),
        })
    return out


def create_project(name: str) -> str:
    slug = _slug(name)
    pdir = os.path.join(PROJECTS_DIR, slug)
    os.makedirs(os.path.join(pdir, "experiments"), exist_ok=True)
    mp = os.path.join(pdir, "project.json")
    if not os.path.exists(mp):
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump({"name": name, "slug": slug,
                       "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
                      fh, indent=2, ensure_ascii=False)
    return slug


def save_experiment(project: str, protocol: Dict[str, Any], input_meta: Dict[str, Any],
                    status: str = "worked", notes: str = "",
                    plan: Optional[Dict[str, Any]] = None,
                    source_documents: Optional[List[Dict[str, Any]]] = None,
                    parsed_docs: Optional[List[Dict[str, Any]]] = None,
                    exp_id: Optional[str] = None) -> str:
    """Save the current protocol + outcome into a project. status in
    {worked, failed, in_progress}. ``source_documents`` keeps the uploaded source
    text (protocols + background + literature) so the Methods writer can re-read
    them and ground details the structured protocol may not capture. If ``exp_id``
    is given and exists, the record is UPDATED in place (no duplicate)."""
    slug = create_project(project) if project not in [p["slug"] for p in list_projects()] else _slug(project)
    edir = os.path.join(PROJECTS_DIR, slug, "experiments")
    os.makedirs(edir, exist_ok=True)
    if not (exp_id and os.path.exists(os.path.join(edir, f"{exp_id}.json"))):
        exp_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    record = {
        "exp_id": exp_id,
        "saved_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": protocol.get("protocol_title", "Protocol"),
        "version": protocol.get("protocol_version", "v1"),
        "assay_type": protocol.get("assay_type", ""),
        "status": status,
        "notes": notes,
        "input_meta": input_meta or {},
        "protocol": protocol,
        "plan": plan,
        "source_documents": source_documents or [],
        "parsed_docs": parsed_docs or [],
    }
    with open(os.path.join(edir, f"{exp_id}.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
    return exp_id


def _sources_path(slug: str) -> str:
    return os.path.join(PROJECTS_DIR, slug, "sources.json")


def _memory_path(slug: str) -> str:
    return os.path.join(PROJECTS_DIR, slug, "memory.json")


def get_project_memory(project: str) -> Dict[str, Any]:
    """Cached agent outputs (summary, literature, education, methods, audit, …) so
    they persist across sessions and don't need re-generating (saves tokens)."""
    fp = _memory_path(_slug(project))
    if not os.path.exists(fp):
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def set_project_memory(project: str, key: str, value: Any) -> None:
    """Store one cached output under ``key`` (e.g. 'summary'). Merges in place."""
    slug = create_project(project) if project not in [p["slug"] for p in list_projects()] else _slug(project)
    mem = get_project_memory(slug)
    mem[key] = {"value": value, "saved_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        with open(_memory_path(slug), "w", encoding="utf-8") as fh:
            json.dump(mem, fh, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_project_sources(project: str) -> List[Dict[str, Any]]:
    """Project-level reference/source documents (added at any stage, not tied to a
    single experiment). Used to ground Methods writing."""
    fp = _sources_path(_slug(project))
    if not os.path.exists(fp):
        return []
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            return json.load(fh) or []
    except Exception:
        return []


def add_project_sources(project: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append source documents to a project (dedup by name+title). Returns the
    full list after the add. Each doc: {name, title, doc_type, text}."""
    slug = create_project(project) if project not in [p["slug"] for p in list_projects()] else _slug(project)
    existing = get_project_sources(slug)
    seen = {(d.get("name", ""), d.get("title", "")) for d in existing}
    for d in docs or []:
        key = (d.get("name", ""), d.get("title", ""))
        if key in seen:
            # replace existing entry of the same name/title
            existing = [e for e in existing if (e.get("name", ""), e.get("title", "")) != key]
        existing.append({
            "name": d.get("name", ""), "title": d.get("title") or d.get("name", ""),
            "doc_type": d.get("doc_type", "reference"),
            "text": (d.get("text") or "")[:8000],
            "added_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        seen.add(key)
    with open(_sources_path(slug), "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)
    return existing


def remove_project_source(project: str, name: str, title: str = "") -> List[Dict[str, Any]]:
    slug = _slug(project)
    existing = [d for d in get_project_sources(slug)
                if not (d.get("name", "") == name and (not title or d.get("title", "") == title))]
    with open(_sources_path(slug), "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)
    return existing


def list_experiments(project: str) -> List[Dict[str, Any]]:
    slug = _slug(project)
    edir = os.path.join(PROJECTS_DIR, slug, "experiments")
    out = []
    if not os.path.isdir(edir):
        return out
    for f in sorted(os.listdir(edir), reverse=True):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(edir, f), "r", encoding="utf-8") as fh:
                rec = json.load(fh)
            # light summary (don't carry the whole protocol in listings)
            out.append({
                "exp_id": rec.get("exp_id", f[:-5]),
                "title": rec.get("title", ""),
                "version": rec.get("version", ""),
                "assay_type": rec.get("assay_type", ""),
                "status": rec.get("status", ""),
                "notes": rec.get("notes", ""),
                "saved_at": rec.get("saved_at", ""),
                "n_steps": len(rec.get("protocol", {}).get("workflow", []) or []),
            })
        except Exception:
            continue
    return out


def delete_project(project: str) -> bool:
    path = os.path.join(PROJECTS_DIR, _slug(project))
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.isdir(path)
    return False


def delete_experiment(project: str, exp_id: str) -> bool:
    fp = os.path.join(PROJECTS_DIR, _slug(project), "experiments", f"{exp_id}.json")
    if os.path.exists(fp):
        try:
            os.remove(fp)
            return True
        except Exception:
            return False
    return False


def load_experiment(project: str, exp_id: str) -> Optional[Dict[str, Any]]:
    fp = os.path.join(PROJECTS_DIR, _slug(project), "experiments", f"{exp_id}.json")
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def full_experiments(project: str) -> List[Dict[str, Any]]:
    """Load full experiment records (with protocols) for a project."""
    slug = _slug(project)
    edir = os.path.join(PROJECTS_DIR, slug, "experiments")
    out = []
    if not os.path.isdir(edir):
        return out
    for f in sorted(os.listdir(edir)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(edir, f), "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out
