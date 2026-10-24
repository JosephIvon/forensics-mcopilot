#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_sidecar.py —— 批 C 第 8 项：侧车来源记录里的上游路径 + 示例路径一致化（2026-10-22）。

一、axiscope：脱敏漏了 `data/sidecar_in/`
2026-10-22 那次脱敏覆盖了 `data/raw/` ✓，但**侧车来源记录**（*.source.txt）里
逐字引用了上游文件自报的 `File = <厂区>\\...` ✗ → 同一处泄露在第二个地方 ✗。
处置与 `data/raw` 侧同法：整段路径换 `[REDACTED_HOST_PATH]` ✓，只留 basename ✓。

二、mcopilot：`docs/落地路线.md` 的示例路径
README 里的 `D:\\logs\\你的日志.log` 已改成相对路径 ✓，这份文档还留着旧写法 ✗——
同一套示例两处写法不一致 ✗。统一改相对 ✓。

三、mcopilot NOTICE：第三方材料表补一行
`docs/jd_证据_20261021/jds.jsonl` 是**公开招聘网站**抓下来的岗位语料 ✓，
属第三方材料，应在 NOTICE §1 逐件登记 ✓。
"""
import io
import os
import re
import sys

AX = r"%WORKSPACE%\axiscope"
MC = r"%WORKSPACE%\mcopilot"

# ── axiscope：侧车来源记录里的上游路径 → 占位 ───────────────────────────
sidecars = [
    r"data\sidecar_in\darus\DaRUS来源存证\Export10_244531.csv.source.txt",
    r"data\sidecar_in\sidecar27\DaRUS来源存证\Export10_244531.csv.source.txt",
]
pat = re.compile(r"<厂区>\\[^\s,;，。；]+")
hit = 0
for rel in sidecars:
    p = os.path.join(AX, rel)
    txt = io.open(p, encoding="utf-8", newline="").read()
    new, n = pat.subn("[REDACTED_HOST_PATH]", txt)
    if n:
        io.open(p, "w", encoding="utf-8", newline="").write(new)
        hit += n
        print(f"  ✓ {rel}：{n} 处上游路径 → [REDACTED_HOST_PATH]")
    else:
        print(f"  ✗ {rel}：未命中（先看内容再改）")
        sys.exit(1)
print(f"  axiscope 侧车：{hit} 处")

# ── mcopilot：落地路线的示例路径统一为相对 ──────────────────────────────
p = os.path.join(MC, "docs", "落地路线.md")
txt = io.open(p, encoding="utf-8", newline="").read()
before = txt.count("D:\\logs\\")
txt = txt.replace("D:\\logs\\", "logs\\")
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print(f"  ✓ docs/落地路线.md：{before} 处 D:\\logs\\ → logs\\")

# ── mcopilot NOTICE：补第三方材料一行 ──────────────────────────────────
p = os.path.join(MC, "NOTICE.md")
txt = io.open(p, encoding="utf-8", newline="").read()
anchor = "| `docs/kb/` 中登记的 ScienceDB / Zenodo 两包 |"
if anchor not in txt:
    print("  ✗ NOTICE 锚点未命中")
    sys.exit(1)
row = ("| `docs/jd_证据_20261021/jds.jsonl` | **公开招聘网站**（BOSS 直聘等）抓取的岗位语料 | 平台公开页面内容 | "
       "本仓只做**统计与标注**（职责块 / 智能体覆盖率），不重发布个人简历；抓取时间与来源 URL 逐条留痕 ✓ |")
txt = txt.replace(anchor, row + "\n" + anchor, 1)
io.open(p, "w", encoding="utf-8", newline="").write(txt)
print("  ✓ NOTICE.md：第三方材料表补「公开招聘信息语料」一行")
