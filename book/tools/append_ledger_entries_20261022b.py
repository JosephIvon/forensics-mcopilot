#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""append_ledger_entries_20261022b.py —— 台账追加本轮五条（2026-10-22 夜·公开前审第一批）。

纪律：台账只追加、不改他人条目（memory.md 章程条目 3）。
"""
import io
import sys

P = r"%USERPROFILE%\self-improving\ledger.md"
ENTRIES = [
    "- [2026-10-22 夜] 条目12 命中 **锚点文本不可动**：批 B 给 mcopilot 的 "
    "`knowledge/protocols/failure_signatures.json` 里 `path:…#锚点` 追加了半句说明，"
    "门禁 `test_evidence_path文件与锚点文本都在场` 当场红——证据条目的锚点是**核对目标**，"
    "不是可编辑的说明位。已回退，改为在别处说明。同时查明：书按锚点 commit 读源文件，"
    "所以**改三仓工作树不动书的任何坐标**；但若被书按行号引用的仓内文件行数漂移，"
    "坐标仍指向原意（改后必须验行数零漂移）。",
    "- [2026-10-22 夜] 命中 **正则 alternation 顺序陷阱**（新类）：清点路径的正则把后缀写成 "
    "`(py|ps1|js|json|…)`，**`js` 排在 `json` 前面** → 所有 `*.json` 被截成 `*.js`，"
    "61 处假断链；改成长后缀在前后真断链 41 处。又一处一字之差：反例计数器写的是"
    "「未**进**」，而文档里实际写的是「未入**库**」→ 计数器对 13 处真缺口失灵。"
    "新规：清点正则必须**长后缀在前**，且必须备阴性用例（区间/行号后缀/花括号/相对路径/记录字段各一例）。",
    "- [2026-10-22 夜] 命中 **「声称存在」与「记录曾经存在」必须分型**：新写的账实相符检查器"
    "首跑 41 处「断链」，其中真债只有 13 处——其余是**反例引用**（文档明说该文件已删）、"
    "**相对路径**（相对所在目录解析）、**记录性引用**（校验报告里的历史 path 字段）、"
    "**不入库区**（.gitignore 声明的 out/ 等）。新规：账实相符检查**先分型再定性**；"
    "把教材式举反例当成账实不符去改文档，等于把教材改坏——本轮差点犯。",
    "- [2026-10-22 夜] 命中 **数字三口径**（第 N 次）：`docs/CodeWiki_20261022.md` 里 8 处计数过期，"
    "根因全是口径混用——**跟踪文件数 ≠ 工作树文件数 ≠ 跑批产出数**"
    "（knowledge/ 85→75 个跟踪文件、templates 5+21→5+14、samples 24→21、"
    "`mcopilot all` 产出 36→34 个文件、pytest 385 passed→383 passed/2 failed/2 skipped）。"
    "另附一条**基线纪律**：怀疑自己改坏时，先用 `git worktree add --detach` 建 HEAD 干净检出跑同一批，"
    "再动手——本轮 3 failed 里 2 failed 是基线既有（Windows 控制台子进程 stdout 编码错位），"
    "只有 1 failed 是我改坏的。",
    "- [2026-10-22 夜] 作者三问（闭环？code-review？传 GitHub？）的结论已落成两笔提交与一份决策清单："
    "**mcopilot `5d7321a`（收尾：4 项未提交逐件定性，3 入库 1 退回）+ `353182e`（账实相符清偿）**；"
    "**不需要新一轮代码质量 review**（门禁 G1–G12 全绿 12/12、负向门禁独立、387 项测试在册），"
    "需要的是一轮**公开前审**（秘密 0 / 绝对路径 26 处 / 厂商原件与数据集定性 / LICENSE 与署名 / CI / 统一提交身份）。"
    "模板 exe 的裁决依据值得单记：同源重建**不是**代码变更——`.text` 段尺寸相同（28868），"
    "字节差异只来自 PE 时间戳与编译器每次构建随机生成的 GUID；据此退回，不入库。",
]

t = io.open(P, encoding="utf-8").read()
add = []
for e in ENTRIES:
    head = e[:46]
    if head in t:
        print(f"[SKIP 已存在] {head}")
        continue
    add.append(e)
if add:
    t = t.rstrip("\n") + "\n" + "\n".join(add) + "\n"
    io.open(P, "w", encoding="utf-8", newline="\n").write(t)
    print(f"[OK] 台账追加 {len(add)} 条")
sys.exit(0)
