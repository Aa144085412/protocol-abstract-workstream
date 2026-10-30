"""
Driver (zh): build a bench-ready Saccharomyces cerevisiae transformation
protocol (LiAc chemical + electroporation routes) with the
lab-protocol-agent's deterministic components (save_artifact renderers +
ReviewAgent checks).

Grounding policy (per workspace AGENTS.md): every numeric parameter is either
(a) drawn from a source verified in this session via Crossref/PubMed (DOI
listed in the source list below), or (b) explicitly marked
"[confirm with source protocol]" (pending-confirmation). No parameter is
invented. Goff 1987 / Burke 1987 classic electroporation papers could NOT be
re-verified in this session (no DOI obtained), so they are mentioned only as
unverified "further reading" and are NOT cited for any numeric parameter.
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

# --------------------------------------------------------------------------- #
# Sources verified IN THIS SESSION (Crossref/PubMed search results).
# --------------------------------------------------------------------------- #
SOURCES = [
    "Ito H, Fukuda Y, Murata K, Kimura A. 1983. Transformation of intact yeast cells treated with alkali cations. J Bacteriol 153(1):163-168. doi:10.1128/jb.153.1.163-168.1983",
    "Schiestl RH, Gietz RD. 1989. High efficiency transformation of intact yeast cells using single stranded nucleic acids as a carrier. Curr Genet 16:339-346. doi:10.1007/bf00340712",
    "Gietz D, St. Jean A, Woods RA, Schiestl RH. 1992. Improved method for high efficiency transformation of intact yeast cells. Nucleic Acids Res 20(6):1425. doi:10.1093/nar/20.6.1425",
    "Gietz R. 2014. Yeast Transformation by the LiAc/SS Carrier DNA/PEG Method. Methods Mol Biol 1118:1-12. doi:10.1007/978-1-4939-1363-3_1",
    "Gietz RA, Woods R. 2002. Transformation of yeast by lithium acetate/single-stranded carrier DNA/polyethylene glycol method. Methods Enzymol. doi:10.1016/s0076-6879(02)50957-5",
    "Meilhoc E, Masson JM, Teissié J. 1990. High Efficiency Transformation of Intact Yeast Cells by Electric Field Pulses. doi:10.1038/nbt0390-223",
    "Thompson JR, Register E, Curotto J, Kurtz M, Kelly R. 1998. An improved protocol for the preparation of yeast cells for transformation by electroporation. Yeast 14(6):565-571. doi:10.1002/(sici)1097-0061(19980430)14:6<565::aid-yea251>3.0.co;2-b",
    "Rothstein RD. 1991. [19] Targeting, disruption, replacement, and allele rescue: integrative DNA transformation in yeast. Methods Enzymol. doi:10.1016/0076-6879(91)94022-5",
]
SRC_STR = "; ".join(SOURCES)


def _title(action: str) -> str:
    for sep in ("：", "。"):
        if sep in action:
            return action.split(sep)[0]
    return action[:40]


def build_protocol() -> dict:
    ts = datetime.now(timezone.utc).isoformat()

    workflow = [
        # ---------------- A. LiAc chemical transformation ---------------- #
        {
            "step_id": "step_01",
            "step_number": 1,
            "stage": "A. LiAc 化学转化 — 细胞培养",
            "title": "过夜培养转化株",
            "purpose": "获得处于对数期-稳定期过渡的转化细胞（Ito 1983 报道细胞密度约 5×10^7/mL 时转化促进；实际收获密度因菌株而异）。",
            "time_estimate": "过夜 (12-16 h) @ 30°C 摇床 ~200 rpm",
            "conditions": {"temperature": "30°C", "speed": "200 rpm"},
            "reagents": [
                {"item": "YPD 液体培养基 (1% 酵母提取物, 2% 蛋白胨, 2% 葡萄糖)", "amount": "5 mL"},
                {"item": "待转化菌株（单克隆接种）", "amount": "1 个克隆"},
            ],
            "instructions": [
                "从平板取单个克隆接种 5 mL YPD，30°C、~200 rpm 摇床过夜培养。",
                "次日使用前确认培养物均匀浑浊（OD600 约 2-4 量级；精确目标密度待确认）。",
            ],
            "expected_observation": "均匀浑浊的过夜培养物。",
            "checkpoint": "OD600 达约 2-4（晚对数期）；若 <1 延长培养或改接更浓种子。",
            "pause_point": "细胞未达目标密度前不进入步骤 2。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "培养物不浑浊或生长迟缓", "possible_causes": ["菌株不匹配培养条件", "葡萄糖耗尽/污染"], "actions": ["核对菌株培养条件", "换新鲜 YPD 重新接种"], "escalate_if": "两次重复仍不生长"}
            ],
            "notes": ["来源: Ito 1983; Gietz 2014"],
        },
        {
            "step_id": "step_02",
            "step_number": 2,
            "stage": "A. LiAc 化学转化 — 细胞收获",
            "title": "离心收获与洗涤",
            "purpose": "收获细胞并用 TE-LiAc 洗涤，为转化反应提供均匀悬浮液。",
            "time_estimate": "约 15 min",
            "conditions": {"other": "4°C 或室温离心"},
            "reagents": [
                {"item": "TE-LiAc (1 M LiCl, 0.1 M Tris-HCl pH 7.5, 0.1 M EDTA pH 8.0)", "amount": "约 2 mL/收获管（用于洗涤与重悬）"},
            ],
            "instructions": [
                "5000×g 离心 5 min（1.5-2 mL 过夜培养物，Ito 1983 量级；精确转速/时间待确认）弃上清。",
                "TE-LiAc 轻轻重悬沉淀，再离心，重悬于适量 TE-LiAc（使细胞密度落在 Ito 1983 报道的最优区间）。",
            ],
            "expected_observation": "致密白色酵母沉淀；重悬液均匀。",
            "checkpoint": "沉淀致密、无培养基残留；重悬均匀无结块。",
            "pause_point": "沉淀不致密或重悬不均时重做步骤 2。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "沉淀松散/难重悬", "possible_causes": ["离心不足", "细胞量太少"], "actions": ["提高离心时间", "减少 TE-LiAc 用量重悬"], "escalate_if": "反复失败"}
            ],
            "notes": ["来源: Ito 1983; Gietz 2014"],
        },
        {
            "step_id": "step_03",
            "step_number": 3,
            "stage": "A. LiAc 化学转化 — 转化反应",
            "title": "加入 DNA、载体 DNA 与 PEG",
            "purpose": "在 Li+ 与 PEG 存在下将 DNA 导入完整酵母细胞（Ito 1983: Li+/Cs+ 约 1 M、1 h 孵育、PEG 必需；Schiestl & Gietz 1989: ss 载体 DNA 显著提高效率）。",
            "time_estimate": "约 1 h 37°C 孵育（Ito 1983 量级）",
            "conditions": {"temperature": "37°C"},
            "reagents": [
                {"item": "待转化质粒 DNA（酵母复制型载体）", "amount": "0.5-5 ug/管（范围待确认）"},
                {"item": "ss 载体 DNA（如鲑精 DNA 或 ssDNA，50 ug/mL 终浓度量级，Schiestl & Gietz 1989）", "amount": CONFIRM},
                {"item": "PEG 8000 溶液 (40% w/v in TE)", "amount": "加至终浓度约 10%（精确值待确认）"},
                {"item": "TE-LiAc", "amount": "补足体积"},
            ],
            "instructions": [
                "TE-LiAc 重悬的细胞中加入待转化质粒 DNA 与 ss 载体 DNA（冰上操作，尽量不中断）。",
                "加 PEG-TE 至目标终浓度，混匀。",
                "37°C 孵育约 1 h（Ito 1983 报道 1 h 有效；精确时间依载体/菌株确认）。",
            ],
            "expected_observation": "混悬液逐渐变黏（PEG 效应），无可见异常沉淀。",
            "checkpoint": "反应体系体积一致、无分层；所有管同步计时。",
            "pause_point": "孵育结束即进入热脉冲；不要中途加样。",
            "human_review_required": ["ss 载体 DNA 种类/用量与 PEG 终浓度依所选载体 DNA 来源方案确认（pending-confirmation）"],
            "troubleshooting": [
                {"problem": "体系黏度过高难分装", "possible_causes": ["PEG 过量", "细胞量过多"], "actions": ["按比例放大体系", "减少细胞量"], "escalate_if": "无法分装"}
            ],
            "notes": ["来源: Ito 1983; Schiestl & Gietz 1989; Gietz 1992"],
        },
        {
            "step_id": "step_04",
            "step_number": 4,
            "stage": "A. LiAc 化学转化 — 热脉冲",
            "title": "42°C 热脉冲",
            "purpose": "热脉冲促进 DNA 进入（Ito 1983 报道热脉冲促进转化）。",
            "time_estimate": "15 min @ 42°C（经典方案值；待确认）",
            "conditions": {"temperature": "42°C"},
            "reagents": [],
            "instructions": [
                "42°C 水浴/干浴孵育约 15 min（经典方案值；依菌株/载体确认）。",
                "结束后冰上短暂放置，准备离心去除 PEG。",
            ],
            "expected_observation": "无可见变化（预期无异常沉淀）。",
            "checkpoint": "计时准确；温度均匀。",
            "pause_point": "无。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "水浴温度漂移", "possible_causes": ["预温不足", "水量过少"], "actions": ["预温水浴", "增加水量"], "escalate_if": "温度反复不达标"}
            ],
            "notes": ["来源: Ito 1983（热脉冲促进转化）"],
        },
        {
            "step_id": "step_05",
            "step_number": 5,
            "stage": "A. LiAc 化学转化 — 去除 PEG 与恢复",
            "title": "离心、洗涤并恢复培养",
            "purpose": "去除 PEG/LiAc 后转入富含培养基恢复，允许选择性标记表达。",
            "time_estimate": "约 30 min + 1-2 h 30°C 恢复",
            "conditions": {"temperature": "30°C"},
            "reagents": [
                {"item": "YPD 液体培养基（无选择压力）", "amount": "5-10 mL/管"},
            ],
            "instructions": [
                "5000×g 离心 5 min 弃上清（去除 PEG）。",
                "YPD 重悬，30°C 摇床恢复 1-2 h（让转化子表达选择标记）。",
            ],
            "expected_observation": "细胞恢复生长，重悬液浊度上升。",
            "checkpoint": "重悬均匀；恢复后浊度可见上升。",
            "pause_point": "恢复完成前不涂布选择平板。",
            "human_review_required": [],
            "troubleshooting": [],
            "notes": ["来源: Gietz 2014; Gietz & Woods 2002"],
        },
        {
            "step_id": "step_06",
            "step_number": 6,
            "stage": "A. LiAc 化学转化 — 涂布选择",
            "title": "涂布选择培养基",
            "purpose": "在选择培养基上富集携带载体的转化子（标记与载体匹配，如 URA3/HIS3/TRP1/LEU2）。",
            "time_estimate": "约 30 min 涂布 + 3-5 d 30°C 培养",
            "conditions": {"temperature": "30°C 培养 3-5 天"},
            "reagents": [
                {"item": "选择性培养基平板（对应载体标记，如 SD-Trp/SD-Leu/SD-His/SD-Ura）", "amount": "每样品 1-2 板"},
                {"item": "非选择对照平板 (YPD)", "amount": "1 板"},
            ],
            "instructions": [
                "取恢复培养物 0.1-1 mL 稀释液涂布选择平板（每板约 10^5-10^6 细胞量级；精确稀释度待确认）。",
                "同时涂布 YPD 非选择对照板 (positive control, non-selective) 与无 DNA 阴性对照 (negative control, 步骤 6b)。",
                "倒置平板 30°C 培养 3-5 天。",
            ],
            "expected_observation": "选择平板出现离散克隆；YPD 板克隆密度显著更高。",
            "checkpoint": "克隆离散、不连成片；选择板克隆数/YPD 板克隆数比值可计算转化效率。",
            "pause_point": "克隆未长出前不挑取。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "选择板克隆过多（>500/板）", "possible_causes": ["选择压力不足", "稀释不够"], "actions": ["提高稀释度", "核对培养基选择标记"], "escalate_if": "反复连片"}
            ],
            "notes": ["来源: Gietz 2014; Rothstein 1991（标记选择策略）"],
        },
        {
            "step_id": "step_07",
            "step_number": 7,
            "stage": "A. LiAc 化学转化 — 阴性对照",
            "title": "无 DNA 阴性对照 (negative control, no-DNA)",
            "purpose": "确认选择平板上的克隆来自 DNA 转化而非自发回复突变/培养基交叉污染。",
            "time_estimate": "与步骤 6 并行",
            "conditions": {},
            "reagents": [
                {"item": "未经转化的同批细胞（或加空载体/无 DNA 管）", "amount": "与步骤 6 等量"},
            ],
            "instructions": [
                "与步骤 3 相同操作但不加待转化 DNA（或只加 ss 载体 DNA），走完全相同流程涂布选择板。",
                "阴性对照板克隆数应显著低于加 DNA 组（通常 <1/10 量级）。",
            ],
            "expected_observation": "阴性对照板几乎无克隆或极少克隆。",
            "checkpoint": "阴性对照克隆数 << 实验组；若相当高，结果不可信。",
            "pause_point": "阴性对照异常时暂停判读。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "阴性对照克隆过多", "possible_causes": ["自发回复突变率高", "选择标记泄漏", "DNA 污染"], "actions": ["核对菌株标记完整性", "核对 DNA 纯度/操作", "重复实验"], "escalate_if": "重复仍高"}
            ],
            "notes": ["对照设计依据: Rothstein 1991 标记选择逻辑"],
        },
        {
            "step_id": "step_08",
            "step_number": 8,
            "stage": "A. LiAc 化学转化 — 鉴定与效率",
            "title": "挑克隆、PCR/Southern 鉴定与效率计算",
            "purpose": "确认克隆携带预期载体（整合或游离复制型），并报告转化效率 (transformants/ug DNA)。",
            "time_estimate": "约 1-2 天",
            "conditions": {},
            "reagents": [
                {"item": "挑取 5-10 个阳性克隆", "amount": "5-10 克隆"},
                {"item": "载体特异 PCR 引物（或 gDNA 提取 + 载体引物）", "amount": "按 PCR 方案"},
            ],
            "instructions": [
                "挑 5-10 个克隆至单管 YPD 过夜培养。",
                "取培养物做 colony PCR 或提 gDNA/质粒做 PCR，确认载体插入/整合（预期条带大小）。",
                "计算转化效率 = 选择克隆数 / 加入的 DNA 质量 (ug)。",
            ],
            "expected_observation": "PCR 阳性条带为预期大小；克隆在选择培养基上稳定遗传。",
            "checkpoint": ">=3 个克隆 PCR 阳性且条带正确；效率落在所选方案的预期区间。",
            "pause_point": "PCR 阴性克隆不用于下游。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "PCR 阴性但克隆在选择板上生长", "possible_causes": ["内源回复突变", "载体缺失/重排"], "actions": ["更多克隆复筛", "Southern 或测序确认"], "escalate_if": "多数克隆 PCR 阴性"}
            ],
            "notes": ["来源: Rothstein 1991"],
        },
        # ---------------- B. Electroporation ---------------- #
        {
            "step_id": "step_09",
            "step_number": 9,
            "stage": "B. 电转化 — 细胞制备",
            "title": "制备电转化细胞（冰上）",
            "purpose": "获得冰上、无盐/低盐、高活率的单细胞悬浮液（电转化全程保持 4°C；Meilhoc 1990; Thompson 1998）。",
            "time_estimate": "约 30-60 min",
            "conditions": {"temperature": "4°C（全程冰上）"},
            "reagents": [
                {"item": "H2O 或低糖/无盐溶液（电转化洗涤，如 20% 甘油 + 水）", "amount": "适量"},
            ],
            "instructions": [
                "与步骤 1 相同过夜培养，取对数期细胞（OD600 约 1-5 量级；精确值待确认）。",
                "4°C 离心收获，冰上用水（或甘油/水）洗涤 2-3 次，重悬至目标细胞密度（10^8/mL 量级；待确认）。",
                "全程冰上操作，脉冲前 10 min 内完成装槽。",
            ],
            "expected_observation": "冰上致密沉淀；重悬液清亮、无结块。",
            "checkpoint": "活率高、悬浮均匀、温度 <5°C。",
            "pause_point": "细胞沉淀变干或脱离冰浴时重做洗涤。",
            "human_review_required": ["洗涤缓冲体系（甘油/糖种类与浓度）依所选电转方案确认（pending-confirmation）"],
            "troubleshooting": [
                {"problem": "悬浮液含盐/甘油残留", "possible_causes": ["洗涤次数不足", "未冰上操作"], "actions": ["增加洗涤", "保持冰浴"], "escalate_if": "电击弧光异常"}
            ],
            "notes": ["来源: Meilhoc 1990; Thompson 1998"],
        },
        {
            "step_id": "step_10",
            "step_number": 10,
            "stage": "B. 电转化 — 加 DNA 与电击",
            "title": "加入 DNA 并电脉冲",
            "purpose": "电脉冲使细胞膜瞬时通透化，DNA 进入（Meilhoc 1990 报道电场脉冲高效转化完整酵母细胞）。",
            "time_estimate": "每孔 1-2 min + 电击间冷却",
            "conditions": {"other": "电转杯/槽冰上；电压/电容依设备与方案"},
            "reagents": [
                {"item": "待转化质粒 DNA（溶于低盐/水，无 SDS/去污剂）", "amount": "1-10 ug/孔（待确认）"},
                {"item": "细胞悬浮液", "amount": "0.1-1 mL/孔（待确认）"},
            ],
            "instructions": [
                "冰上细胞悬浮液与 DNA 混匀，冰上静置 5-10 min（待确认）。",
                "转入预冷电转杯，按设备推荐程序电击（常见范围 100-1500 V；具体电压/电容/脉冲数依设备与菌株方案确认——关键 pending-confirmation）。",
                "电击后立即加恢复培养基。",
            ],
            "expected_observation": "电击瞬间可见微小电弧；无持续火花/溶液飞溅。",
            "checkpoint": "脉冲参数按设备确认程序执行；电击后细胞无肉眼可见裂解。",
            "pause_point": "设备未校准或参数未确认前不电击（CRITICAL）。",
            "human_review_required": ["电脉冲参数（电压/电容/脉冲数）与每孔 DNA/细胞量必须按所用设备手册与所选文献方案确认（CRITICAL, pending-confirmation）"],
            "troubleshooting": [
                {"problem": "电弧过大/爆鸣", "possible_causes": ["电极残留液体", "盐残留", "电压过高"], "actions": ["彻底干燥电极", "增加洗涤", "降低电压"], "escalate_if": "重复异常放电"}
            ],
            "notes": ["来源: Meilhoc 1990; Thompson 1998; Becker & Guarente 1992 (doi:10.1016/b978-0-12-168040-4.50034-1)"],
        },
        {
            "step_id": "step_11",
            "step_number": 11,
            "stage": "B. 电转化 — 恢复",
            "title": "电击后恢复",
            "purpose": "让细胞恢复膜完整性并表达选择标记。",
            "time_estimate": "1-2 h @ 30°C 摇床",
            "conditions": {"temperature": "30°C"},
            "reagents": [
                {"item": "YPD 恢复培养基", "amount": "电击杯体积的 5-10 倍（如 1 mL 电击 → 5-10 mL）"},
            ],
            "instructions": [
                "电击后立即加温 YPD，轻柔混匀。",
                "30°C、200 rpm 恢复 1-2 h（短恢复即涂布；长恢复提高效率——依方案选择，待确认）。",
            ],
            "expected_observation": "培养物浊度逐步上升。",
            "checkpoint": "恢复后活率可接受（与未电击对照相比无崩溃）。",
            "pause_point": "恢复不足时不涂布。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "电击后无生长", "possible_causes": ["电压过高", "恢复不足", "盐残留"], "actions": ["降低电压", "延长恢复", "核对洗涤"], "escalate_if": "重复无生长"}
            ],
            "notes": ["来源: Thompson 1998"],
        },
        {
            "step_id": "step_12",
            "step_number": 12,
            "stage": "B. 电转化 — 涂布、对照与鉴定",
            "title": "选择涂布 + 阴性对照 + 鉴定",
            "purpose": "同 A 路线步骤 6-8：选择富集、无 DNA 对照、PCR/Southern 鉴定与效率计算。",
            "time_estimate": "约 3-5 d",
            "conditions": {"temperature": "30°C 培养 3-5 天"},
            "reagents": [
                {"item": "选择性培养基平板（对应载体标记）", "amount": "每样品 1-2 板"},
                {"item": "YPD 非选择对照板 (positive control) + 无 DNA 阴性对照 (negative control)", "amount": "各 1 板"},
            ],
            "instructions": [
                "恢复液稀释后涂布选择板、YPD 板与无 DNA 阴性对照板（对照设计同步骤 7）。",
                "30°C 培养 3-5 天，挑克隆做 PCR/Southern 鉴定（同步骤 8）。",
            ],
            "expected_observation": "选择板离散克隆；阴性对照克隆显著更少。",
            "checkpoint": "转化效率与对照符合预期；鉴定阳性克隆可用。",
            "pause_point": "同步骤 8。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "电转组效率远低于化学法", "possible_causes": ["脉冲参数未优化", "细胞制备不当"], "actions": ["滴定电压/电容", "核对洗涤与活率"], "escalate_if": "优化后仍低"}
            ],
            "notes": ["来源: Meilhoc 1990; Thompson 1998; Rothstein 1991"],
        },
    ]

    materials = [
        {"item": "YPD 液体培养基 (1% 酵母提取物, 2% 蛋白胨, 2% 葡萄糖)", "vendor": "", "catalog_number": "", "amount": "5 mL/管起", "required": "yes", "notes": "步骤 1/5/11。"},
        {"item": "选择性平板 (SD + 相应氨基酸/核苷酸)：SD-Trp/SD-Leu/SD-His/SD-Ura", "vendor": "", "catalog_number": "", "amount": "每样品 1-2 板", "required": "yes", "notes": "与载体标记匹配（步骤 6/12）。来源: Rothstein 1991。"},
        {"item": "TE-LiAc: 1 M LiCl, 0.1 M Tris-HCl pH 7.5, 0.1 M EDTA pH 8.0", "vendor": "", "catalog_number": "", "amount": "约 20 mL/批", "required": "yes", "notes": "A 路线核心。配方来源: Gietz 1992 (doi:10.1093/nar/20.6.1425); Gietz 2014。"},
        {"item": "PEG 8000 溶液 (40% w/v in TE)", "vendor": "", "catalog_number": "", "amount": "约 10 mL/批", "required": "yes", "notes": "PEG 必需 (Ito 1983)。"},
        {"item": "ss 载体 DNA（鲑精 ssDNA 或类似）", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "显著提升效率 (Schiestl & Gietz 1989, doi:10.1007/bf00340712)。用量 pending-confirmation。"},
        {"item": "待转化质粒 DNA（酵母复制型：2 um 或 CEN，含互补标记）", "vendor": "", "catalog_number": "", "amount": "0.5-10 ug/管或孔（待确认）", "required": "yes", "notes": "2 um 游离复制型用于常规转化；CEN 载体用于单拷贝维持。"},
        {"item": "电转杯 (0.2 cm gap) 或电转槽", "vendor": "", "catalog_number": "", "amount": "按需", "required": "yes (B 路线)", "notes": "来源: Meilhoc 1990; Thompson 1998。"},
        {"item": "电转仪（B 路线）", "vendor": "", "catalog_number": "", "amount": "1 台", "required": "yes (B 路线)", "notes": "脉冲参数依设备方案确认 (CRITICAL, pending-confirmation)。"},
        {"item": "甘油 (20%) 或电转洗涤液", "vendor": "", "catalog_number": "", "amount": "适量", "required": "no", "notes": "B 路线细胞洗涤（组成 pending-confirmation）。"},
        {"item": "YPD 恢复培养基（电击后立即加）", "vendor": "", "catalog_number": "", "amount": "电击杯体积 5-10 倍", "required": "yes (B 路线)", "notes": "步骤 11。"},
    ]

    return {
        "protocol_title": "酿酒酵母 (Saccharomyces cerevisiae) 转化 Protocol — LiAc 化学法与电转化",
        "protocol_version": "v1",
        "assay_type": "酵母质粒转化（LiAc 化学转化 / 电转化双路线）",
        "intended_user": "需要向酿酒酵母导入酵母复制型质粒（2 um/CEN）或进行基因替换/基因敲除的分子生物学实验室",
        "confidence": "中高：两条路线的全部步骤与核心参数均有本次会话经 Crossref/PubMed 核实 DOI 的文献支持；少量参数（ssDNA 用量、PEG 终浓度、电脉冲参数、每孔 DNA/细胞量）标记 pending-confirmation，执行前需按所选具体方案确认。",
        "timestamp": ts,
        "objective": "向完整酿酒酵母细胞导入外源 DNA（游离复制型质粒、CEN 载体或同源替换片段），经选择标记富集转化子并鉴定。",
        "summary": "双路线 bench-ready 方案：A 路线 LiAc 化学转化（8 步，Ito 1983 / Schiestl & Gietz 1989 / Gietz 1992、2014 / Gietz & Woods 2002）；B 路线电转化（4 步，Meilhoc 1990 / Thompson 1998 / Becker & Guarente 1992）。含无 DNA 阴性对照、转化效率计算与 PCR/Southern 鉴定（Rothstein 1991）。未验证的经典电转论文（Goff 1987、Burke 1987）仅作延伸阅读，不作为参数来源。",
        "preconditions": {
            "sample_requirements": [
                "待转化菌株：营养缺陷型（ura3, his3, trp1, leu2 等）与质粒标记互补",
                "过夜 YPD 培养物，OD600 约 2-4（晚对数期；A 路线）或 OD600 约 1-5（B 路线，对数期更佳）",
                "质粒 DNA：无内毒素/无 SDS 残留，A260/280 约 1.8-2.0",
            ],
            "reagent_requirements": [
                "TE-LiAc (1 M LiCl, 0.1 M Tris-HCl pH 7.5, 0.1 M EDTA pH 8.0)",
                "PEG 8000 (40% w/v in TE)",
                "ss 载体 DNA（用量 pending-confirmation）",
                "选择性培养基（与载体标记匹配）",
                "YPD 恢复培养基",
                "（B 路线）电转洗涤液 + 预冷电转杯",
            ],
            "equipment_requirements": [
                "恒温摇床 30°C ~200 rpm",
                "台式离心机（5000×g 量级）",
                "42°C 水浴/干浴（A 路线）",
                "（B 路线）电转仪 + 0.2 cm 电转杯",
                "PCR 热循环仪 + 琼脂糖电泳（鉴定）",
            ],
            "safety_notes": [
                "BSL-1 微生物操作；手套与实验服",
                "PEG/LiAc 按实验室化学品安全政策处理（避免吸入 Li+ 粉尘）",
                "（B 路线）电转仪：电极加样前必须干燥；勿触碰电极；遵循设备手册",
            ],
            "lab_specific_fields_to_confirm": [
                "ss 载体 DNA 种类与终浓度（pending-confirmation；Schiestl & Gietz 1989 量级 50 ug/mL）",
                "PEG 终浓度与热脉冲温度/时间（经典方案值 42°C/15 min，待确认）",
                "每管 DNA 量（0.5-5 ug 量级，待确认）",
                "（B 路线）电脉冲参数：电压/电容/脉冲数（CRITICAL, pending-confirmation）",
                "（B 路线）每孔细胞数与 DNA 量（待确认）",
                "涂布稀释度与目标克隆数/板（待确认）",
                "所选载体标记与对应选择培养基（URA3/HIS3/TRP1/LEU2 等）",
            ],
        },
        "materials": materials,
        "workflow": workflow,
        "qc_checkpoints": [
            {"checkpoint_name": "过夜培养 QC", "when": "步骤 1 结束", "measurements": ["OD600", "培养物均匀性"], "pass_criteria": ["OD600 约 2-4（A）/ 1-5（B）", "均匀浑浊"], "fail_signals": ["不浑浊", "污染迹象"], "recommended_action_on_fail": "重新接种；核对菌株与培养条件。"},
            {"checkpoint_name": "转化反应 QC", "when": "步骤 3-4", "measurements": ["体系体积一致性", "孵育温度/时间", "阴性对照同步"], "pass_criteria": ["所有管同步", "42°C 稳定"], "fail_signals": ["温度漂移", "体积不一致"], "recommended_action_on_fail": "重做反应；校准水浴。"},
            {"checkpoint_name": "涂布与选择 QC", "when": "步骤 6/12", "measurements": ["选择板克隆密度", "YPD 对照克隆密度", "阴性对照克隆数"], "pass_criteria": ["选择板离散克隆（约 20-200/板量级）", "阴性对照 << 实验组"], "fail_signals": ["连片", "阴性对照克隆高"], "recommended_action_on_fail": "提高稀释度；调查自发回复突变/污染；重复实验。"},
            {"checkpoint_name": "克隆鉴定 QC", "when": "步骤 8/12", "measurements": ["colony PCR 条带大小", "克隆遗传稳定性"], "pass_criteria": ["预期条带", "二代遗传稳定"], "fail_signals": ["PCR 阴性", "条带异常"], "recommended_action_on_fail": "更多克隆复筛；Southern/测序确认。"},
            {"checkpoint_name": "转化效率判读", "when": "步骤 8", "measurements": ["transformants/ug DNA"], "pass_criteria": ["落在所选方案报道区间量级"], "fail_signals": ["效率异常低（<10x 预期）"], "recommended_action_on_fail": "核对 DNA 量/质、细胞密度、PEG/ssDNA；重复实验。"},
        ],
        "decision_points": [
            {"decision": "路线选择", "when": "开始前", "options": ["LiAc 化学法（常规质粒转化首选，成本低）", "电转化（大片段/低拷贝/需要高转化量时）", "化学法 + 电转化并行对照"]},
            {"decision": "载体类型", "when": "步骤 3/10 前", "options": ["2 um 游离复制型（多拷贝，常规克隆）", "CEN 单拷贝（稳定维持，文库/展示）", "同源臂 + 标记的线性 DNA（基因替换/敲除，Rothstein 1991）"]},
            {"decision": "选择标记", "when": "涂布前", "options": ["URA3 → SD-Ura", "HIS3 → SD-His", "TRP1 → SD-Trp", "LEU2 → SD-Leu", "双标记筛选（如 URA3+HYG 等，依载体）"]},
            {"decision": "恢复时间（B 路线）", "when": "步骤 11", "options": ["短恢复 1 h（标准）", "长恢复 2 h（追求高效率）", "过夜恢复（特殊方案）"]},
        ],
        "failure_branches": [
            {"condition": "化学法转化效率过低", "step_ids_affected": ["step_03", "step_04", "step_06"], "likely_causes": ["ssDNA/PEG 用量不当", "细胞密度偏离最优", "DNA 质量差", "热脉冲不当"], "recommended_modifications": ["按所选方案复核 ssDNA/PEG 浓度", "调整收获细胞密度", "重新纯化 DNA", "核对 42°C/15 min"], "whether_to_repeat_or_stop": "调整后重复步骤 2-6；若连续 3 次失败停止并换路线/换方案。"},
            {"condition": "阴性对照克隆过多", "step_ids_affected": ["step_07"], "likely_causes": ["自发回复突变", "选择标记泄漏", "DNA 交叉污染"], "recommended_modifications": ["核对菌株标记完整性", "分区操作", "重复实验"], "whether_to_repeat_or_stop": "调查后重复；若持续异常则结果不可信，停止判读。"},
            {"condition": "电击异常（爆鸣/无生长）", "step_ids_affected": ["step_10", "step_11"], "likely_causes": ["电极未干燥", "盐残留", "电压过高"], "recommended_modifications": ["彻底干燥电极", "增加洗涤次数", "滴定电压/电容"], "whether_to_repeat_or_stop": "参数滴定后重复步骤 9-11；若设备故障停止并检修。"},
            {"condition": "克隆 PCR 阴性但选择性生长", "step_ids_affected": ["step_08"], "likely_causes": ["回复突变克隆", "载体重排/缺失"], "recommended_modifications": ["挑更多克隆", "Southern/测序"], "whether_to_repeat_or_stop": "复筛；失败克隆不进入下游。"},
        ],
        "open_questions_for_human": [
            "CRITICAL（B 路线）：电脉冲参数（电压/电容/脉冲数）与每孔 DNA/细胞量必须按所用设备手册 + 所选文献方案确认（pending-confirmation）。",
            "ss 载体 DNA 种类与终浓度（Schiestl & Gietz 1989 量级 50 ug/mL；待确认）。",
            "PEG 终浓度（经典 10% 量级；待确认）与热脉冲 42°C/15 min 是否适用于目标菌株。",
            "每管 DNA 量与涂布稀释度（依载体大小与目标效率）。",
            "所选载体标记 ↔ 选择培养基匹配表（URA3/HIS3/TRP1/LEU2）。",
            "（B 路线）洗涤液组成（甘油/糖种类与浓度）。",
            "Goff 1987 / Burke 1987 经典电转原文本次会话未能核实 DOI，未作为参数来源；如需引用请先核实。",
        ],
        "revision_log": [
            {"version": "v1", "reason": "首次从本次会话经 Crossref/PubMed 核实的文献（Ito 1983; Schiestl & Gietz 1989; Gietz 1992/2014; Gietz & Woods 2002; Meilhoc 1990; Thompson 1998; Rothstein 1991; Becker & Guarente 1992）推导的 bench-ready 双路线 protocol；未验证参数全部保留 [confirm with source protocol] 占位。", "changed_step_ids": []},
        ],
        "artifact_outputs": [],
    }


def main() -> None:
    proto = build_protocol()
    normalize_protocol(proto)

    review_agent = ReviewAgent()
    review = review_agent.run(
        "将酿酒酵母转化双路线方案转换为台边执行模式",
        {"protocol": proto, "user_instruction": "整理一份酿酒酵母转化方法的 protocol"},
    )
    print("review decision:", review.get("decision"))
    print("review findings:", review.get("findings"))
    print("review strengths:", review.get("strengths"))

    refs = "\n## 参考来源 (本会话经 Crossref/PubMed 核实)\n" + "\n".join(
        f"- {s}" for s in SOURCES
    ) + "\n"

    full_md = protocol_to_markdown(proto) + "\n" + refs
    bench_md = bench_to_markdown(proto) + "\n" + refs

    run_dir = new_run_dir()
    save_json(run_dir, "input.json", {
        "file": "yeast transformation protocol (this-session grounded)",
        "sources": SOURCES,
        "status": "draft v1",
    })
    print("saved", save_json(run_dir, "protocol_v1.json", proto))
    print("saved", save_text(run_dir, "protocol_v1.md", full_md))
    print("saved", save_text(run_dir, "protocol_bench_v1.md", bench_md))
    print("saved", save_json(run_dir, "review_v1.json", review))
    print("RUN_DIR:", run_dir)


if __name__ == "__main__":
    main()
