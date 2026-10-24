#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_three_repos_state.py —— 三仓发布前状态实查（2026-10-23）。

回答三个问题所需的事实：
  Q1 code wiki：三个仓现在有没有 README / docs/wiki / 架构文档，深度如何
  Q2 闭环：锚点之后有没有未收口的提交与未提交变更；测试/门禁现状
  Q3 一个仓发布：许可、署名义务、脱敏、秘密、跨仓引用
"""
import io
import os
import re
import subprocess

REPOS = [
    ("mcopilot", r"%WORKSPACE%\mcopilot", "b53ac62"),
    ("axiscope", r"%WORKSPACE%\axiscope", "b95ffb2"),
    ("trae_factory", r"%WORKSPACE%\trae_factory", "954c210"),
]


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


for name, repo, anchor in REPOS:
    print("=" * 88)
    print(f"【{name}】{repo}   书中锚点 = {anchor}")
    print("=" * 88)
    head = git(repo, "rev-parse", "--short", "HEAD")
    print(f"  HEAD = {head}")
    # 锚点之后的提交
    logs = git(repo, "log", "--oneline", f"{anchor}..HEAD").splitlines()
    print(f"  锚点后提交 {len(logs)} 个：")
    for l in logs[:8]:
        print(f"     {l}")
    # 未提交
    st = git(repo, "status", "--porcelain")
    stl = [x for x in st.splitlines() if x.strip()]
    print(f"  未提交项 {len(stl)} 个：")
    for x in stl[:10]:
        print(f"     {x}")
    # 许可 / 署名
    lic = [f for f in os.listdir(repo) if re.match(r"(?i)^(licen[sc]e|copying)", f)]
    print(f"  许可文件：{lic or '（无）'}")
    for name2 in ("README.md", "README_CN.md", "ARCHITECTURE.md", "CONTRIBUTING.md"):
        p = os.path.join(repo, name2)
        if os.path.isfile(p):
            n = len(io.open(p, encoding="utf-8", errors="replace").read().splitlines())
            print(f"  {name2}: {n} 行")
    # wiki / docs
    for sub in ("docs/wiki", "wiki", "docs"):
        p = os.path.join(repo, sub)
        if os.path.isdir(p):
            mds = sorted(f for f in os.listdir(p) if f.endswith(".md"))
            print(f"  {sub}/: {len(mds)} 篇 md {mds[:8]}")
    print()
