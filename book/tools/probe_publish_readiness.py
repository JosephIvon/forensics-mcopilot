#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_publish_readiness.py —— 三仓"能不能公开"实查（2026-10-23）。

只做只读扫描，不改任何东西。查五类：
  ① 秘密（token / 密码 / 私钥 / 连接串）
  ② 绝对路径与用户名泄露
  ③ 第三方材料的可再分发风险（厂商原件、审计件里的外部原文、许可声明）
  ④ 大文件 / 二进制
  ⑤ 仓内是否有 .gitignore / LICENSE
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
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "out", "out_v_unique",
             "real_corpora", "vendor_docs"}
SECRET = [
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}"), "疑似密钥"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥头"),
    (re.compile(r"(?i)(postgres|mysql|mongodb|redis)://[^\s'\"]+:[^\s'\"]+@"), "带口令连接串"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk- 形态令牌"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub 令牌形态"),
]
ABSPATH = [
    (re.compile(r"[A-Za-z]:\\\\?Users\\\\?[^\\\\\"'\s]+"), "用户目录"),
    (re.compile(r"[A-Za-z]:\\\\?workspace\\\\?[^\\\\\"'\s]+"), "工作区路径"),
]
LICENCE_HINT = re.compile(r"(?i)CC[ -]BY|Apache|MIT License|GPL|copyright \(c\)|版权所有|署名")

for name, repo in REPOS:
    print("=" * 90)
    print(f"【{name}】{repo}")
    print("=" * 90)
    files, secrets, abss, lics = [], [], [], []
    for dp, dns, fns in os.walk(repo):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, repo)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            files.append((rel, sz))
            if sz > 2 * 1024 * 1024:
                print(f"  [大文件] {rel}  {sz/1024/1024:.1f} MB")
            if fn.endswith((".exe", ".dll", ".so", ".pyd", ".bin", ".zip", ".7z")):
                print(f"  [二进制入库] {rel}  {sz/1024:.0f} KB")
            if not fn.lower().endswith((".md", ".txt", ".py", ".ps1", ".js", ".json", ".yml",
                                       ".yaml", ".csv", ".jsonl", ".ts", ".sh", ".toml", ".ini")):
                continue
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for pat, lbl in SECRET:
                if pat.search(txt):
                    secrets.append(f"{lbl}@{rel}")
            for pat, lbl in ABSPATH:
                for m in pat.finditer(txt):
                    abss.append(f"{lbl}@{rel}")
                    break
            if LICENCE_HINT.search(txt):
                lics.append(rel)
    print(f"  文件总数 {len(files)}｜疑似秘密 {len(set(secrets))}｜绝对路径命中 {len(abss)}｜含许可/署名字样文件 {len(lics)}")
    for s in sorted(set(secrets))[:8]:
        print(f"    ⚠ {s}")
    for a in sorted(set(abss))[:10]:
        print(f"    · {a}")
    for l in sorted(set(lics))[:8]:
        print(f"    © {l}")
    gi = os.path.join(repo, ".gitignore")
    print(f"  .gitignore: {'有' if os.path.isfile(gi) else '无'}")
    tracked = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.splitlines()
    print(f"  git 跟踪文件 {len(tracked)}")
    big = [(t, os.path.getsize(os.path.join(repo, t))) for t in tracked
           if os.path.isfile(os.path.join(repo, t)) and os.path.getsize(os.path.join(repo, t)) > 500 * 1024]
    for t, s in sorted(big, key=lambda x: -x[1])[:6]:
        print(f"    跟踪大文件 {t} {s/1024:.0f} KB")
    print()
