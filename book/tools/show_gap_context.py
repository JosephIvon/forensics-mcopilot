#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""show_gap_context.py —— 把 41 处真断链的上下文原样打出来，供逐条定性（2026-10-22）。"""
import io
import os
import subprocess
import sys

sys.path.insert(0, r"%WORKSPACE%\forensics-learning-book\tools")
import importlib.util
spec = importlib.util.spec_from_file_location("chk", r"%WORKSPACE%\forensics-learning-book\tools\check_doc_refs_heads.py")

# 复用检查器的归一化逻辑（直接重跑一遍收集）
import re
from collections import defaultdict

REPOS = {
    "mcopilot": r"%WORKSPACE%\mcopilot",
    "axiscope": r"%WORKSPACE%\axiscope",
    "trae_factory": r"%WORKSPACE%\trae_factory",
}
TOP = (r"(?:docs|scripts|src|knowledge|data|bench|gen|tests|out|samples|examples|synth|"
       r"tools|\.github|out_v_unique)")
EXT = r"(?:jsonl|json|yaml|yml|html|toml|ipynb|md|csv|py|ps1|js|ts|exe|dll|txt|ini|log|md)"
PATH = re.compile(r"((?<![\w/])" + TOP + r"/[A-Za-z0-9_\-./{}*]*\." + EXT + r"(?::[\d,\-]+)?)")
LINESUF = re.compile(r":[\d,\-]+$")
COUNTER = re.compile(r"不存在|一个都|从未|未进|缺失|不在仓|没有.*(?:进|在)仓|已被清|清理")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def expand_braces(p):
    m = re.search(r"\{([^{}]*)\}", p)
    if not m:
        return [p]
    out = []
    for o in m.group(1).split(","):
        out += expand_braces(p[:m.start()] + o.strip() + p[m.end():])
    return out


def norm(raw):
    out = []
    for one in expand_braces(raw):
        one = LINESUF.sub("", one).strip().replace("\\", "/")
        if not one or "*" in one or "<" in one or ">" in one or one.endswith("/"):
            continue
        out.append(one)
    return out


HEADS = {n: set(git(r, "ls-files").splitlines()) for n, r in REPOS.items()}
WT = {}
for n, r in REPOS.items():
    s = set()
    for dp, dns, fns in os.walk(r):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__", "node_modules", ".venv")]
        for fn in fns:
            s.add(os.path.relpath(os.path.join(dp, fn), r).replace("\\", "/"))
    WT[n] = s

groups = defaultdict(list)
for name, repo in REPOS.items():
    for rel in sorted(f for f in HEADS[name] if f.lower().endswith((".md", ".json")) and not f.startswith("out/")):
        p = os.path.join(repo, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        for i, line in enumerate(lines, 1):
            if COUNTER.search(line):
                continue
            for m in PATH.finditer(line):
                for ref in norm(m.group(1)):
                    if ref in HEADS[name] or ref in WT[name]:
                        continue
                    if any(ref in HEADS[o] for o in REPOS):
                        continue
                    groups[(name, rel)].append((i, ref, line))

for (name, rel), items in groups.items():
    print("=" * 92)
    print(f"【{name}】{rel}   （{len(items)} 处）")
    print("=" * 92)
    p = os.path.join(REPOS[name], rel.replace("/", os.sep))
    lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
    shown = set()
    for i, ref, line in items:
        if i in shown:
            continue
        shown.add(i)
        print(f"  L{i}  缺: {ref}")
        print(f"        {line.strip()[:150]}")
    print()
