#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""append_ledger_entries.py —— 台账追加本轮三条（2026-10-22）。

纪律：台账只追加、不改他人条目（memory.md 章程条目 3）。
"""
import io
import sys

P = r"%USERPROFILE%\self-improving\ledger.md"
ENTRIES = [
    "- [2026-10-22] 条目12 命中 **锚点漂移**：axiscope 在书中锚点 `b95ffb2` 之后有提交"
    "（KB0 +7/-3、新增 docs/wiki 7 篇）。书里 20 处 KB0 坐标在锚点处是对的，但审计器读**工作树**"
    "——同样判 [OK] 却指的是另一行，\"0 失败\"成假话。修法：审计器改为**按锚点 commit 读源文件**"
    "（`git show <rev>:<path>`），并新增三个根目录（mcopilot-pending / self-improving / "
    "mcopilot-external）。规模数一律按锚点口径：KB 8 件 = 8141 物理行（原写 8142，是加总笔误）、"
    "docs md 锚点处实存 20 件（原写 27 是 HEAD 的数）。",
    "- [2026-10-22] 条目19 命中 **清点正则的盲区**：裸行号清点正则写成 \"`:\\d+`\"（数字后须紧跟反引号），"
    "**匹配不到区间写法** \"`:25-26`\" —— 清点脚本与修补脚本同时漏网，7 处区间式幸存。"
    "改正则为 \"`:\\d+(?:-\\d+)?`\" 后实点全书 70 处（卷一 3 章从未机判化过，另有册一 2、册二 6、尾声 4），"
    "逐处**回锚点核对源文件原文**后机判化，全书裸行号清零。由此立新规：清点工具的正则本身要出阴性用例"
    "（区间、单行、别名、全路径四种写法各一例），否则\"清零\"可能只是没看见。",
    "- [2026-10-22] 条目12 命中 作者三项授权（2026-10-22）执行完毕：① 册一 ch06 增设 §6.6"
    "「现场操作步骤分级：L1→L6 与\"L1 也不执行\"」（原 §6.6–§6.8 顺移，简历句/讲师切分/习题/尾注同步）；"
    "② 旧章坐标机判化（含卷一 3 章，70 → 0）；③ 书级《前言》《尾声》落盘（均入坐标审计与结构体检）。"
    "顺带当场修掉两处真实缺陷：卷一 ch06\"诚实边界\"原指 eval_forensics.py:38-40（实为 read_jsonl，"
    "正确落点 forensics_comm.py:38-40）、册一 ch06 `scripts/dialects.py` 应为 `src/axiscope/dialects.py`；"
    "并补齐裁剪核验覆盖（卷一 2 件从未进核验 → 补 crop_vol1.py 重建，核验扩到 6 件 0 不一致）。",
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
