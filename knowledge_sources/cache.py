"""
knowledge_sources.cache
======================
On-disk cache for retrieved knowledge, so a query hits the network once and is
reproducible afterward (every record keeps its retrieved_time + version). Pure
local file IO; no network. Cache lives in memory/knowledge_cache/.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "memory", "knowledge_cache")


def _ensure() -> None:
    os.makedirs(_DIR, exist_ok=True)


def cache_key(entity_type: str, query: str, sources: Optional[List[str]] = None) -> str:
    raw = f"{entity_type}|{query.strip().lower()}|{','.join(sorted(sources or []))}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def get(key: str, max_age_days: Optional[float] = None) -> Optional[List[Dict[str, Any]]]:
    """Return cached record-dicts for a key, or None if missing/stale."""
    fp = os.path.join(_DIR, f"{key}.json")
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, encoding="utf-8") as fh:
            blob = json.load(fh)
    except Exception:
        return None
    if max_age_days is not None:
        age = (time.time() - blob.get("_cached_at", 0)) / 86400.0
        if age > max_age_days:
            return None
    return blob.get("records", [])


def put(key: str, records: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> None:
    _ensure()
    fp = os.path.join(_DIR, f"{key}.json")
    with open(fp, "w", encoding="utf-8") as fh:
        json.dump({"_cached_at": time.time(), "meta": meta or {}, "records": records},
                  fh, indent=2, ensure_ascii=False)


def clear() -> int:
    if not os.path.isdir(_DIR):
        return 0
    n = 0
    for f in os.listdir(_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(_DIR, f))
            n += 1
    return n
