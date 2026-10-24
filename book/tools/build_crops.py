#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_crops.py —— 裁剪件生成器（**一件**，合并版）。

2026-10-24：本书随 mcopilot 仓开源后，裁剪件由两件（简历版 / 讲师版）合成**一件**。
理由不是省事，是**对象变了**：

  · 简历版服务的是「**一个人的求职**」——它带着「按岗位挑 2-3 句」「对外投递时怎么举证」
    这类个人用法，还带着个人履历的口气；
  · 开源之后面对的是「**一类开发者**」——这类读者要的是「一句带锚点、可当场复核的主张」
    和「这一章怎么讲」，不需要「怎么把这句话塞进简历」。

所以：**求职的挑法删掉，主张与切分都留着，一件就够。**
判据写在文件里，不靠读者自己体会。

本脚本是裁剪件的**唯一生成器**：
  · 各章「可验证主张」与「讲师 90 分钟」两段从当前 `chapters/` **原样裁出**，一字不改；
  · 编者按语（怎么用 / 授课顺序与依赖 / 组合方案）在本文件里，是编者的，
    **不从旧件沿用**——旧件里有求职口径，按新对象重写。

仓根从 `__file__` 反推（本文件在 `<book>/tools/`），不写死绝对路径。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

BOOK = Path(__file__).resolve().parents[1]
SRC = BOOK / "chapters"
OUT = BOOK / "crops"
CROP_NAME = "裁剪版.md"

CHAPTERS = [
    ("ch01", "ch01-驾驭层.md", "驾驭层"),
    ("ch02", "ch02-三态真值.md", "三态真值"),
    ("ch03", "ch03-门禁与负向测试.md", "门禁与负向测试"),
    ("ch04", "ch04-契约先行.md", "契约先行"),
    ("ch05", "ch05-故障农场与真实语料.md", "故障农场与真实语料"),
    ("ch06", "ch06-诊断与归因.md", "诊断与归因"),
    ("ch07", "ch07-多智能体协作制度.md", "多智能体协作制度"),
    ("ch08", "ch08-记忆与沉淀系统.md", "记忆与沉淀系统"),
    ("ch09", "ch09-经济账与收尾.md", "经济账与收尾"),
]


# ---------------------------------------------------------------- 抽取

def extract_claim(text: str) -> list[str]:
    """取「可验证主张」块：所有 '> **可验证主张**' 块中**字符数最长**者
    （章头的指针行是短块）；若该章以「可验证主张」小节给出且标题不是
    '**可验证主张**'，回退取小节内的引文块。"""
    lines = text.splitlines()
    blocks, cur = [], []
    for ln in lines:
        if ln.startswith("> **可验证主张**"):
            if cur:
                blocks.append(cur)
            cur = [ln]
            continue
        if cur:
            if ln.startswith(">"):
                cur.append(ln)
            else:
                blocks.append(cur)
                cur = []
    if cur:
        blocks.append(cur)
    if blocks:
        best = max(blocks, key=lambda b: sum(len(x) for x in b))
        if sum(len(x) for x in best) >= 120 and "见 §" not in best[0]:
            return best
    for i, ln in enumerate(lines):
        if re.match(r"^#+\s.*可验证主张", ln):
            quote = []
            j = i + 1
            while j < len(lines) and not (lines[j].startswith("#") or lines[j].strip() == "---"):
                if lines[j].startswith(">"):
                    quote.append(lines[j])
                j += 1
            if quote:
                return quote
    return blocks[0] if blocks else []


def extract_teacher(text: str) -> list[str]:
    """取讲师切分段：'**讲师 90 分钟**' 行优先；否则取 '讲师切分' 小节/标签及其后的表格。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("**讲师 90 分钟**"):
            out = [ln]
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].startswith("**") \
                    and not lines[j].startswith("#"):
                out.append(lines[j])
                j += 1
            return out
    for i, ln in enumerate(lines):
        if re.match(r"^#+\s.*讲师", ln):
            lvl = len(ln) - len(ln.lstrip("#"))
            out = [ln]
            j = i + 1
            while j < len(lines):
                x = lines[j]
                if (x.startswith("#") and (len(x) - len(x.lstrip("#"))) <= lvl) or x.strip() == "---":
                    break
                out.append(x)
                j += 1
            out = _strip_claim(out)
            if len(out) >= 2:
                return out
    for i, ln in enumerate(lines):
        if "讲师切分" in ln and not ln.startswith("> ") and not ln.startswith("#"):
            out = [ln]
            j = i + 1
            while j < len(lines):
                x = lines[j]
                if x.startswith("#") or x.strip() == "---":
                    break
                out.append(x)
                j += 1
            if len(out) >= 2:
                return out
    return []


def _strip_claim(lines: list[str]) -> list[str]:
    """从切分块里剔掉主张引文与其小标题（切分件只留切分，不重复主张）。"""
    out = []
    for ln in lines:
        if not ln.startswith("> ") and not ("可验证主张" in ln and ln.startswith("#")):
            out.append(ln)
    return out


# ---------------------------------------------------------------- 编者按语

HEAD = """\
# 裁剪版：九章的可验证主张与 90 分钟课切分（M6 裁剪件）

> **来源**：各章 §末「可验证主张」与「讲师 90 分钟」两段**原样裁剪，一字未改**
> （2026-10-24 合并定版；正文改动后请重跑 `tools/build_crops.py`）。
> **规格**（`OUTLINE.md` §3）：每章两件——一句可验证主张（带锚点）+ 90 分钟课的切分点。
> 大纲模板预算为 概念 20' / 动手 40' / 习题复盘 30'（上限骨架）；各章实切见下，
> 动手预算不得被讲解侵占——每章都有现场跑真命令的环节。

## 为什么只有一版

早先这里按用途分成两件：**简历版**（服务一个人的求职）与**讲师版**（服务授课）。
本书开源后面对的是**一类开发者**，不是一个人的求职——所以合成一件：

- **留下的**：一句带锚点、当场可复核的主张；这一章怎么讲。
- **删掉的**：「按岗位挑 2-3 句」「对外投递时怎么举证」这类个人求职用法。

分开两件对开源读者没有意义：他们要的是方法与证据，不是简历模板。
"""

RULES = """\
## 怎么用（先读这条再用）

1. **可验的含义**：锚点 = 仓库@commit + 路径，对有仓库访问权的人当场可验
   （`git clone` 后开文件即对上数字）。
2. **数字全部有坐标**：主张句里没有任何形容词撑场的数字——每个都挂在
   `forensics-mcopilot@2dfc6d2` 或工件路径上，追问到底就是本书对应章节。
3. ch08/ch09 的 `self-improving/` 锚点为本机活文件（挂节锚）；复核场合以
   本书 `decision-lists/mcopilot-b53ac62.md` 与第 8/9 章正文为 durable 证物。
4. **主张与切分是两件事**：主张说明"这一章主张了什么、能验到哪"，切分说明
   "90 分钟怎么排"。按需取用，不必两样都读。
"""

DEPS = """\
## 授课顺序与依赖（编者加注）

- **先讲 ch03**：门禁是全书基础设施，ch05/ch06 的 G11/G12、ch01 的"总门禁
  动手"都以它为前提。
- **ch02 → ch05**：三态真值（Tier A/B 分工）是农场与语料章的概念底。
- **ch04 → ch05/ch06**：comm_log/1 契约是农场日志与检出引擎的共同裁判。
"""

COMBOS = """\
## 组合方案（编者加注）

| 方案 | 组成 | 适合 |
|---|---|---|
| 单章课 ×9 | 任一章 90' | 企业内训切片 |
| 检出线全天（6h） | ch03 → ch04 → ch05 → ch06 | 工程/质量团队 |
| 沉淀线半天（4.5h） | ch01 → ch07 → ch08 → ch09 | 平台/交付团队 |
| 两日全课（9h+机动） | 九章全排 + 60' 结算工作坊（用 ch09 动手收全课） | 完整方法论培训 |
"""


# ---------------------------------------------------------------- 生成

def build() -> str:
    parts = [HEAD, RULES, DEPS, COMBOS, "---"]
    for idx, (k, fn, title) in enumerate(CHAPTERS, 1):
        text = (SRC / fn).read_text(encoding="utf-8")
        claim = extract_claim(text)
        teacher = extract_teacher(text)
        parts.append(f"\n## {k} {title}（第{idx}章）\n")
        parts.append("\n".join(claim) if claim else "> （本章可验证主张缺失——待补）")
        parts.append("")
        parts.append("\n".join(teacher) if teacher else "**讲师 90 分钟**：待补")
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / CROP_NAME
    body = build()
    with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    n = len(body.splitlines())
    print(f"   {target}: {n} 行")
    print("裁剪件已重建（单件合并版；各章主张与切分从当前 chapters/ 原样重抽）")


if __name__ == "__main__":
    main()
