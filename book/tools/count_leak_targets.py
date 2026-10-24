#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""count_leak_targets.py —— 统计待脱敏/待参数化目标串的逐文件命中次数（2026-10-22，批 C 用）。"""
import io
import os
import subprocess

REPOS = {
    "mcopilot": r"%WORKSPACE%\mcopilot",
    "axiscope": r"%WORKSPACE%\axiscope",
    "trae_factory": r"%WORKSPACE%\trae_factory",
}
TARGETS = [
    r"%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
    sys.executable,
    r"%WORKSPACE%\trae_factory",
    r"%USERPROFILE%\Documents\Qoder\2026-10-19\4dc146eb",
    r"%USERPROFILE%\.qoder-cn\memory\feedback-verify-subagent-completion-claims.md",
    r"%USERPROFILE%\.minimax\sessions\mvs_838bec01bb00476594f48711e6b172d0\workspace\mcopilot",
    r"%USERPROFILE%\Documents\Trae-CN\temp_20261019_01",
    r"D:\迅雷下载",
    r"<厂区>\Projekte",
    r"%WORKSPACE%\mcopilot",
    r"%WORKSPACE%\axiscope",
]
BINARY = {".pdf", ".exe", ".dll", ".zip", ".png", ".jpg", ".csv", ".tsv"}

for name, repo in REPOS.items():
    files = [f for f in subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True,
                                       text=True, encoding="utf-8", errors="replace"
                                       ).stdout.splitlines() if f]
    print("=" * 92)
    print(f"【{name}】")
    print("=" * 92)
    for t in TARGETS:
        hits = []
        for rel in files:
            if os.path.splitext(rel)[1].lower() in BINARY:
                continue
            p = os.path.join(repo, rel.replace("/", os.sep))
            if not os.path.isfile(p):
                continue
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            n = txt.count(t)
            if n:
                hits.append((rel, n))
        if hits:
            total = sum(n for _, n in hits)
            print(f"  {t}   —— 合计 {total} 处 / {len(hits)} 文件")
            for rel, n in hits[:14]:
                print(f"      {rel}  ×{n}")
            if len(hits) > 14:
                print(f"      …另有 {len(hits)-14} 个文件")
    print()
