#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_doc_head_consistency.py —— 三仓"文档说的 vs HEAD 有的"一致性实查（2026-10-23）。

背景：mcopilot 的 lessons 记了一条真教训——"文档里写的文件路径，必须拿 git ls-files 核一遍"；
     已实测确认 mcopilot 无 .github/、无 scripts/run_gates.py、无 knowledge/shared_eval.json，
     而文档与 coverage_ledger 声称它们在。本脚本把这件事扩到三个仓。

口径：**以 HEAD 为准**（git ls-files），不看工作树——工作树里有而 HEAD 没有的，
      同样是"文档/账本说的东西读者拿不到"。
"""
import io
import os
import re
import subprocess
from _localenv import expand

REPOS = [
    ("mcopilot", expand(r"%WORKSPACE%\mcopilot")),
    ("axiscope", expand(r"%WORKSPACE%\axiscope")),
    ("trae_factory", expand(r"%WORKSPACE%\trae_factory")),
]
TOP = r"(?:docs|scripts|src|knowledge|data|bench|gen|tests|out|samples|examples|synth|tools|\.github|src/mcopilot|src/axiscope)"
# 后缀必须**长的在前**：否则 "json" 会被 "js" 先吃掉（正则 alternation 顺序陷阱，2026-10-23 当场修）
EXT = r"(?:jsonl|json|yaml|yml|html|toml|ipynb|md|csv|py|ps1|js|ts|exe|dll|txt|ini)"
PATH = re.compile(r"`?(" + TOP + r"/[A-Za-z0-9_\-./]+\." + EXT + r")`?")
WINDOWS = re.compile(r"[A-Za-z]:\\[^`\"'\s]+")


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


for name, repo in REPOS:
    print("=" * 92)
    print(f"【{name}】{repo}")
    print("=" * 92)
    tracked = set(git(repo, "ls-files").splitlines())
    md_files = sorted(f for f in tracked if f.lower().endswith((".md", ".json")) and not f.startswith("out/"))
    missing, total = {}, 0
    for rel in md_files:
        p = os.path.join(repo, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in PATH.finditer(txt):
            total += 1
            ref = m.group(1).replace("\\", "/")
            if ref in tracked:
                continue
            # 允许：目录、glob、模板占位
            if any(ch in ref for ch in "*?{") or ref.endswith("/"):
                continue
            missing.setdefault(ref, []).append(rel)
    print(f"  扫描 {len(md_files)} 份 tracked 文档，路径型引用 {total} 处")
    print(f"  **HEAD 里不存在的被引路径：{len(missing)} 个**")
    for ref, srcs in sorted(missing.items())[:25]:
        uniq = sorted(set(srcs))
        print(f"     ✗ {ref}   ← {len(uniq)} 处（{', '.join(uniq[:3])}{'…' if len(uniq) > 3 else ''}）")
    # CI 目录
    has_ci = any(f.startswith(".github/") for f in tracked)
    print(f"  CI 配置（.github/ 在 HEAD）：{'有' if has_ci else '**无**'}")
    print()
