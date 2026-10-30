#!/usr/bin/env python3
"""
End-to-end smoke test for the Lab Experimental Agent.

Runs in DEMO_MODE (no API key) and exercises every agent, tool, and the
deterministic calculators. Use it to re-verify after any edit:

    cd lab_agent_prototype
    python -m tests.test_smoke        # or: python tests/test_smoke.py

Exits non-zero on the first failure.
"""

from __future__ import annotations

import os
import sys

# ensure DEMO_MODE so no network/key is needed, and the package is importable
os.environ.setdefault("DEMO_MODE", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0


def check(name, cond):
    global _passed
    if not cond:
        print(f"FAIL: {name}")
        sys.exit(1)
    _passed += 1
    print(f"  ok  {name}")


def main():
    from agents import (DocumentAgent, ProtocolAgent, ReviewAgent, SearchAgent,
                        PlannerAgent, ChatAgent, MethodsAgent, FillAgent,
                        ImproveAgent, StepExpandAgent)
    from tools import (get_kit, combine_protocols, count_confirm, list_kits,
                       apply_kit, protocol_to_markdown, bench_to_markdown,
                       plan_to_markdown, projects as proj)
    from tools.fill_slots import list_slots, apply_values, kit_suggestions
    from tools.step_ops import merge_steps, suggest_merges, split_step, move_step, \
        delete_step, move_to_preconditions
    from tools.readiness import compute_readiness
    from tools.pcr_design import tm_nn, design_pcr
    from tools.mol_tools import ligation_insert_ng, dilution, cell_seeding

    print("AGENTS")
    parsed = DocumentAgent().parse("zyppy plasmid miniprep spin column", "x.md")
    check("DocumentAgent.parse", parsed["status"] == "success")
    proto = ProtocolAgent().generate(parsed, {"experience_level": "beginner"})
    check("ProtocolAgent.generate schema", proto["status"] == "success" and proto["workflow"])
    rev = ProtocolAgent().revise({"prior_protocol": proto, "troubleshooting_input":
                                  {"flagged_steps": [{"step_id": "step_01", "issue_type": "Low yield"}]},
                                  "target_version": "v2"})
    check("ProtocolAgent.revise -> v2 surgical", rev["protocol_version"] == "v2" and rev["changed_step_ids"] == ["step_01"])
    review = ReviewAgent().review(proto, parsed)
    check("ReviewAgent.review", review["status"] == "success")
    plan = PlannerAgent().plan(proto, {"hours_per_day": 6})
    check("PlannerAgent hands-on/walk-away", plan["status"] == "success" and plan.get("total_hands_on"))
    check("SearchAgent fallback", SearchAgent().search("zymo rna")["status"] == "success")
    check("ChatAgent", ChatAgent().ask("spin speed for step 5?", proto)["status"] == "success")
    fs = FillAgent().suggest(proto, list_slots(proto))
    check("FillAgent.suggest", fs["status"] == "success")
    check("ImproveAgent", ImproveAgent().suggest(proto, review)["status"] == "success")
    check("StepExpandAgent", StepExpandAgent().expand(proto, proto["workflow"][1])["status"] == "success")

    print("TOOLS")
    check("kit library >= 10", len(list_kits()) >= 10)
    kit = get_kit("zyppy_plasmid_miniprep")
    check("kit has 0 confirm tags", count_confirm(kit) == 0)
    filled, ch = apply_kit(proto, kit)
    check("apply_kit non-destructive", count_confirm(filled) <= count_confirm(proto))
    comb = combine_protocols([get_kit("zyppy_plasmid_miniprep"), get_kit("zymoclean_gel_dna_recovery")])
    ids = [s["step_id"] for s in comb["workflow"]]
    check("combine renumbers steps", ids == [f"step_{i:02d}" for i in range(1, len(ids) + 1)])
    p2 = dict(proto)
    n = apply_values(p2, kit_suggestions(p2, list_slots(p2)))
    check("apply_values fills", n > 0)
    for r in (protocol_to_markdown(proto), bench_to_markdown(proto), plan_to_markdown(plan)):
        check("renderer non-empty", bool(r))

    print("STRUCTURE EDITS")
    m, e = merge_steps(proto, [proto["workflow"][0]["step_id"], proto["workflow"][1]["step_id"]])
    check("merge_steps", e is None and len(m["workflow"]) == len(proto["workflow"]) - 1)
    sp, e = split_step(proto, next(s["step_id"] for s in proto["workflow"] if len(s.get("instructions", [])) >= 2))
    check("split_step", e is None and len(sp["workflow"]) > len(proto["workflow"]))
    mv, e = move_step(proto, proto["workflow"][2]["step_id"], -1)
    check("move_step", e is None)
    pc, e = move_to_preconditions(proto, proto["workflow"][0]["step_id"])
    check("move_to_preconditions", e is None and len(pc["workflow"]) == len(proto["workflow"]) - 1)
    dl, e = delete_step(proto, proto["workflow"][0]["step_id"])
    check("delete_step", e is None and len(dl["workflow"]) == len(proto["workflow"]) - 1)

    print("READINESS")
    r = compute_readiness(proto)
    check("readiness 0-100", 0 <= r["score"] <= 100 and r["level"] in ("low", "medium", "high"))

    print("CALCULATORS")
    check("tm_nn plausible", 40 < (tm_nn("ACCACAGTCCATGCCATCAC") or 0) < 75)
    d = design_pcr("ACCACAGTCCATGCCATCAC", "TCCACCACCCTGTTGCTGTA", 450, "Q5 (NEB)")
    check("design_pcr", d.get("annealing_C") and d.get("extension_time"))
    check("ligation 3:1 = 30 ng", ligation_insert_ng(50, 5000, 1000, 3)["insert_ng"] == 30.0)
    check("dilution V1", dilution(1.0, None, 0.1, 100.0)["result"] == 10.0)
    check("cell seeding", cell_seeding(200000, 200, 12, 1000000)["total_cells_needed"] == 2640000)

    print("PROJECTS + METHODS")
    proj.create_project("_smoketest")
    proj.save_experiment("_smoketest", proto, {}, status="worked")
    md = MethodsAgent().write(proj.full_experiments("_smoketest"), "_smoketest")["markdown"]
    check("MethodsAgent writeup", "Methods" in md)

    print(f"\nALL {_passed} CHECKS PASSED ✅")


if __name__ == "__main__":
    main()
