#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arrange_apply.py —— 编排改造②中档的应用脚本（2026-10-22）。

对 22 章各做两件事：
  ① 章首插入**承接段**（本章承接 / 学完你会 / 前置），内容取自 arrange_content_data.BRIDGE，
     逐章手写、贴该章主张与动手节；
  ② 章首的「素材坐标 / 已验算」块**下沉**到章末新小节「## 证据与坐标」，
     章首只留「简历句 / 讲师切分」指针行。

不动：正文论证、坐标内容、习题、简历句框、讲师切分、尾注坐标清单（原文照搬）。
"""
import io
import os
import sys

sys.path.insert(0, r"%WORKSPACE%\forensics-learning-book\tools")
from arrange_content_data import BRIDGE  # noqa: E402

REPO = r"%WORKSPACE%\forensics-learning-book"


def apply_one(rel, bridge):
    path = os.path.join(REPO, rel.replace("/", os.sep))
    text = io.open(path, encoding="utf-8").read()
    lines = text.splitlines()

    # ── 找章首引用块（标题之后的第一段连续 '>' 行）────────────────────────
    i = 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or not lines[i].startswith(">"):
        print(f"[SKIP] {rel}：章首没有引用块")
        return False
    start = i
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    block = lines[start:i]

    # ── 切分三组：素材坐标组 / 已验算组 / 指针行 ────────────────────────
    groups, cur = [], []
    for l in block:
        if l.startswith("> **") and cur:
            groups.append(cur)
            cur = [l]
        else:
            cur.append(l)
    if cur:
        groups.append(cur)
    mat = [g for g in groups if "**素材坐标**" in g[0]]
    ver = [g for g in groups if "**已验算**" in g[0]]
    ptr = [g for g in groups if "**简历句**" in g[0] or "**讲师切分**" in g[0]]
    if not mat or not ver:
        print(f"[SKIP] {rel}：未识别到素材坐标/已验算组")
        return False

    # ── ① 承接段插入（标题之后、指针行之前）────────────────────────────
    bridge_lines = [f"> **本章承接**：{bridge[0]}",
                    f"> **学完你会**：{bridge[1]}",
                    f"> **前置**：{bridge[2]}"]
    new_head = lines[:start] + bridge_lines + [""] + ptr[0] if False else None
    # （保持原块顺序：先承接段，再指针行）
    head = lines[:start] + bridge_lines + [""] + [l for g in ptr for l in g]
    body = lines[i:]

    # ── ② 坐标块下沉：章末「## 证据与坐标」小节 ────────────────────────
    sep_idx = max((n for n, l in enumerate(body) if l.strip() == "---"), default=-1)
    ev = ["## 证据与坐标", ""]
    for g in mat + ver:
        ev += g
    ev += [""]
    if sep_idx >= 0:
        tail = body[:sep_idx] + ["---"] + ev + body[sep_idx:]
    else:
        tail = body + ["---", ""] + ev

    out = head + tail
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print(f"[OK] {rel}：承接段 + 坐标块下沉（{len(lines)} → {len(out)} 行）")
    return True


def main():
    ok = 0
    for rel, bridge in BRIDGE.items():
        if apply_one(rel, bridge):
            ok += 1
    print(f"\n完成 {ok}/{len(BRIDGE)} 章")
    sys.exit(0 if ok == len(BRIDGE) else 1)


if __name__ == "__main__":
    main()
