#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_absolute_paths.py —— 「绝对路径/用户名泄露」精确定位（批 C 起的仓内纪律）。

口径
----
默认扫**工作树**（第一次提交前仓库里几乎全是未跟踪件，只扫 tracked 会扫出 0 处而显得干净）；
`--tracked` 退回"只扫已跟踪文件"的旧口径。

四类命中
--------
  1. 家目录/用户名（``C:\\Users\\xxx``）——**必改**：公开仓里等于把使用者的家目录结构贴出去；
  2. 本机工作区绝对路径（``%WORKSPACE%\\...``）——**必改**：泄露本机布局与仓间相对位置；
  3. 工具链路径（``C:\\Program Files`` / ``C:\\Windows`` / ``<工具链>``）——**保留**：
     那是通用安装位置（读者机器上也叫这个名字），换成占位反而让指令跑不了；
  4. 其他绝对路径——**逐条定性**（厂商 SDK 路径等，可能是必须的）。

为什么这道门禁在本仓
--------------------
本仓要把真值基座、代码与电子书**一起公开**，而书与文档里有大量"我本机上的路径"。
公开前必须先把第 1、2 类清干净——**用占位符说明，不要删**，删了读者看不出那是路径。

用法
----
    python book/tools/scan_absolute_paths.py              REM 扫工作树（默认）
    python book/tools/scan_absolute_paths.py --tracked    REM 只扫已跟踪文件
    python book/tools/scan_absolute_paths.py --all        REM 连同级独立仓一起扫
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from collections import defaultdict
# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(BOOK)
WS = os.path.dirname(REPO_ROOT)

PATS = [
    ("家目录/用户名", re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"'<>|]+")),
    ("本机工作区", re.compile(r"[A-Za-z]:\\workspace\\[^\\\s\"'<>|,;)]+")),
    ("工具链路径", re.compile(r"(?:C:\\Program Files[^\\\s\"'<>|]*|C:\\Windows[^\\\s\"'<>|]*|"
                             r"<工具链>[^\\\s\"'<>|]*)")),
    ("其他绝对路径", re.compile(r"(?<![A-Za-z]:\\)([A-Za-z]:\\[^\\\s\"'<>|,;)]{4,})")),
]
BINARY_EXT = {".pdf", ".exe", ".dll", ".zip", ".png", ".jpg", ".csv", ".tsv", ".dat", ".bin"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "out", "out_v_unique"}


def git(repo: str, *a: str) -> str:
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def repo_roots(include_siblings: bool) -> list[tuple[str, str]]:
    roots = [("mcopilot", REPO_ROOT)]
    if include_siblings:
        for name in ("axiscope", "trae_factory"):
            p = os.path.join(WS, name)
            if os.path.isdir(p):
                roots.append((name, p))
    return roots


def files_of(repo: str, tracked: bool) -> list[str]:
    out: list[str] = []
    if tracked:
        out = [f for f in git(repo, "ls-files", "-z").split("\0") if f]
    else:
        for dp, dns, fns in os.walk(repo):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                out.append(os.path.relpath(os.path.join(dp, fn), repo).replace("\\", "/"))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="绝对路径/用户名泄露扫描")
    ap.add_argument("--tracked", action="store_true", help="只扫已跟踪文件（旧口径）")
    ap.add_argument("--all", action="store_true", help="连同级的独立仓一起扫")
    args = ap.parse_args()

    summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    detail: dict[tuple[str, str], list[tuple[str, int, str, str]]] = defaultdict(list)

    for name, repo in repo_roots(args.all):
        for rel in files_of(repo, args.tracked):
            if os.path.splitext(rel)[1].lower() in BINARY_EXT:
                continue          # 二进制件里的"路径"是乱码误报，不算泄露
            p = os.path.join(repo, rel.replace("/", os.sep))
            if not os.path.isfile(p):
                continue
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                for label, pat in PATS:
                    for m in pat.finditer(line):
                        hit = m.group(0)
                        if label == "其他绝对路径" and (
                                "\\Users\\" in hit or "\\workspace\\" in hit
                                or hit.startswith(("C:\\Program Files", "C:\\Windows", "<工具链>"))):
                            continue
                        summary[name][label] += 1
                        detail[(name, label)].append((rel, i, hit, line.strip()[:150]))

    for name, _ in repo_roots(args.all):
        print("=" * 96)
        print(f"【{name}】")
        print("=" * 96)
        for label, _pat in PATS:
            print(f"  {label}: {summary[name][label]} 处")
        for (n, label), items in detail.items():
            if n != name:
                continue
            print(f"  ---- {label} ----")
            agg: dict[tuple[str, str], list[int]] = defaultdict(list)
            for rel, i, hit, _line in items:
                agg[(rel, hit)].append(i)
            for (rel, hit), lines in sorted(agg.items()):
                print(f"    {rel}  {hit}")
                print(f"        行 {sorted(set(lines))[:6]}{'…' if len(set(lines)) > 6 else ''}")
        print()

    must_fix = sum(summary[n]["家目录/用户名"] + summary[n]["本机工作区"] for n, _ in repo_roots(args.all))
    tot = sum(sum(v.values()) for v in summary.values())
    print(f"合计 {tot} 处；**必改（家目录/用户名 + 本机工作区）{must_fix} 处**")
    print("→ 必改项清零才算公开就绪。第 3 类（工具链路径）保留：那是通用安装位置。")
    sys.exit(1 if must_fix else 0)


if __name__ == "__main__":
    main()
