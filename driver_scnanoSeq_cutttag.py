"""
Driver (zh): build a bench-ready scNanoSeq-CUT&Tag protocol (single-cell
long-read CUT&Tag on Oxford Nanopore, Li et al. 2024 Nat Methods) with the
lab-protocol-agent's deterministic components (save_artifact renderers +
ReviewAgent checks).

Grounding policy (per workspace AGENTS.md): the source protocol (Li et al.
2024, Nat Methods 21:2044-2057, doi:10.1038/s41592-024-02453-w) is
subscription-only; NO open-access full text was found in this session
(Unpaywall: no OA URL; GitHub repo Guo-Yuqing/scNanoSeq-CUT-Tag contains the
analysis pipeline only; no bioRxiv preprint found). Therefore:
  - Wet-lab parameters that could not be verified from the full text are
    tagged "[confirm with source protocol]" (pending-confirmation).
  - The analysis-pipeline parameters below are taken verbatim from the
    project GitHub README (fetched this session).
  - Wet-lab parameters from the closely related droplet method dscNanoSeq
    (Lu et al. 2026, Cell Discovery, doi:10.1038/s41421-026-00928-y, PMC full
    text) appear ONLY in the clearly labeled comparison section and are NOT
    presented as scNanoSeq-CUT&Tag parameters.
  - CUT&Tag method origin: Kaya-Okur et al. 2019 (Nat Commun) is the original
    CUT&Tag paper (Tn5-protein A/G fusion, in-situ tagmentation, single-cell
    microwell format). Skene & Henikoff 2017 (eLife, doi:10.7554/eLife.21856)
    is the related CUT&RUN paper (antibody-targeted MNase cleavage); it is
    cited only as a related-method context, NOT as the source of the Tn5
    tagmentation concept.
No parameter is invented.
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
# Sources verified IN THIS SESSION (Crossref / PubMed / PMC / GitHub).
# --------------------------------------------------------------------------- #
SOURCES = [
    "Li Q, Guo Y, Wu Z, Xu X, Jiang Z, Qi S, Liu Z, Wen L, Tang F. 2024. scNanoSeq-CUT&Tag: a single-cell long-read CUT&Tag sequencing method for efficient chromatin modification profiling within individual cells. Nat Methods 21(11):2044-2057. doi:10.1038/s41592-024-02453-w (PRIMARY SOURCE; full text paywalled — wet-lab details pending-confirmation)",
    "Kaya-Okur HS, Wu SJ, Codomo CA, Pledger ES, Bryson TD, Henikoff JG, Ahmad K, Henikoff S. 2019. CUT&Tag for efficient epigenomic profiling of small samples and single cells. Nat Commun 10. doi:10.1038/s41467-019-09982-5 (preprint doi:10.1101/568915; ORIGINAL CUT&Tag paper: protein A-Tn5 transposase fusion, in-situ tagmentation, single tube/microwell single cells)",
    "Kaya-Okur HS, Janssens DH, Henikoff JG, Ahmad K, Henikoff S. 2020. Efficient low-cost chromatin profiling with CUT&Tag. Nat Protoc 15(10):3264-3283. doi:10.1038/s41596-020-0373-x (official CUT&Tag wet-lab protocol reference; details not extracted this session — Li 2024 parameters still pending-confirmation)",
    "Skene PJ, Henikoff S. 2017. An efficient targeted nuclease strategy for high-resolution mapping of DNA binding sites. eLife 6:e21856. doi:10.7554/eLife.21856 (original CUT&RUN method; related in-situ antibody-targeted cleavage — NOT the source of the Tn5 tagmentation concept)",
    "Bartosovic M, Castelo-Branco G. 2022. Multimodal chromatin profiling using nanobody-based single-cell CUT&Tag. Nat Biotechnol 41(6):794-805. doi:10.1038/s41587-022-01535-4 (nano-CT; nanobody-Tn5 fusions, 25,000-200,000 cells)",
    "Lu J, Chen K, Jia S, Chen G, Yu X, Li W. 2026. A droplet-based long-read single-cell epigenome sequencing method for the high-throughput profiling of multidimensional regulatory elements within individual cells. Cell Discovery 12. doi:10.1038/s41421-026-00928-y (RELATED METHOD dscNanoSeq; PMC full text — used only in the comparison section)",
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
        # ---------------- A. Sample preparation ---------------- #
        {
            "step_id": "step_01",
            "step_number": 1,
            "stage": "A. 样本制备",
            "title": "细胞收获与核分离（可选）",
            "purpose": "获得单细胞/单核悬液。scNanoSeq-CUT&Tag 适配于单细胞（Li et al. 2024 摘要：within individual cells）；CUT&Tag 原始方法自活细胞单管/微孔即可完成全流程（Kaya-Okur 2019）。",
            "time_estimate": "约 30-60 min",
            "conditions": {"temperature": "4°C 操作"},
            "reagents": [
                {"item": "目标细胞系/组织（对数期或新鲜解离）", "amount": CONFIRM},
                {"item": "核分离裂解液（如含 digitonin/sucrose 体系，参考相关长读长单细胞方案）", "amount": CONFIRM},
                {"item": "40 um 滤网（去核分离杂质，若走核路线）", "amount": "1 个/样品"},
                {"item": "DAPI（核染色与计数）", "amount": CONFIRM},
            ],
            "instructions": [
                "收获活细胞或组织，4°C PBS 洗涤；如需核路线，裂解后离心收集核（转速/时间 pending-confirmation）。",
                "核路线经 40 um 滤网过滤、DAPI 染色计数；细胞路线直接计数。",
                "将细胞/核调整至目标每孔装载浓度（每孔细胞数 pending-confirmation）。",
            ],
            "expected_observation": "均匀单核/单细胞悬液，DAPI 阳性细胞/核为主。",
            "checkpoint": "悬液均匀、无大团块；活率/核完整性可接受。",
            "pause_point": "细胞/核状态不佳（大量碎片或死细胞）时重做制备。",
            "human_review_required": [
                "每孔装载细胞/核数与核分离缓冲液配方依 Li et al. 2024 原文 Methods 确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "核碎片多/悬浮不均", "possible_causes": ["裂解条件过强", "过滤不充分"], "actions": ["优化裂解", "增加过滤/换 40 um 滤网"], "escalate_if": "重复后仍差"}
            ],
            "notes": ["来源: Li et al. 2024 (摘要); Kaya-Okur 2019 (CUT&Tag 原始方法); Skene & Henikoff 2017 仅相关 CUT&RUN 背景"],
        },
        # ---------------- B. Single-cell CUT&Tag ---------------- #
        {
            "step_id": "step_02",
            "step_number": 2,
            "stage": "B. 单细胞 CUT&Tag — 固定与透化",
            "title": "固定、透化与封闭",
            "purpose": "固定染色质并透化膜以便抗体进入（CUT&Tag 为 in-situ 反应，通常固定后透化；Kaya-Okur 2019 单细胞方案为活细胞/固定细胞皆可）。",
            "time_estimate": "约 30-60 min",
            "conditions": {"temperature": "4°C-室温"},
            "reagents": [
                {"item": "甲醛固定液（终浓度约 0.5-1% 量级，pending-confirmation）", "amount": CONFIRM},
                {"item": "透化剂（digitonin/Triton X-100 体系，pending-confirmation）", "amount": CONFIRM},
                {"item": "封闭液（BSA/血清，pending-confirmation）", "amount": CONFIRM},
            ],
            "instructions": [
                "细胞/核悬液加甲醛固定（浓度与时间 pending-confirmation），淬灭后洗涤。",
                "透化剂处理使膜通透（浓度/时间 pending-confirmation），加封闭液阻断非特异结合。",
                "全程冰上/4°C，避免 chromatin 损失。",
            ],
            "expected_observation": "细胞/核保持完整，透化后核染色质可被抗体接触（无肉眼可见结构变化）。",
            "checkpoint": "透化后无大量沉淀/裂解物释放（显微镜可抽查核完整性）。",
            "pause_point": "核大量裂解时降低透化强度重做。",
            "human_review_required": [
                "固定剂浓度/时间、透化剂种类/浓度/时间、封闭体系依 Li et al. 2024 原文确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "透化不足（后续信号低）或过度（背景高/DNA 释放）", "possible_causes": ["透化剂浓度不当", "透化时间不当"], "actions": ["滴定透化剂", "调整时间"], "escalate_if": "两轮滴定仍不可接受"}
            ],
            "notes": ["来源: Kaya-Okur 2019; 细节 pending-confirmation (Li 2024 全文不可得)"],
        },
        {
            "step_id": "step_03",
            "step_number": 3,
            "stage": "B. 单细胞 CUT&Tag — 抗体孵育",
            "title": "一抗孵育（组蛋白修饰/转录因子）",
            "purpose": "抗体靶向目标组蛋白修饰或转录因子，将 Tn5 募集到目标位点（CUT&Tag 核心原理，Kaya-Okur 2019）。scNanoSeq-CUT&Tag 的 GitHub README 聚类参数段列出 H3K4me3、H3K27ac、H3K36me3、CTCF、RAD21、H3K27me3、H3K9me3 等标记的 ArchR minTSS 参数；Li et al. 2024 摘要仅述'高效组蛋白修饰/TF profiling'，标记是否逐一 verified 待原文确认。",
            "time_estimate": "4°C 过夜",
            "conditions": {"temperature": "4°C 过夜", "speed": "缓慢旋转"},
            "reagents": [
                {"item": "一抗（组蛋白修饰，如 anti-H3K4me3/H3K27ac/H3K27me3 等，ENCODE 验证过）", "amount": CONFIRM},
                {"item": "no-antibody / isotype 阴性对照抗体 (negative control, isotype)", "amount": "与实验组等量"},
                {"item": "抗体孵育缓冲液（含 BSA/digitonin 维持透化，pending-confirmation）", "amount": CONFIRM},
            ],
            "instructions": [
                "透化封闭后的细胞/核加入一抗，4°C 过夜缓慢旋转（稀释度 pending-confirmation）。",
                "同批同步设置 no-antibody 阴性对照（不加一抗或换同型对照抗体），其余步骤完全相同。",
                "次日洗涤去除未结合抗体（次数 pending-confirmation）。",
            ],
            "expected_observation": "无可见变化；对照与实验组处理一致。",
            "checkpoint": "一抗与对照同批、同浓度体系；洗涤后无沉淀异常。",
            "pause_point": "抗体来源/稀释度未确认前不进入步骤 4（CRITICAL）。",
            "human_review_required": [
                "一抗供应商/货号/稀释度依 Li et al. 2024 原文确认（CRITICAL, pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "信号过低或背景过高", "possible_causes": ["抗体稀释度不当", "透化不当", "固定不当"], "actions": ["滴定抗体", "回到步骤 2 优化"], "escalate_if": "滴定后仍差"}
            ],
            "notes": ["来源: Kaya-Okur 2019 (CUT&Tag 原理); 标记清单: Li et al. 2024 (摘要) + GitHub README 聚类参数段; verified 状态待原文确认"],
        },
        {
            "step_id": "step_04",
            "step_number": 4,
            "stage": "B. 单细胞 CUT&Tag — Tn5 tagmentation",
            "title": "加入 Tn5-protein A/G 并 tagmentation",
            "purpose": "Tn5 融合蛋白通过 protein A/G 结合抗体，在目标位点切割 DNA 并插入转座末端（tagmentation；Kaya-Okur 2019）。单细胞格式下在微孔/96 孔板逐孔进行（Kaya-Okur 2019）。",
            "time_estimate": "37°C 10-30 min（经典单细胞 CUT&Tag 量级；精确值 pending-confirmation）",
            "conditions": {"temperature": "37°C", "speed": "旋转混匀"},
            "reagents": [
                {"item": "Tn5-protein A/G fusion（商业化 Tn5 转座酶复合物）", "amount": CONFIRM},
                {"item": "tagmentation 缓冲液（Mg2+ 体系，pending-confirmation）", "amount": CONFIRM},
            ],
            "instructions": [
                "洗涤后的抗体-染色质复合物重悬于 tagmentation 缓冲液。",
                "加入 Tn5-protein A/G，37°C 旋转孵育（时间 pending-confirmation）。",
                "no-antibody 对照孔同步进行（不加 Tn5 或加同型对照，依 Li et al. 2024 设计确认；pending-confirmation）。",
                "反应终止：加 EDTA 终止缓冲液，4°C 短暂停反应（终止体系 pending-confirmation）。",
            ],
            "expected_observation": "无肉眼变化；反应液清亮。",
            "checkpoint": "各孔体积一致、同步计时；37°C 稳定。",
            "pause_point": "Tn5 用量/时间未确认前不做正式孔板（CRITICAL）。",
            "human_review_required": [
                "Tn5-protein A/G 用量、tagmentation 缓冲液组成与时间、终止体系依 Li et al. 2024 原文确认（CRITICAL, pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "片段过多（切过头）或过少", "possible_causes": ["Tn5 过量/不足", "时间不当", "Mg2+ 浓度不当"], "actions": ["滴定 Tn5 与时间"], "escalate_if": "两轮滴定仍异常"}
            ],
            "notes": ["来源: Kaya-Okur 2019 (CUT&Tag 原理)"],
        },
        {
            "step_id": "step_05",
            "step_number": 5,
            "stage": "B. 单细胞 CUT&Tag — 产物回收",
            "title": "裂解、离心与 SPRI 纯化",
            "purpose": "释放 tagmented 目标 DNA 并用 SPRI 磁珠纯化长片段产物（单细胞 CUT&Tag 标准下游；Kaya-Okur 2019）。",
            "time_estimate": "约 30-60 min",
            "conditions": {"other": "冰上操作"},
            "reagents": [
                {"item": "裂解/洗涤缓冲液", "amount": CONFIRM},
                {"item": "SPRI 磁珠（Ampure 或同等）", "amount": CONFIRM},
                {"item": "80% 乙醇", "amount": "适量"},
            ],
            "instructions": [
                "tagmentation 终止后裂解细胞/核，离心收集上清（含目标 DNA）。",
                "SPRI 磁珠按目标片段大小选择性纯化（珠:DNA 比例 pending-confirmation；长读长应用需保留较长片段）。",
                "乙醇洗涤后水/洗脱缓冲液洗脱，冰上待用。",
            ],
            "expected_observation": "上清含 DNA（可用微量分光光度计抽查）。",
            "checkpoint": "纯化产物无明显蛋白污染；浓度可测。",
            "pause_point": "浓度极低时检查步骤 2-4 是否损失。",
            "human_review_required": [
                "SPRI 珠比与洗脱体积依 Li et al. 2024 原文确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "产物产量低", "possible_causes": ["透化/Tn5 步骤损失", "磁珠比例不当"], "actions": ["回顾步骤 2-4", "调整珠比"], "escalate_if": "重复仍低"}
            ],
            "notes": ["来源: Kaya-Okur 2019"],
        },
        # ---------------- C. Long-read library ---------------- #
        {
            "step_id": "step_06",
            "step_number": 6,
            "stage": "C. 长读长文库构建 — 单细胞条形码",
            "title": "加接头与单细胞条形码 (barcode ligation)",
            "purpose": "为每个孔/单细胞文库加接头并引入单细胞条形码，使测序后能 demultiplex 到单细胞（scNanoSeq-CUT&Tag 核心设计：长读长 + 单细胞 barcode；Li et al. 2024 摘要 'within individual cells'；GitHub README 预处理段含 barcode_inner.fa / barcode_outer.fa 双端 barcode 文件）。",
            "time_estimate": "约 1-2 h",
            "conditions": {"other": "冰上/室温依接头方案"},
            "reagents": [
                {"item": "Nanopore 接头 + 单细胞 barcode 寡核苷酸（内/外双端 barcode，项目提供 barcode_inner.fa / barcode_outer.fa）", "amount": CONFIRM},
                {"item": "连接/连接酶体系（或 PCR 加 barcode，依 Li et al. 2024 设计）", "amount": CONFIRM},
            ],
            "instructions": [
                "纯化 DNA 按孔/按样品加接头与对应 barcode（barcode 分配表需与孔板布局一致）。",
                "连接反应（温度/时间 pending-confirmation）。",
                "barcode 白名单（whitelist）在生信 demux 时使用（见步骤 10）。",
            ],
            "expected_observation": "无可见变化。",
            "checkpoint": "barcode 分配表与孔位一一对应；无交叉污染（操作分区）。",
            "pause_point": "barcode 体系未确认前不做正式文库（CRITICAL）。",
            "human_review_required": [
                "接头/barcode 设计（内/外 barcode 序列长度与分配方案）依 Li et al. 2024 原文确认（CRITICAL, pending-confirmation；GitHub README 仅列出 barcode_inner.fa / barcode_outer.fa 文件名）"
            ],
            "troubleshooting": [
                {"problem": "barcode 交叉污染/错配", "possible_causes": ["操作交叉", "barcode 序列相似度过高"], "actions": ["分区操作", "核对 whitelist"], "escalate_if": "demux 后交叉率高"}
            ],
            "notes": ["来源: Li et al. 2024 (摘要 + GitHub README 文件列表); 细节 pending-confirmation"],
        },
        {
            "step_id": "step_07",
            "step_number": 7,
            "stage": "C. 长读长文库构建 — QC",
            "title": "文库 QC（片段长度分布）",
            "purpose": "确认长读长文库片段长度分布适合 Nanopore 测序且长片段（co-occupancy 分析依赖 >1 kb 长片段，GitHub README 06_co_peaks 段）占比可接受。",
            "time_estimate": "约 1 h",
            "conditions": {},
            "reagents": [
                {"item": "片段长度检测（qPCR/琼脂糖凝胶/Nanopore 测序自带 QC，依平台）", "amount": "按需"},
            ],
            "instructions": [
                "测文库浓度与片段长度分布。",
                "确认长片段（尤其 >1 kb）比例满足 co-occupancy 分析（GitHub README：'Only save reads length > 1 kb for calculation'）。",
                "不合格文库回步骤 5/6 排查。",
            ],
            "expected_observation": "片段分布峰值在数百 bp 至数 kb（长读长 CUT&Tag 特征；精确分布 pending-confirmation）。",
            "checkpoint": "浓度/分布达标（阈值 pending-confirmation）。",
            "pause_point": "分布异常（过多短片段）时暂停测序。",
            "human_review_required": [
                "QC 通过阈值依 Li et al. 2024 原文确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "短片段过多", "possible_causes": ["tagmentation 过切", "SPRI 比例偏向短片段"], "actions": ["调 Tn5", "调 SPRI 比例"], "escalate_if": "调整后仍差"}
            ],
            "notes": ["来源: GitHub README (06_co_peaks); 阈值 pending-confirmation"],
        },
        # ---------------- D. Sequencing ---------------- #
        {
            "step_id": "step_08",
            "step_number": 8,
            "stage": "D. Oxford Nanopore 测序",
            "title": "Nanopore 测序（PromethION/MinION）",
            "purpose": "长读长单分子测序读取单细胞 tagmented 片段（scNanoSeq-CUT&Tag 平台；Li et al. 2024 摘要：nanopore sequencing platform）。",
            "time_estimate": "测序 1-3 天（依平台与通量）",
            "conditions": {"other": "依 Nanopore 平台操作手册"},
            "reagents": [
                {"item": "Nanopore 文库转座/加载试剂（Ligation Kit 或同级，依 ONT 当前方案）", "amount": "按 ONT 手册"},
                {"item": "Flow cell（R10.4.1 或同级；平台选择 pending-confirmation）", "amount": "按需"},
            ],
            "instructions": [
                "按 ONT 当前 ligation kit 手册制备测序文库。",
                "加载 flow cell，启动测序；记录运行 ID 与通量。",
                "每文库目标深度 pending-confirmation（Li et al. 2024 未公开于摘要；相关长读长单细胞方案 dscNanoCUT 约 0.01 Gb/cell 量级，仅作量级参考，Lu et al. 2026）。",
            ],
            "expected_observation": "测序正常产生长 reads（平均长度数百 bp-kb 量级）。",
            "checkpoint": "运行无严重错误；产出 fastq 完整。",
            "pause_point": "运行失败则换 flow cell 重测。",
            "human_review_required": [
                "测序平台/flow cell 与每细胞目标深度依 Li et al. 2024 原文确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "reads 平均长度过低", "possible_causes": ["文库片段偏短", "加载问题"], "actions": ["回步骤 7", "核对加载"], "escalate_if": "重复仍短"}
            ],
            "notes": ["来源: Li et al. 2024 (摘要); 深度量级参考: Lu et al. 2026 (相关方法, 非 scNanoSeq-CUT&Tag 参数)"],
        },
        # ---------------- E. Bioinformatics ---------------- #
        {
            "step_id": "step_09",
            "step_number": 9,
            "stage": "E. 生信 — 预处理",
            "title": "Demultiplex、trim、比对 (per GitHub README)",
            "purpose": "按单细胞 barcode 拆分为单细胞 reads，去接头并比对到参考基因组（GitHub README 01_preprocess：nanoplexer v0.1 拆库；NanoFilt v2.8.0 / cutadapt v3.5 去接头；minimap2 v2.26-r1175 比对 hg38/mm10；samtools v1.3）。",
            "time_estimate": "数小时（CPU 集群）",
            "conditions": {"other": "bash 脚本（项目 01_preprocess）"},
            "reagents": [
                {"item": "nanoplexer (v0.1) — 按文库/barcode 拆分", "amount": "工具"},
                {"item": "NanoFilt (v2.8.0) / cutadapt (v3.5) — 过滤去接头", "amount": "工具"},
                {"item": "minimap2 (v2.26-r1175) + samtools (v1.3) — 比对 hg38 / mm10", "amount": "工具"},
                {"item": "barcode 白名单 (barcode_inner.fa / barcode_outer.fa)", "amount": "项目文件"},
            ],
            "instructions": [
                "运行 S01_pkubatch_01_demultiplex.sh（按 pass.fastq.gz 与孔板布局拆库）。",
                "运行 S02_pkubatch_02_trim_mapping.sh（trim + 比对，输出单细胞 bam）。",
                "检查 demux 效率（有效 barcode reads 比例；阈值 pending-confirmation）。",
            ],
            "expected_observation": "每个有效孔产出单细胞 bam；demux 有效率可计算。",
            "checkpoint": "demux 有效率与比对率达标（阈值 pending-confirmation）。",
            "pause_point": "demux 效率过低时回查步骤 6 barcode 体系。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "demux 有效率低", "possible_causes": ["barcode 序列错误/交叉", "测序质量差"], "actions": ["核对 whitelist", "查原始数据质量"], "escalate_if": "重复仍低"}
            ],
            "notes": ["来源: GitHub README 01_preprocess（本会话获取原文）"],
        },
        {
            "step_id": "step_10",
            "step_number": 10,
            "stage": "E. 生信 — 聚类与信号提取",
            "title": "ArchR 信号提取与聚类 (per GitHub README)",
            "purpose": "提取染色质修饰信号、聚类单细胞轮廓（GitHub README 02_clustering：ArchR v1.0.1；活性标记 minTSS=1，抑制性标记 minTSS=0.1）。",
            "time_estimate": "数小时-1 天",
            "conditions": {"other": "R / ArchR"},
            "reagents": [
                {"item": "ArchR (v1.0.1)", "amount": "工具"},
            ],
            "instructions": [
                "运行 03_prearchr.sh $antibody（信号提取）。",
                "运行 04_archr.R $antibody：活性标记（H3K4me3, H3K27ac, H3K36me3, CTCF, RAD21）设 minTSS=1；抑制性标记（H3K27me3, H3K9me3）设 minTSS=0.1。",
                "产出 cell type mark genes 与 coverage track。",
            ],
            "expected_observation": "聚类后细胞类型分群可辨识；TSS enrichment 分布合理。",
            "checkpoint": "各抗体参数按 README 设置无遗漏。",
            "pause_point": "聚类异常（无分群）时回查 demux/质量。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "TSS enrichment 低", "possible_causes": ["demux 错配", "片段提取错误"], "actions": ["核对 barcode 比对", "重跑 03/04"], "escalate_if": "重复仍低"}
            ],
            "notes": ["来源: GitHub README 02_clustering（本会话获取原文）"],
        },
        {
            "step_id": "step_11",
            "step_number": 11,
            "stage": "E. 生信 — peak calling",
            "title": "SEACR 单细胞 peak calling (per GitHub README)",
            "purpose": "单细胞 peak calling（GitHub README 03_peak_calling：SEACR v1.3 'non stringent 0.05'；保留 ≥(1.5% × 总细胞数) 且 ≥5 cells 支持的 peaks）。",
            "time_estimate": "数小时",
            "conditions": {"other": "bash / SEACR"},
            "reagents": [
                {"item": "SEACR (v1.3)", "amount": "工具"},
            ],
            "instructions": [
                "运行 sbatch_get_fragment_callpeak.sh（SEACR non stringent 0.05）。",
                "保留被至少 max(1.5% × 总细胞数, 5) 个细胞支持的 peaks。",
            ],
            "expected_observation": "peak 集合与预期标记分布一致（活性标记 TSS 富集等）。",
            "checkpoint": "peak 支持细胞数阈值严格执行。",
            "pause_point": "无。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "peak 数异常（过多/过少）", "possible_causes": ["噪声", "细胞数不足"], "actions": ["检查质量", "确认细胞数"], "escalate_if": "不可解释"}
            ],
            "notes": ["来源: GitHub README 03_peak_calling（本会话获取原文）"],
        },
        {
            "step_id": "step_12",
            "step_number": 12,
            "stage": "E. 生信 — 下游分析（可选）",
            "title": "质量评估 / ASP / co-occupancy / 重复元件 (per GitHub README)",
            "purpose": "按研究问题选择下游模块（GitHub README 04-07）：交叉污染评估（04_cross_condamination）、最优通量 downsampling（04_optimal_throughput）、可重复性相关性（04_reproducibility）、等位基因特异性 ASPs（05：whatshap v1.6 分相 + binom.test 检验）、co-occupancy（06：reads >1 kb、左右 peak pval adj <0.01）、重复元件全长检测（07：人 T2T 320 全长 L1HS；小鼠 L1Base 全长 LINE）。",
            "time_estimate": "数小时-数天/模块",
            "conditions": {"other": "R / bash"},
            "reagents": [
                {"item": "whatshap (v1.6)、GenMap (v1.3.0)、deepTools (v3.5.1)、blast (v2.5.0)", "amount": "工具"},
                {"item": "T2T 人参考基因组（重复元件分析）", "amount": "参考"},
            ],
            "instructions": [
                "按需运行对应模块脚本（README 中 sbatch/Rscript 命令）。",
                "ASPs 用原始未去重 bam（README：高错误率三代数据，用 HetSNPs + duplicate reads 校正分相）。",
                "co-occupancy 仅保留 >1 kb reads 计算。",
            ],
            "expected_observation": "各模块产出按 README 预期。",
            "checkpoint": "模块参数与 README 一致。",
            "pause_point": "无。",
            "human_review_required": [],
            "troubleshooting": [
                {"problem": "ASPs 检出异常", "possible_causes": ["分相错误", "SNP 质量差"], "actions": ["核对 HetSNP 过滤", "重跑分相"], "escalate_if": "不可解释"}
            ],
            "notes": ["来源: GitHub README 04-07（本会话获取原文）"],
        },
        # ---------------- F. Controls ---------------- #
        {
            "step_id": "step_13",
            "step_number": 13,
            "stage": "F. 对照设计",
            "title": "no-antibody 阴性对照与输入对照 (negative control design)",
            "purpose": "确认信号来自抗体特异性靶向而非 Tn5 非特异切割（CUT&Tag 标准对照逻辑：Kaya-Okur 2019 报道低背景，其方案含无抗体/no-Tn5 对照；Li et al. 2024 摘要同）。",
            "time_estimate": "与步骤 3-8 并行",
            "conditions": {},
            "reagents": [
                {"item": "no-antibody 对照（不加一抗，其余完全相同）", "amount": "与实验组等量"},
                {"item": "isotype 对照抗体（可选，依 Li et al. 2024 设计）", "amount": "与实验组等量"},
            ],
            "instructions": [
                "no-antibody 对照孔走完全相同流程（步骤 2-8），用于扣除非特异 Tn5 切割背景。",
                "peak 分析时实验组 peaks 应显著富集于对照之上（FRiP/overlap 判读；GitHub README 04_evaluate_data_quality 提供相关性/交叉污染评估脚本）。",
                "具体对照孔数与判读阈值 pending-confirmation（Li et al. 2024 原文）。",
            ],
            "expected_observation": "no-antibody 对照信号显著低于实验组，无特异性 peak 富集。",
            "checkpoint": "对照与实验组同批同步处理。",
            "pause_point": "对照信号异常高时结果不可信。",
            "human_review_required": [
                "对照设计细节（no-Tn5 孔、isotype 孔、spike-in 等是否使用）依 Li et al. 2024 原文确认（pending-confirmation）"
            ],
            "troubleshooting": [
                {"problem": "no-antibody 背景高", "possible_causes": ["透化/固定不当", "Tn5 过量", "非特异 Fc 结合"], "actions": ["优化步骤 2-4", "核对 Tn5 用量"], "escalate_if": "优化后仍高"}
            ],
            "notes": ["来源: Kaya-Okur 2019; Li et al. 2024 (摘要); GitHub README 04"],
        },
        {
            "step_id": "step_14",
            "step_number": 14,
            "stage": "F. 结果判读",
            "title": "判读与报告",
            "purpose": "综合 QC 指标与生物学结果判读（Li et al. 2024 摘要声明的能力：单细胞组蛋白/TF 占据、细胞类型分辨、等位基因特异性、重复元件拷贝级检测、blacklist 区域分析）。",
            "time_estimate": "半天-1 天",
            "conditions": {},
            "reagents": [],
            "instructions": [
                "汇总 QC：demux 有效率、TSS enrichment、peak 支持细胞数、FRiP/overlap（对照相关）。",
                "生物学判读：细胞类型分群、ASPs、co-occupancy、重复元件状态。",
                "报告中标注：计算通过 ≠ 湿实验验证；所有 pending-confirmation 参数在正式使用前需对照原文确认。",
            ],
            "expected_observation": "QC 全达标且生物学结果与对照一致。",
            "checkpoint": "QC 指标逐项过线；对照行为正常。",
            "pause_point": "任一 QC 失败则回到对应步骤排查。",
            "human_review_required": [],
            "troubleshooting": [],
            "notes": ["来源: Li et al. 2024 (摘要)"],
        },
    ]

    materials = [
        {"item": "一抗（组蛋白修饰/TF，ENCODE 验证，如 H3K4me3/H3K27ac/H3K27me3/CTCF/RAD21）", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "步骤 3。供应商/货号/稀释度依 Li et al. 2024 原文确认 (CRITICAL, pending-confirmation)。"},
        {"item": "no-antibody / isotype 对照抗体", "vendor": "", "catalog_number": "", "amount": "与实验组等量", "required": "yes", "notes": "步骤 3/13。对照设计 pending-confirmation。"},
        {"item": "Tn5-protein A/G fusion 转座酶", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "步骤 4 (CRITICAL, pending-confirmation)。CUT&Tag 原始方法: Kaya-Okur 2019；官方湿实验协议参考: Nat Protocols 2020 (doi:10.1038/s41596-020-0373-x)。"},
        {"item": "固定/透化/封闭试剂（甲醛、digitonin/Triton、BSA/血清）", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "步骤 2。组成 pending-confirmation。"},
        {"item": "SPRI 磁珠 (Ampure 或同等)", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "步骤 5。珠比 pending-confirmation。"},
        {"item": "Nanopore 接头 + 单细胞 barcode 寡核苷酸 (内/外双端)", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "yes", "notes": "步骤 6。barcode 白名单: 项目 barcode_inner.fa / barcode_outer.fa (GitHub README)。设计 pending-confirmation (CRITICAL)。"},
        {"item": "Nanopore 测序试剂 + flow cell (R10.4.1 或同级)", "vendor": "Oxford Nanopore Technologies", "catalog_number": "", "amount": "按 ONT 手册", "required": "yes", "notes": "步骤 8。"},
        {"item": "40 um 滤网（核路线）", "vendor": "", "catalog_number": "", "amount": "1 个/样品", "required": "no", "notes": "步骤 1（核路线）。"},
        {"item": "DAPI（核染色/计数）", "vendor": "", "catalog_number": "", "amount": CONFIRM, "required": "no", "notes": "步骤 1。"},
        {"item": "生信软件栈: nanoplexer v0.1, NanoFilt v2.8.0, cutadapt v3.5, minimap2 v2.26-r1175, samtools v1.3, bedtools v2.30.0, SEACR v1.3, deepTools v3.5.1, whatshap v1.6, blast v2.5.0, GenMap v1.3.0, ArchR v1.0.1", "vendor": "", "catalog_number": "", "amount": "conda/源码安装", "required": "yes", "notes": "步骤 9-12。版本来源: GitHub README（本会话获取原文）。"},
    ]

    return {
        "protocol_title": "scNanoSeq-CUT&Tag Protocol — 单核长读长 CUT&Tag（Oxford Nanopore 平台）",
        "protocol_version": "v1",
        "assay_type": "单细胞长读长 CUT&Tag 测序（组蛋白修饰/转录因子占据，Oxford Nanopore 平台）",
        "intended_user": "需要在单细胞分辨率下检测组蛋白修饰/TF 占据、等位基因特异性修饰、重复元件拷贝级表观状态的基因组学实验室（具备 Nanopore 测序条件）",
        "confidence": "中：方法框架、分析管线参数与对照设计逻辑均有本次会话核实文献支持（Li et al. 2024 摘要 + GitHub README 原文 + Kaya-Okur 2019 CUT&Tag 原始方法 + Kaya-Okur 2020 Nat Protocols 官方协议参考；Skene & Henikoff 2017 仅作相关 CUT&RUN 背景）；但 Li et al. 2024 全文 Methods 本次会话不可获取（订阅墙、无 OA、无预印本），全部湿实验关键参数（每孔细胞数、抗体稀释度、Tn5 用量/时间、SPRI 比例、barcode 设计、测序深度）标记 [confirm with source protocol]，执行前必须对照原文确认。",
        "timestamp": ts,
        "objective": "在单个细胞/核水平对基因组范围组蛋白修饰与 TF 占据进行 profiling，利用 Nanopore 长读长实现等位基因特异性、co-occupancy 与重复元件分析（Li et al. 2024 摘要目标）。",
        "summary": "Bench-ready 方案骨架 + 生信管线：A 样本制备（1 步）→ B 单细胞 CUT&Tag（固定透化/抗体/Tn5 tagmentation/SPRI，4 步）→ C 长读长文库与单细胞 barcode（2 步）→ D Nanopore 测序（1 步）→ E 生信（demux/ArchR 聚类/SEACR peak calling/下游模块，4 步）→ F 对照与判读（no-antibody 阴性对照，2 步）。生信参数逐字取自项目 GitHub README（nanoplexer/NanoFilt/cutadapt/minimap2/SEACR non stringent 0.05 + ≥1.5% 细胞且 ≥5 cells peak 支持、ArchR minTSS=1 活性/0.1 抑制、whatshap v1.6 ASPs）。相关方法对比：dscNanoSeq（Lu et al. 2026, Cell Discovery, PMC 全文）为 droplet-based 长读长单细胞表观基因组，含详细湿实验参数（100,000-200,000 细胞装载、MobiCube 芯片、Tn5 adapter barcode、PromethION 48 R10.4.1），仅作为量级参考，不得替代 scNanoSeq-CUT&Tag 原文参数。",
        "preconditions": {
            "sample_requirements": [
                "目标细胞/组织：健康对数期细胞或新鲜解离核（每孔装载数 pending-confirmation）",
                "组蛋白修饰/TF 一抗：ENCODE 验证级；H3K4me3/H3K27ac/H3K36me3/CTCF/RAD21/H3K27me3/H3K9me3 为 Li et al. 2024 摘要与 GitHub README 聚类参数段列出的标记，'已验证' 状态待原文确认",
                "Nanopore 测序能力：flow cell 与测序运行计划",
            ],
            "reagent_requirements": [
                "Tn5-protein A/G fusion（用量 pending-confirmation）",
                "固定/透化/封闭体系（pending-confirmation）",
                "SPRI 磁珠（pending-confirmation）",
                "Nanopore 接头 + 单细胞内/外 barcode（pending-confirmation）",
                "生信软件栈（版本见 materials）",
            ],
            "equipment_requirements": [
                "96/384 孔板或微孔系统（单细胞格式，Kaya-Okur 2019 风格；具体孔板 pending-confirmation）",
                "台式离心机",
                "4°C 旋转孵育（过夜抗体）",
                "37°C 孵育（tagmentation）",
                "Oxford Nanopore 测序仪（PromethION/MinION）",
                "生信计算资源（HPC 集群，bash/R 脚本）",
            ],
            "safety_notes": [
                "BSL-1 细胞/组织操作",
                "甲醛：通风橱内操作，按实验室危化品政策处理",
                "Nanopore 测序仪：按 ONT 手册操作，避免 flow cell 损伤",
            ],
            "lab_specific_fields_to_confirm": [
                "每孔装载细胞/核数（pending-confirmation；相关方法量级：dscNanoCUT 100,000-200,000 细胞总量、nano-CT 25,000-200,000 细胞——均非 scNanoSeq-CUT&Tag 参数）",
                "一抗供应商/货号/稀释度（CRITICAL, pending-confirmation）",
                "固定剂浓度/时间、透化剂种类/浓度/时间（pending-confirmation）",
                "Tn5-protein A/G 用量与 tagmentation 时间（CRITICAL, pending-confirmation）",
                "SPRI 珠:DNA 比例与洗脱体积（pending-confirmation）",
                "barcode 设计（内/外 barcode 序列与分配方案）（CRITICAL, pending-confirmation）",
                "测序平台/flow cell 与每细胞目标深度（pending-confirmation）",
                "对照设计细节（no-Tn5 孔/isotype 孔/spike-in）（pending-confirmation）",
            ],
        },
        "materials": materials,
        "workflow": workflow,
        "qc_checkpoints": [
            {"checkpoint_name": "样本制备 QC", "when": "步骤 1 结束", "measurements": ["细胞/核活率", "悬液均匀性", "DAPI 阳性比例"], "pass_criteria": ["活率可接受（阈值 pending-confirmation）", "无大团块"], "fail_signals": ["碎片多", "死细胞多"], "recommended_action_on_fail": "优化裂解/过滤；重做制备。"},
            {"checkpoint_name": "CUT&Tag 反应 QC", "when": "步骤 2-4", "measurements": ["核完整性（镜检）", "各孔体积/时间一致性", "对照同步"], "pass_criteria": ["核完整", "同步"], "fail_signals": ["裂解", "不同步"], "recommended_action_on_fail": "优化透化/Tn5；重做反应。"},
            {"checkpoint_name": "文库 QC", "when": "步骤 7", "measurements": ["浓度", "片段长度分布", ">1 kb 长片段比例"], "pass_criteria": ["分布合理（阈值 pending-confirmation）"], "fail_signals": ["短片段过多", "浓度过低"], "recommended_action_on_fail": "回步骤 4/5 调整 Tn5/SPRI。"},
            {"checkpoint_name": "Demux QC", "when": "步骤 9", "measurements": ["有效 barcode reads 比例", "比对率"], "pass_criteria": ["有效率达标（阈值 pending-confirmation）"], "fail_signals": ["交叉污染高", "比对率低"], "recommended_action_on_fail": "核对 barcode 体系/白名单。"},
            {"checkpoint_name": "Peak calling QC", "when": "步骤 11", "measurements": ["peak 支持细胞数", "TSS enrichment"], "pass_criteria": ["≥max(1.5% 总细胞数, 5) cells 支持", "活性标记 TSS 富集"], "fail_signals": ["peak 过少", "TSS 低"], "recommended_action_on_fail": "回查 demux/质量。"},
            {"checkpoint_name": "对照判读", "when": "步骤 13", "measurements": ["no-antibody 背景水平", "实验组/对照 overlap"], "pass_criteria": ["对照无特异富集", "实验组显著高于对照"], "fail_signals": ["对照背景高"], "recommended_action_on_fail": "优化固定/透化/Tn5；结果暂不可信。"},
        ],
        "decision_points": [
            {"decision": "细胞路线 vs 核路线", "when": "开始前", "options": ["完整活细胞 CUT&Tag（Kaya-Okur 2019 支持）", "分离核 CUT&Tag（组织/难透化细胞更常用）"]},
            {"decision": "抗体选择", "when": "步骤 3 前", "options": ["H3K4me3/H3K27ac/H3K36me3（活性）", "CTCF/RAD21（结构蛋白）", "H3K27me3/H3K9me3（抑制性）", "多抗体孔板并行（多标记）"]},
            {"decision": "测序深度", "when": "步骤 8 前", "options": ["按 Li et al. 2024 原文目标深度（pending-confirmation）", "按相关方法量级参考（dscNanoCUT ~0.01 Gb/cell, Lu et al. 2026 — 非本源参数）"]},
            {"decision": "下游模块选择", "when": "步骤 12", "options": ["质量评估（04）", "ASPs 等位基因特异性（05）", "co-occupancy（06）", "重复元件（07）", "全部（完整分析）"]},
        ],
        "failure_branches": [
            {"condition": "CUT&Tag 信号极低/背景高", "step_ids_affected": ["step_02", "step_03", "step_04"], "likely_causes": ["透化不当", "抗体稀释度不当", "Tn5 用量不当", "固定不当"], "recommended_modifications": ["滴定透化/抗体/Tn5", "核对固定条件"], "whether_to_repeat_or_stop": "滴定后重复步骤 2-5；连续失败则换抗体/换样本。"},
            {"condition": "文库短片段过多", "step_ids_affected": ["step_04", "step_05", "step_06"], "likely_causes": ["tagmentation 过切", "SPRI 偏向短片段"], "recommended_modifications": ["降低 Tn5/缩短时间", "调整 SPRI 比例"], "whether_to_repeat_or_stop": "调整后重复步骤 4-7。"},
            {"condition": "Demux 有效率低/交叉污染", "step_ids_affected": ["step_06", "step_09"], "likely_causes": ["barcode 体系缺陷", "操作交叉污染"], "recommended_modifications": ["核对 barcode 白名单与孔位", "分区操作"], "whether_to_repeat_or_stop": "核对后重复文库构建；barcode 体系缺陷则停止并重新设计。"},
            {"condition": "no-antibody 对照背景高", "step_ids_affected": ["step_13"], "likely_causes": ["Tn5 非特异切割", "透化/固定不当"], "recommended_modifications": ["优化步骤 2-4", "核对 Tn5 用量"], "whether_to_repeat_or_stop": "优化后重复；仍高则批次结果不可信，停止判读。"},
        ],
        "open_questions_for_human": [
            "CRITICAL：一抗供应商/货号/稀释度、Tn5-protein A/G 用量与 tagmentation 时间、barcode 设计——均须对照 Li et al. 2024 原文 Methods 确认（本文本次会话不可获取全文，订阅墙/无 OA/无预印本；pending-confirmation）。",
            "每孔装载细胞/核数（Li et al. 2024 原文待确认）。",
            "固定/透化/封闭体系细节（pending-confirmation）。",
            "SPRI 珠比与洗脱体积（pending-confirmation）。",
            "测序平台/flow cell 与每细胞目标深度（pending-confirmation）。",
            "对照设计完整清单（no-Tn5 孔、isotype 孔、spike-in 是否使用）（pending-confirmation）。",
            "注意：dscNanoSeq（Lu et al. 2026, Cell Discovery 12, doi:10.1038/s41421-026-00928-y）的详细湿实验参数（100,000-200,000 细胞、MobiCube droplet 芯片、Tn5 adapter barcode、PromethION 48 R10.4.1、cutadapt v3.3 -q 7 -e 0.25 -m 100、minimap2 -ax map-ont）属相关方法，不得直接当作 scNanoSeq-CUT&Tag 参数使用。",
        ],
        "revision_log": [
            {"version": "v1", "reason": "首次从本次会话经 Crossref/PubMed/PMC/GitHub 核实的文献推导的 bench-ready protocol 骨架；Li et al. 2024 全文不可获取，湿实验参数全部保留 [confirm with source protocol]；生信参数逐字取自 GitHub README；dscNanoSeq 参数仅作相关方法对比。", "changed_step_ids": []},
        ],
        "artifact_outputs": [],
    }


def _comparison_section() -> str:
    return (
        "\n## 相关方法对比（仅作量级参考，参数归属原方法，非 scNanoSeq-CUT&Tag 参数）\n"
        "- dscNanoSeq (Lu J et al. 2026, Cell Discovery 12, doi:10.1038/s41421-026-00928-y, PMC 全文已核实)：\n"
        "  - droplet-based（MobiCube/MobiDrop 微流控芯片），100,000-200,000 细胞/核装载\n"
        "  - dscNanoCUT：0.2% 甲醛固定 5 min；一抗 1:100 4°C ~8 h（anti-H3K27ac ab4729 / anti-H3K27me3 CST 9733S）；"
        "二级抗 1:50 30 min；pG-Tn5 (Vazyme S602) 1:100 4°C 1 h；tagmentation 37°C 1 h\n"
        "  - barcode：Tn5 adapter 双端 10 bp cell barcode + 10 bp UMI；UV 断开 bead 连接\n"
        "  - 测序：Takara GXL PCR 加 24 bp Nanopore barcode；PromethION 48, R10.4.1, 1 ug/文库\n"
        "  - 生信：nanoplexer v0.1、cutadapt v3.3 (-q 7 -e 0.25 -m 100)、minimap2 v2.18-r1015 (-ax map-ont)、"
        "samtools (-ShuF 2308 -q 30, sclen/hclen<150 过滤)、umi_tools 双端 barcode、ArchR v1.0.1→v1.0.2、"
        "MACS2 via ArchR (cutoff 0.05, reproducibility 2, -nomodel --local 500000)、whatshap v1.3、GenMap v1.3.0\n"
        "  - 通量：~0.01 Gb/cell，平均 3346 unique fragments/cell；FRiP 高于 scNanoSeq-CUT&Tag（原文比较）\n"
        "- nano-CT (Bartosovic & Castelo-Branco 2022, Nat Biotechnol 41:794-805, doi:10.1038/s41587-022-01535-4)："
        "nanobody-Tn5 融合蛋白，25,000-200,000 细胞，最多 3 模态同时检测。\n"
        "- 单细胞 CUT&Tag 基础 (Kaya-Okur et al. 2019, Nat Commun, doi:10.1038/s41467-019-09982-5)：96/384 孔微孔格式、小样本与单细胞、极低通量即可。\n"
    )


def main() -> None:
    proto = build_protocol()
    normalize_protocol(proto)

    review_agent = ReviewAgent()
    review = review_agent.run(
        "将 scNanoSeq-CUT&Tag 单核长读长 CUT&Tag 方案转换为台边执行模式",
        {"protocol": proto, "user_instruction": "整理一份scNanoSeq-CUT&Tag的protocol"},
    )
    print("review decision:", review.get("decision"))
    print("review findings:", review.get("findings"))
    print("review strengths:", review.get("strengths"))

    refs = (
        "\n## 参考来源 (本会话经 Crossref/PubMed/PMC/GitHub 核实)\n"
        + "\n".join(f"- {s}" for s in SOURCES)
        + "\n"
        + "- GitHub: Guo-Yuqing/scNanoSeq-CUT-Tag (分析管线 README，本会话获取原文；含生信版本与参数)"
        + _comparison_section()
    )

    full_md = protocol_to_markdown(proto) + "\n" + refs
    bench_md = bench_to_markdown(proto) + "\n" + refs

    run_dir = new_run_dir()
    save_json(run_dir, "input.json", {
        "file": "scNanoSeq-CUT&Tag protocol (this-session grounded)",
        "sources": SOURCES,
        "status": "draft v1",
        "note": "Li et al. 2024 full text paywalled; wet-lab parameters pending-confirmation; analysis params verbatim from GitHub README",
    })
    print("saved", save_json(run_dir, "protocol_v1.json", proto))
    print("saved", save_text(run_dir, "protocol_v1.md", full_md))
    print("saved", save_text(run_dir, "protocol_bench_v1.md", bench_md))
    print("saved", save_json(run_dir, "review_v1.json", review))
    print("RUN_DIR:", run_dir)


if __name__ == "__main__":
    main()
