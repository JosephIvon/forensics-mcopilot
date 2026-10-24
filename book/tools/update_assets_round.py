#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_assets_round.py —— ASSETS.md 本轮更新（2026-10-22，作者三项授权的执行留痕）。

改动点：
1. 本书自有工件表补「前言.md / 尾声.md」两行（书级前后记首次入证据层）；
2. 裁剪件行数按实测更新（卷一 111/81、册一 120/106、册二 65/58），并注明卷一裁剪件
   本轮重建（编者按语沿用、各章简历句与讲师段从当前章节重抽）；
3. 工具行改为当前工具链，并写明审计器**按锚点 commit 读源文件**、覆盖 24 个文件；
4. 锚点变更登记新增一条：axiscope 在锚点后有提交（KB0 +7/-3、7 篇 wiki），
   书内规模数一律按锚点口径，审计器改按锚点读；并补三个新根目录
   （mcopilot-pending / self-improving / mcopilot-external）。
"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\ASSETS.md"
t = io.open(P, encoding="utf-8").read()

JOBS = [
    # ① 前言/尾声入证据层
    ("""| `chapters-vol2b/ch01`-`ch04`（卷二册二《代码工厂与真值链卷》= trae_factory：代码工厂/真值链/**手册进知识库**/双仓收尾实录） | 册二各章 |""",
     """| `chapters-vol2b/ch01`-`ch04`（卷二册二《代码工厂与真值链卷》= trae_factory：代码工厂/真值链/**手册进知识库**/双仓收尾实录） | 册二各章 |
| `前言.md`（书级前言：三册分工 / 五条硬纪律 / 怎么验这本书 / 不承诺什么 / 三种读法） | 书级 |
| `尾声.md`（书级尾声：三场战役的收尾 / 诚实账三张表 / 三条最贵的教训 / 欠账挂账） | 书级 |"""),
    # ② 卷一裁剪件
    ("""| `crops/简历版.md`、`crops/讲师版.md`（M6 双裁剪：九句九切分原样抽取，编者加注显式标注） | 输出件 |""",
     """| `crops/简历版.md`（111 行）、`crops/讲师版.md`（81 行）（M6 双裁剪：九句九切分原样抽取，编者加注显式标注；2026-10-22 因卷一正文坐标机判化而重建——编者按语沿用旧件，各章简历句与讲师段从当前章节重抽） | 输出件 |"""),
    # ③ 册一裁剪件行数
    ("""| `crops-vol2a/简历版.md`（118 行）、`crops-vol2a/讲师版.md`（105 行）（册一双裁剪：9 章简历句与切分原样裁剪） | 输出件 |""",
     """| `crops-vol2a/简历版.md`（120 行）、`crops-vol2a/讲师版.md`（106 行）（册一双裁剪：9 章简历句与切分原样裁剪；2026-10-22 随 C6 补写 §6.6 重建） | 输出件 |"""),
    # ④ 册一坐标审计数
    ("""坐标审计 321 引用 0 失败） | 册一各章 |""",
     """坐标审计 0 失败） | 册一各章 |"""),
    # ⑤ 工具链
    ("""| `tools/audit_vol2_coords.py`（坐标审计器：201→321 引用 0 失败；支持 C1–C7 与 KB0–KB8 别名、区间行号、跨仓消歧）、`tools/crop_vol2.py`（两册裁剪生成器）、`tools/verify_crops_verbatim.py`（裁剪件逐行"原样"核验）、`tools/check_vol2s_structure.py`（两册结构体检） | 卷二生产工具链 |""",
     """| `tools/audit_vol2_coords.py`（坐标审计器：**按锚点 commit 读源文件**而非工作树；覆盖 24 个文件（卷一 9 + 册一 9 + 册二 4 + 前言 + 尾声）697 引用 0 失败；支持 C1–C7 与 KB0–KB8 别名、区间行号、跨仓消歧、尾路径匹配）、`tools/crop_vol1.py`（卷一裁剪重建）、`tools/crop_vol2.py`（两册裁剪生成器）、`tools/verify_crops_verbatim.py`（**6 件**裁剪件逐行"原样"核验）、`tools/check_vol2s_structure.py`（两册 + 前后记结构体检）、`tools/precompute_frontback_facts.py`（规模数亲跑，**axiscope 段按锚点读**） | 全书生产工具链 |"""),
    # ⑥ 锚点变更登记新增
    ("""### 外部参照与缓写卷""",
     """- [2026-10-22 本轮·作者三项授权] **axiscope 锚点后的变更与审计口径**：
  锚点 `b95ffb2` 之后仓内又有提交（HEAD `a57e67b`）：`docs/kb/KB0-conventions.md` +7/-3、
  新增 `docs/wiki/` 7 篇（合计 518 行）。**书内规模数一律按锚点口径**
  （KB 8 件 = 8141 物理行、docs md 实存 20 件 = 主体 19 + 收尾文档 1，wiki 0 件）；
  工作树读数为 KB 8145 / docs 27，**不是书的数**。审计器同步改为**按锚点 commit 读源文件**
  （`git show <rev>:<path>`），否则"行还在"会判 [OK] 却指的是另一行，0 失败成假话。
  审计根目录新增 `mcopilot-pending-20261022`（MANIFEST）、`%USERPROFILE%\\self-improving`
  （memory.md / ledger.md）、`mcopilot-external`（厂商原件 `LTDMC.cs`）——
  三处原为"仓外原件指针"，现已全部可解析。
  本轮坐标机判化后**全书裸行号清零**（清点正则由 "`:\\d+`" 改为 "`:\\d+(?:-\\d+)?`"，
  前者漏掉区间写法）。
- [2026-10-22 本轮] 书级前后记（`前言.md` / `尾声.md`）首次落盘，并纳入坐标审计与结构体检。

### 外部参照与缓写卷"""),
]

fail = 0
for old, new in JOBS:
    n = t.count(old)
    if n != 1:
        print(f"[SKIP 命中 {n} 次] {old[:60]!r}")
        fail += 1
        continue
    t = t.replace(old, new)
    print(f"[OK] {old[:48]!r}")
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
