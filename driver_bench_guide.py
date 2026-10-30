"""
Driver (zh): convert the approved (human-reviewed) RMCE protocol into a
Chinese bench-ready protocol using the lab-protocol-agent's deterministic
components (save_artifact renderers + ReviewAgent checks).

Grounded source: the approved project.json (Evidence status: approved; v2 =
Chinese translation of approved v1). No live model calls, no API keys. Every
pending-confirmation value keeps the tool's placeholder convention
"[confirm with source protocol]" so ReviewAgent can audit it.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

from tools.save_artifact import (
    new_run_dir,
    save_json,
    save_text,
    protocol_to_markdown,
    bench_to_markdown,
    normalize_protocol,
)
from agents.review_agent import ReviewAgent

CONFIRM = "[confirm with source protocol]"

PROJ_DIR = (
    "C:\\Users\\a1440\\Documents\\Codex\\2026-10-28\\junction-pcr-p18-l-f1-p18\\outputs\\protocol_sop_mcp\\data\\"
    "Electroporation-delivery-of-a-donor-plasmid-plus-Cre-loxP-recombinase-mediated-c"
)
PROJECT_JSON = os.path.join(PROJ_DIR, "project.json")
PROTOCOL_MD = os.path.join(PROJ_DIR, "protocol.md")


def load_project() -> dict:
    with open(PROJECT_JSON, encoding="utf-8") as f:
        return json.load(f)


def _confirm_items(items: list[dict]) -> list[dict]:
    """Map approved project items into bench materials entries, keeping the
    confirm placeholder for any pending-confirmation amount/identity."""
    out = []
    for it in items:
        name = it.get("name", "")
        note = it.get("note", "")
        srcs = ", ".join(it.get("source_ids", []))
        pending = "pending-confirmation" in note
        amount = CONFIRM if pending and ("质粒" in name or "引物" in name) else ""
        if "电转溶液" in name:
            amount = "100-110 uL/槽"
        if "抗生素" in name:
            amount = "见步骤 6"
        if "电转仪" in name:
            amount = "1 台"
        out.append(
            {
                "item": name,
                "vendor": "",
                "catalog_number": "",
                "amount": amount or "按实验需要",
                "required": "yes",
                "notes": (note + (f"。来源: {srcs}" if srcs else "")).strip(),
            }
        )
    return out


def build_protocol() -> dict:
    d = load_project()
    p = d["protocol"]
    steps_src = p["steps"]
    ts = datetime.now(timezone.utc).isoformat()

    def _title(action: str) -> str:
        if "：" in action:
            return action.split("：")[0]
        if "。" in action:
            return action.split("。")[0]
        return action[:40]

    workflow = []
    for s in steps_src:
        unk = s.get("unknowns", [])
        workflow.append(
            {
                "step_id": f"step_{s['step']:02d}",
                "step_number": s["step"],
                "stage": {
                    1: "预验证",
                    2: "构建体准备",
                    3: "细胞准备",
                    4: "电转",
                    5: "恢复",
                    6: "选择",
                    7: "克隆",
                    8: "验证",
                }[s["step"]],
                "title": _title(s["action"]),
                "purpose": s["action"],
                "time_estimate": CONFIRM,
                "conditions": {},
                "reagents": [],
                "instructions": [
                    s["action"],
                    "参数: " + json.dumps(s["parameters"], ensure_ascii=False),
                    "检查点: " + s["checkpoint"],
                    "暂停点: " + (s["pause_point"] or "[未报告]"),
                    "来源: " + ", ".join(s["source_ids"]),
                ]
                    + [f"待确认: {u}" for u in unk],
                "expected_observation": s["checkpoint"],
                "checkpoint": s["checkpoint"],
                "pause_point": s["pause_point"] or "[未报告]",
                "human_review_required": unk,
                "troubleshooting": [],
                "notes": ["来源: " + ", ".join(s["source_ids"])],
            }
        )

    materials = _confirm_items(p["materials"]) + _confirm_items(p["equipment"])

    return {
        "protocol_title": p["title"],
        "protocol_version": f"v{p['version']}",
        "assay_type": "重组酶介导的盒交换 (RMCE)，电转递送",
        "intended_user": "在培养的哺乳动物细胞基因组着陆垫中执行长片段定向整合的分子细胞生物学实验室",
        "confidence": "中高：全部步骤/引用有来源支持并经人工审查批准；步骤 4 的电转参数为跨模态外推值（pending-confirmation）",
        "timestamp": ts,
        "objective": "通过共电转供体质粒与 Cre 重组酶表达质粒，将 loxP 两侧修饰的长片段插入整合入单拷贝基因组着陆垫，经选择富集完成交换的细胞，并验证单拷贝、方向正确的整合。",
        "summary": "8 步文献推导方案（9 个 PMC 来源；模型审查第 1 轮 PASS；人工审查 APPROVED）。步骤 4 的电场参数来自整合酶-RMCE 与 DICE 研究的跨模态参考，执行前必须针对用户细胞系与载荷进行确认/优化。",
        "preconditions": {
            "sample_requirements": [
                "目标位点带有单拷贝、loxP 两侧修饰基因组着陆垫 (LP) 的 LP 细胞系（用户提供；设计/位点 pending-confirmation）",
                "收获前为健康单层/传代，良好汇合度",
                "电转前即时确认活率 >95%",
            ],
            "reagent_requirements": [
                "无内毒素、经测序验证的供体质粒（loxP 两侧修饰长片段插入 + 选择标记，可选报告基因）",
                "无内毒素 Cre 重组酶哺乳动物表达质粒（载体身份 pending-confirmation）",
                "使用时刻为冰上的冷电转溶液（Solution R 或转染试剂 R）",
                "与交换标记切换匹配的选择抗生素（浓度 pending-confirmation）",
                "细胞系特异恢复培养基（参考配方见步骤 5）",
                "gDNA 提取试剂 + SYBR qPCR 试剂 + 单拷贝参考基因引物（用于验证）",
            ],
            "equipment_requirements": [
                "电转仪：Neon（人 iPSC 参考 1200 V/30 ms/2 次脉冲；小鼠 ES 参考 1400 V/10 ms/3 次脉冲）、4D-Nucleofector X（P3 kit，iPSC DICE 参考）或 MPK5000（CHO 参考 1575 V/10 ms/3 次脉冲）",
                "细胞活率分析仪",
                "PCR 热循环仪 + 琼脂糖凝胶电泳",
                "qPCR 仪（例如 CFX96）",
                "流式细胞仪 / FACS 分选仪（可选单细胞克隆）",
                "96 孔板（限制稀释）",
            ],
            "safety_notes": [
                "标准 BSL-1 哺乳动物细胞培养操作；手套、实验服、护目镜",
                "电转仪：槽在加样前保持干燥；勿触碰电极；遵循设备安全手册",
                "抗生素/选择培养基与 ROCK 抑制剂 (Y-27632) 按实验室化学品安全政策处理",
            ],
            "lab_specific_fields_to_confirm": [
                "用户细胞系 + Cre/供体载荷的精确电转程序（电压/脉冲）——仅跨模态参考值（关键 CRITICAL）",
                "每个质粒的 DNA 量（依赖细胞系与载荷尺寸）",
                "每槽细胞数与重悬体积",
                "Cre 表达载体身份与供体骨架",
                "选择策略：获得/丢失哪个标记；抗生素种类 + 浓度",
                "目标细胞系的恢复培养基配方",
                "junction PCR 引物组（5'/3'）与 qPCR 参考基因",
                "克隆密度与板格式",
            ],
        },
        "materials": materials,
        "workflow": workflow,
        "qc_checkpoints": [
            {"checkpoint_name": "LP 细胞系验证", "when": "电转前（步骤 1）", "measurements": ["5'/3' junction PCR 条带大小", "LP 拷贝数（对单拷贝参考）", "克隆稳定性/报告基因表达"], "pass_criteria": ["junction 条带为预期大小", "拷贝数约每二倍体基因组 1 个", "稳定表达克隆"], "fail_signals": ["junction PCR 阴性", "拷贝数非单拷贝", "生长缺陷"], "recommended_action_on_fail": "重新隔离或重新靶向 LP 细胞系；不进入后续步骤。"},
            {"checkpoint_name": "质粒 QC", "when": "电转前（步骤 2）", "measurements": ["供体 + Cre 构建体 Sanger 测序", "A260/280 定量", "内毒素水平"], "pass_criteria": ["测序验证", "已定量", "低内毒素"], "fail_signals": ["插入片段 indel", "高内毒素", "A260/280 异常"], "recommended_action_on_fail": "重新纯化或重新克隆；超大插入考虑 minicircle 供体。"},
            {"checkpoint_name": "电转前细胞 QC", "when": "脉冲前即时（步骤 3）", "measurements": ["细胞活率", "细胞计数", "悬浮液质量"], "pass_criteria": ["活率 >95%", "计数正确", "冰上单细胞悬浮液"], "fail_signals": ["活率 <95%", "结团", "计数错误"], "recommended_action_on_fail": "重新收获；优化分散。"},
            {"checkpoint_name": "电转后恢复 QC", "when": "脉冲后约 2 天（步骤 4-5）", "measurements": ["脉冲后活率", "约 2 天内的贴壁/生长"], "pass_criteria": ["活率可接受", "施加选择前可见生长"], "fail_signals": ["活率崩溃", "4 天仍无恢复"], "recommended_action_on_fail": "优化脉冲程序/细胞数；调整恢复培养基。"},
            {"checkpoint_name": "选择 QC", "when": "递送后 2-4 天起，持续 2-4 周（步骤 6）", "measurements": ["抗性克隆出现", "未交换细胞清除", "对照孔（无供体/无 Cre/空载体）"], "pass_criteria": ["稳定抗性克隆", "未交换细胞被清除", "对照显示预期特异性"], "fail_signals": ["无克隆", "未选择细胞存活过多"], "recommended_action_on_fail": "滴定抗生素强度；核对选择设计与对照。"},
            {"checkpoint_name": "克隆验证 QC", "when": "克隆扩增后，逐克隆（步骤 8）", "measurements": ["5'/3' junction PCR", "拷贝数 qPCR", "复杂插入的方向/骨架检查"], "pass_criteria": ["junction 条带预期大小", "单拷贝", "方向正确、无骨架"], "fail_signals": ["junction 条带缺失/异常", "多拷贝", "方向错误"], "recommended_action_on_fail": "拒绝克隆；从更早传代重新克隆；复杂插入加做 Southern/低深度拷贝数验证。"},
        ],
        "decision_points": [
            {"decision": "电转程序选择", "when": "步骤 4，首次脉冲前", "options": ["Neon 1200 V/30 ms/2 次脉冲（人 iPSC 参考）", "Neon 1400 V/10 ms/3 次脉冲（小鼠 ES RMCE 参考）", "MPK5000 1575 V/10 ms/3 次脉冲（CHO 参考）", "4D-Nucleofector X P3 kit（iPSC DICE 跨模态参考）", "用户细胞系优化程序（使用前确认）"]},
            {"decision": "选择标记策略", "when": "步骤 6 前", "options": ["对被交换进标记的正选择（例如 G418 200-210 ug/mL 参考）", "对交换前丢失标记的负选择", "正/负联合（Big-in 式，pmc:12868904）", "嘌呤霉素短程暴露（DICE 参考，500 ng/mL，2-4 天）"]},
            {"decision": "克隆方法", "when": "步骤 7", "options": ["96 孔板限制稀释 0.5 细胞/孔", "单细胞 FACS 分选"]},
        ],
        "failure_branches": [
            {"condition": "LP 细胞系验证失败（junction PCR 阴性/多拷贝/不稳定）", "step_ids_affected": ["step_01"], "likely_causes": ["LP 设计/位点不匹配", "单细胞克隆建立不良"], "recommended_modifications": ["重新建立单细胞克隆", "重新设计 junction 引物", "重新靶向 LP"], "whether_to_repeat_or_stop": "LP 验证前停止后续步骤；重复步骤 1。"},
            {"condition": "电转后活率崩溃", "step_ids_affected": ["step_04", "step_05"], "likely_causes": ["电压过高", "每槽细胞过多", "冷链失效"], "recommended_modifications": ["降低电压/脉冲数", "降低每槽细胞数", "核对冷溶液"], "whether_to_repeat_or_stop": "修改程序后重复步骤 3-4；若无可用程序则停止。"},
            {"condition": "2-4 周后无抗性克隆", "step_ids_affected": ["step_06"], "likely_causes": ["选择过强", "未发生交换", "Cre 未表达"], "recommended_modifications": ["降低抗生素浓度", "核对无 Cre/无供体对照", "优化 Cre 表达"], "whether_to_repeat_or_stop": "调整强度后重复选择；若始终无交换则停止并重新设计构建体。"},
            {"condition": "克隆验证失败（多拷贝/方向错误/junction 异常）", "step_ids_affected": ["step_08"], "likely_causes": ["串联体整合", "部分交换", "选择压力过弱"], "recommended_modifications": ["拒绝克隆", "从更早传代重新克隆", "加做 Southern/低深度拷贝数验证"], "whether_to_repeat_or_stop": "从更早克隆池重复克隆；不推进失败克隆。"},
        ],
        "open_questions_for_human": [
            "关键 (CRITICAL)：电转 Cre + 长片段供体 RMCE 的电转参数（电压/脉冲/DNA 量）为跨模态外推值，必须针对用户细胞系确认/优化（pending-confirmation）。",
            "Cre 表达载体与长片段供体骨架的身份（用户依赖）。",
            "目标细胞系每槽细胞数与重悬体积。",
            "选择策略（获得/丢失哪个标记）与抗生素浓度。",
            "目标细胞系的恢复培养基配方。",
            "junction PCR 与拷贝数 qPCR 引物组。",
            "克隆密度与板格式。",
            "超大插入是否需要 minicircle 供体（pmc:13586533）。",
        ],
        "revision_log": [
            {"version": "v1", "reason": "从已批准文献推导 SOP（证据状态: approved；模型审查第 1 轮 PASS；人工审查 APPROVED）转换为 lab-protocol-agent 台边执行 schema；内容为已批准 v1 的中文译文（format_only，无科学内容修改）。"},
        ],
        "artifact_outputs": [],
    }


def main() -> None:
    d = load_project()
    proto = build_protocol()
    normalize_protocol(proto)

    review_agent = ReviewAgent()
    review = review_agent.run(
        "将已批准的 RMCE 方案转换为台边执行模式",
        {"protocol": proto, "user_instruction": "将已批准的 RMCE 方案转换为台边执行模式"},
    )
    print("review checks:", review.get("checks"))
    print("review issues:", review.get("issues"))
    print("review suggestions:", review.get("suggestions"))

    run_dir = new_run_dir()
    p = save_json(run_dir, "input.json", {"file": "project.json (approved, v2 zh translation)", "project_id": d["id"], "status": d["status"]})
    print("saved", p)
    p = save_json(run_dir, "protocol_v1.json", proto)
    print("saved", p)
    p = save_text(run_dir, "protocol_v1.md", protocol_to_markdown(proto))
    print("saved", p)
    p = save_text(run_dir, "protocol_bench_v1.md", bench_to_markdown(proto))
    print("saved", p)
    p = save_json(run_dir, "review_v1.json", review)
    print("saved", p)
    print("RUN_DIR:", run_dir)


if __name__ == "__main__":
    main()
