#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""machine_ize_all_bare_refs.py —— 全书裸行号机判化（终版，2026-10-22）。

清点正则修正为 "`:\\d+(?:-\\d+)?`" 后，真相是全书还剩 70 处裸行号
（卷一 ch02/ch04/ch06 从未机判化过，册一 ch06/ch09 各 1，册二 ch03 6，尾声 4）。
每处归属都已**回锚点核对过源文件原文**（不是按上下文猜）：

  卷一 ch02：:89/:90/:91 → knowledge/protocols/anchors.json（锚点原文为 snap7 源码包 /
                com0com 安装包 / extracted_text 三条锚）
              :109 → knowledge/protocols/real_corpora/sources.md（"宁缺毋滥未收"逐字在 :65）
              :123 → scripts/fault_farm.py（RST 桩主机层攻击）
              :211 → samples/servo/darus3252_prbs_pos_ppi.truth.json（同文件 :9）
  卷一 ch04：契约/校验器两件（:41-:103、:165、:173、:185 → comm_log_contract.json；
              :149、:168 → validate_comm_log.py）
  卷一 ch06：:35/:49/:52/:54 → src/mcopilot/agents/forensics_comm.py
              :75/:88/:90/:93/:96 → knowledge/protocols/failure_signatures.json
                （:100-106 = must_not_match_samples，:107-111 = honest_boundary 三条）
              :105/:107/:112 → scripts/onboard_loop.py
              :127/:135 → scripts/eval_forensics.py
              :182 → forensics_comm.py:38-40（诚实边界"不证明现场故障分布的覆盖率"，
                原文逐字核对；原先指向 eval_forensics.py 的 read_jsonl，是行锚腐烂，当场修）
  册一 ch06:58 → dialects.py；册一 ch09:34 → data/probe_doc_line_refs.py
  册二 ch03：:78/:79/:183 → gen/adapters_kb.js；:82/:113/:127/:146 → 决策清单
  尾声：:30 → decision-lists/axiscope-36e2c74.md；:39 → decision-lists/trae_factory-2da4559.md
"""
import io
import os
import re
import sys
from _localenv import expand

REPO = expand(r"%WORKSPACE%\forensics-learning-book")
BARE = re.compile(r"`:\d+(?:-\d+)?`")

A_JSON = "knowledge/protocols/anchors.json"
A_SOURCES = "knowledge/protocols/real_corpora/sources.md"
A_FARM = "scripts/fault_farm.py"
A_TRUTH = "samples/servo/darus3252_prbs_pos_ppi.truth.json"
A_CONTRACT = "knowledge/contracts/comm_log_contract.json"
A_VALID = "scripts/validate_comm_log.py"
A_ENG = "src/mcopilot/agents/forensics_comm.py"
A_SIG = "knowledge/protocols/failure_signatures.json"
A_ONBOARD = "scripts/onboard_loop.py"
A_EVAL = "scripts/eval_forensics.py"
A_DIALECT = "scripts/dialects.py"
A_PROBE = "data/probe_doc_line_refs.py"
A_ADAPT = "gen/adapters_kb.js"
A_DEC_T = "decision-lists/trae_factory-2da4559.md"
A_DEC_A = "decision-lists/axiscope-36e2c74.md"

# (文件相对路径, 行号, 该行裸行号按出现顺序, 归属)
PLAN = [
    ("chapters/ch02-三态真值.md", 89, [":57-63"], A_JSON),
    ("chapters/ch02-三态真值.md", 90, [":65-95"], A_JSON),
    ("chapters/ch02-三态真值.md", 91, [":97-122"], A_JSON),
    ("chapters/ch02-三态真值.md", 109, [":64-65"], A_SOURCES),
    ("chapters/ch02-三态真值.md", 123, [":395-404"], A_FARM),
    ("chapters/ch02-三态真值.md", 211, [":9"], A_TRUTH),
    ("chapters/ch04-契约先行.md", 41, [":2-5"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 42, [":15-90"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 43, [":92-99"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 44, [":105-109"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 48, [":31"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 49, [":36", ":71"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 51, [":8"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 52, [":101"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 53, [":102"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 54, [":103"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 57, [":128-133"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 60, [":44"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 69, [":93"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 70, [":94"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 71, [":95"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 72, [":96"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 73, [":97", ":89"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 74, [":98", ":20"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 83, [":13", ":12"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 96, [":5"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 103, [":4"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 149, [":10-11"], A_VALID),
    ("chapters/ch04-契约先行.md", 165, [":95"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 168, [":130-131"], A_VALID),
    ("chapters/ch04-契约先行.md", 170, [":5"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 173, [":103"], A_CONTRACT),
    ("chapters/ch04-契约先行.md", 185, [":5"], A_CONTRACT),
    ("chapters/ch06-诊断与归因.md", 35, [":12-13"], A_ENG),
    ("chapters/ch06-诊断与归因.md", 49, [":14-16"], A_ENG),
    ("chapters/ch06-诊断与归因.md", 52, [":63"], A_ENG),
    ("chapters/ch06-诊断与归因.md", 54, [":16-17"], A_ENG),
    ("chapters/ch06-诊断与归因.md", 75, [":11-99"], A_SIG),
    ("chapters/ch06-诊断与归因.md", 88, [":5"], A_SIG),
    ("chapters/ch06-诊断与归因.md", 90, [":6-10"], A_SIG),
    ("chapters/ch06-诊断与归因.md", 93, [":100-106"], A_SIG),
    ("chapters/ch06-诊断与归因.md", 96, [":107-111"], A_SIG),
    ("chapters/ch06-诊断与归因.md", 105, [":11-12"], A_ONBOARD),
    ("chapters/ch06-诊断与归因.md", 107, [":16-28"], A_ONBOARD),
    ("chapters/ch06-诊断与归因.md", 112, [":30-34"], A_ONBOARD),
    ("chapters/ch06-诊断与归因.md", 127, [":13-16"], A_EVAL),
    ("chapters/ch06-诊断与归因.md", 135, [":32"], A_EVAL),
    ("chapters/ch06-诊断与归因.md", 182, [":38-40"], A_ENG),
    ("chapters-vol2a/ch06-厂商方言与上下文契约.md", 58, [":35-36"], A_DIALECT),
    ("chapters-vol2a/ch09-文档即代码.md", 34, [":9-10"], A_PROBE),
    ("chapters-vol2b/ch03-手册进知识库.md", 78, [":19", ":321", ":487", ":668"], A_ADAPT),
    ("chapters-vol2b/ch03-手册进知识库.md", 79, [":802", ":857"], A_ADAPT),
    ("chapters-vol2b/ch03-手册进知识库.md", 82, [":33-34"], A_DEC_T),
    ("chapters-vol2b/ch03-手册进知识库.md", 113, [":63-65"], A_DEC_T),
    ("chapters-vol2b/ch03-手册进知识库.md", 127, [":35-36"], A_DEC_T),
    ("chapters-vol2b/ch03-手册进知识库.md", 146, [":33-34"], A_DEC_T),
    ("chapters-vol2b/ch03-手册进知识库.md", 183, [":37", ":196-199"], A_ADAPT),
    ("尾声.md", 30, [":69-71", ":72"], A_DEC_A),
    ("尾声.md", 39, [":33-34", ":63-65"], A_DEC_T),
]

fail = 0
cache = {}
for rel, lineno, refs, alias in PLAN:
    path = os.path.join(REPO, rel.replace("/", os.sep))
    if path not in cache:
        cache[path] = io.open(path, encoding="utf-8").read().splitlines(keepends=True)
    lines = cache[path]
    if lineno > len(lines):
        print(f"[SKIP] {rel}:{lineno} 行不存在")
        fail += 1
        continue
    line = lines[lineno - 1]
    found = [f.strip("`") for f in BARE.findall(line)]
    if found != refs:
        print(f"[SKIP] {rel}:{lineno} 实际裸行号 {found} ≠ 计划 {refs}")
        fail += 1
        continue
    it = iter([alias] * len(refs))

    def rep(m, _it=it):
        return f"`{next(_it)}:{m.group(0)[2:-1]}`"

    lines[lineno - 1] = BARE.sub(rep, line)

for path, lines in cache.items():
    io.open(path, "w", encoding="utf-8", newline="\n").write("".join(lines))

# 全书复探
total = 0
for d in ("chapters", "chapters-vol2a", "chapters-vol2b"):
    for fn in sorted(os.listdir(os.path.join(REPO, d))):
        if fn.endswith(".md"):
            hits = BARE.findall(io.open(os.path.join(REPO, d, fn), encoding="utf-8").read())
            total += len(hits)
            if hits:
                print(f"[残留] {d}/{fn}: {hits[:8]}")
for fn in ("前言.md", "尾声.md"):
    hits = BARE.findall(io.open(os.path.join(REPO, fn), encoding="utf-8").read())
    total += len(hits)
    if hits:
        print(f"[残留] {fn}: {hits[:8]}")
print(f"全书剩余裸行号：{total}")
print(f"计划 {len(PLAN)} 行，失败 {fail}")
sys.exit(1 if (fail or total) else 0)
