"""
protocol_graph
=============
The protocol as a LIVING DEPENDENCY GRAPH, not a form. Parameters are nodes;
edges declare how a downstream value derives from upstream values via a transform.
Change one intent value (cell number, vessel, scale) and every dependent
recomputes — with an explanation of WHY it changed.

Deterministic + auditable: transforms are concrete functions (reusing vessels /
standard_units), never model guesses. Recomputed values are SUGGESTIONS the user
can accept or LOCK; changing an upstream of a locked node raises a conflict
instead of silently overwriting a settled decision. No model calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import vessels


# --------------------------------------------------------------------------- #
# transform registry: id -> fn(args: list, params: dict) -> value
# --------------------------------------------------------------------------- #
def _linear(args, params):          # y = x * factor
    return args[0] * params["factor"]


def _clamp(args, params):           # clamp x into [lo, hi]
    return min(max(args[0], params["lo"]), params["hi"])


def _vessel_area(args, params):     # scale a base value by growth-area ratio to a new vessel
    return vessels.scale(params["base_value"], params["from_vessel"], args[0], "area")


def _vessel_media(args, params):    # working volume of the (new) vessel
    r = vessels.recommend_media(args[0])
    return r["working_volume_mL"] if r else None


TRANSFORMS: Dict[str, Callable[[list, dict], Any]] = {
    "linear": _linear, "clamp": _clamp,
    "vessel_area": _vessel_area, "vessel_media": _vessel_media,
}


# --------------------------------------------------------------------------- #
# graph
# --------------------------------------------------------------------------- #
@dataclass
class Edge:
    dst: str
    inputs: List[str]
    transform: str
    params: Dict[str, Any] = field(default_factory=dict)
    label: str = ""                 # human name for the dst, used in explanations


class DependencyGraph:
    def __init__(self):
        self.edges: List[Edge] = []
        self._locked: set = set()

    def add(self, dst, inputs, transform, params=None, label="") -> "DependencyGraph":
        self.edges.append(Edge(dst, list(inputs), transform, params or {}, label or dst))
        return self

    def lock(self, slot: str) -> None:
        self._locked.add(slot)

    def unlock(self, slot: str) -> None:
        self._locked.discard(slot)

    def is_locked(self, slot: str) -> bool:
        return slot in self._locked


def _eq(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return str(a) == str(b)


def recompute(graph: DependencyGraph, values: Dict[str, Any],
              changed: Dict[str, Any]) -> Dict[str, Any]:
    """Apply changed values and propagate through the graph. Returns
    {values, changes, conflicts}. Multi-level (a dependent of a dependent updates
    too). Locked nodes are not overwritten — a would-be change becomes a conflict."""
    vals = dict(values)
    vals.update(changed)
    dirty = set(changed)
    changes: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    for _ in range(len(graph.edges) + 1):
        newly = set()
        for e in graph.edges:
            if not any(i in dirty for i in e.inputs):
                continue
            if not all(i in vals for i in e.inputs):
                continue
            args = [vals[i] for i in e.inputs]
            try:
                newval = TRANSFORMS[e.transform](args, e.params)
            except Exception:
                continue
            if newval is None:
                continue
            old = vals.get(e.dst)
            if _eq(newval, old):
                continue
            trigger = next((i for i in e.inputs if i in dirty), e.inputs[0])
            if graph.is_locked(e.dst):
                conflicts.append({
                    "slot": e.dst, "label": e.label, "current": old, "proposed": newval,
                    "trigger": trigger,
                    "explanation": f"{e.label} is locked at {old}, but {trigger} changed to "
                                   f"{vals[trigger]} (would suggest {newval}). Resolve manually."})
                continue
            vals[e.dst] = newval
            newly.add(e.dst)
            changes.append({
                "slot": e.dst, "label": e.label, "old": old, "new": newval,
                "trigger": trigger, "transform": e.transform,
                "explanation": f"{e.label} updated {old} → {newval} because "
                               f"{trigger} changed to {vals[trigger]}."})
        if not newly:
            break
        dirty |= newly

    return {"values": vals, "changes": changes, "conflicts": conflicts}


def dependents(graph: DependencyGraph, slot: str) -> List[str]:
    """Direct dependents of a slot (one hop)."""
    return [e.dst for e in graph.edges if slot in e.inputs]
