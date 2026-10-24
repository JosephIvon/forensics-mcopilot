#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""precompute_frontback_facts.py —— 前言/尾声引用的全部数字亲跑一次（2026-10-22）。

纪律：凡写进书的数字必须由本脚本打印，且**每项带口径**（物理行 / 非空行 / 件数 / 实收集数）。
口径不同的同名数字（物理行 vs 非空行）在正文里不许混用。
"""
import io
import json
import os
import subprocess
from pathlib import Path

# 2026-10-24：书随 mcopilot 仓开源，仓根从 __file__ 反推（<repo>/book/tools/ → <repo>/book）。
# 源仓仍在仓外同级目录，按名字探测；探测不到就保留原名，报告里会显示缺失。
BOOK_DIR = Path(__file__).resolve().parents[1]
WS = BOOK_DIR.parents[1]


def _first_existing(*names):
    for n in names:
        p = WS / n
        if p.exists():
            return str(p)
    return str(WS / names[0])


BOOK = str(BOOK_DIR)
AXI = _first_existing("axiscope")
TRAE = _first_existing("trae_factory")
MCO = _first_existing("mcopilot", "forensics-mcopilot")


def lines_of(path):
    return io.open(path, encoding="utf-8", errors="replace").read().splitlines()


def nonempty(lines):
    return sum(1 for l in lines if l.strip())


def group(dirs, pattern, label):
    """统计目录下匹配文件：件 / 物理行 / 非空行。"""
    files = []
    for d in dirs:
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if f.endswith(pattern):
                    files.append(os.path.join(dp, f))
    phys = sum(len(lines_of(f)) for f in files)
    ne = sum(nonempty(lines_of(f)) for f in files)
    print(f"  {label}: {len(files)} 件 ｜ 物理行 {phys} ｜ 非空行 {ne}")
    return len(files), phys, ne


AXI_REV = "7b0fd88"  # 书中锚点：规模数一律按此 commit 读，不读工作树


def ax_lines(rel):
    """axiscope 在锚点处的文件行（相对仓库根）。"""
    import subprocess
    r = subprocess.run(["git", "-C", AXI, "show", f"{AXI_REV}:{rel}"],
                       capture_output=True)
    if r.returncode:
        return None
    return r.stdout.decode("utf-8", "replace").splitlines()


def ax_files(subdir, ext):
    """axiscope 在锚点处的文件清单（相对仓库根）。"""
    import subprocess
    r = subprocess.run(["git", "-C", AXI, "-c", "core.quotepath=false", "ls-tree", "-r",
                        "--name-only", AXI_REV, subdir], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.endswith(ext)]


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root] + list(args), capture_output=True,
                           text=True, timeout=60)
        return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"<err {e}>"


print("【一】本书（book/，随 mcopilot 仓开源）")
for vol, d in (("卷一", "chapters"),):
    fs = sorted(f for f in os.listdir(os.path.join(BOOK, d)) if f.endswith(".md"))
    # 章与导读分列（2026-10-22 编排改造新增卷首导读页，口径必须分开报）
    chs = [f for f in fs if f != "00-导读.md"]
    guide = [f for f in fs if f == "00-导读.md"]
    phys = sum(len(lines_of(os.path.join(BOOK, d, f))) for f in fs)
    ne = sum(nonempty(lines_of(os.path.join(BOOK, d, f))) for f in fs)
    gtxt = "、".join(f"{f} {len(lines_of(os.path.join(BOOK, d, f)))} 行" for f in guide) or "无"
    print(f"  {vol}: {len(chs)} 章 + {len(guide)} 导读（{gtxt}） ｜ 物理行 {phys} ｜ 非空行 {ne}")
    cphys = sum(len(lines_of(os.path.join(BOOK, d, f))) for f in chs)
    print(f"    └ 仅正文 {len(chs)} 章：物理行 {cphys}")
crops = []
for d in ("crops",):
    for f in sorted(os.listdir(os.path.join(BOOK, d))):
        if f.endswith(".md"):
            crops.append((d + "/" + f, len(lines_of(os.path.join(BOOK, d, f)))))
print(f"  裁剪件: {len(crops)} 件 ｜ " + "、".join(f"{n} {k} 行" for n, k in crops))
tools = [f for f in os.listdir(os.path.join(BOOK, "tools")) if f.endswith(".py")]
print(f"  工具脚本: {len(tools)} 支 py")
dl = [f for f in os.listdir(os.path.join(BOOK, "decision-lists")) if f.endswith(".md")]
print(f"  决策清单: {len(dl)} 份 ｜ " +
      "、".join(f"{f} {len(lines_of(os.path.join(BOOK, 'decision-lists', f)))} 行" for f in dl))
print(f"  书仓 HEAD: {git(BOOK, 'rev-parse', '--short', 'HEAD')} ｜ 未提交 {len(git(BOOK, 'status', '--porcelain').splitlines())} 项")

print(f"\n【二】axiscope（书中锚点 @{AXI_REV} —— 一律按锚点读，不读工作树）")


def ax_group(subdir, ext, label):
    """按锚点统计某目录下的件数 / 物理行 / 非空行。"""
    fs = ax_files(subdir, ext)
    phys = ne = 0
    for f in fs:
        ls = ax_lines(f) or []
        phys += len(ls)
        ne += sum(1 for x in ls if x.strip())
    print(f"  {label}: {len(fs)} 件 ｜ 物理行 {phys} ｜ 非空行 {ne}")
    return fs


ax_group("docs/contracts", ".md", "契约 C1-C7")
ax_group("docs/kb", ".md", "知识库 KB0-KB8")
ax_group("src/axiscope", ".py", "src/axiscope 实现")
ax_group("tests", ".py", "tests 测试")
ax_group("synth", ".py", "synth 合成被控对象")
ax_group("bench", ".py", "bench runner 与构造")
docs_all = ax_files("docs", ".md")
_主体 = len([d for d in docs_all if "/wiki/" not in d and "收尾" not in d])
_收尾 = len([d for d in docs_all if "收尾" in d])
_wiki = len([d for d in docs_all if "/wiki/" in d])
print(f"  docs md: {len(docs_all)} 件（锚点处实存 = 主体 {_主体} + 收尾文档 {_收尾} + wiki {_wiki}）")
cases = ax_lines("bench/cases.jsonl") or []
print(f"  bench 用例: {len([c for c in cases if c.strip()])} 例")
hid = ax_lines("bench/hidden.sha256") or []
print(f"  hidden.sha256: {len([c for c in hid if c.strip() and not c.strip().startswith('#')])} 条冻结摘要"
      f"（注释行 {len([c for c in hid if c.strip().startswith('#')])} 行）")
agent_files = ax_files("src/agent", "")
print(f"  src/agent: {len(agent_files)} 个文件（锚点处）")
print(f"  axiscope HEAD: {git(AXI, 'rev-parse', '--short', 'HEAD')}")

print("\n【三】trae_factory（书中锚点 @954c210）")
group([os.path.join(TRAE, "gen")], ".js", "gen 知识库与生成器")
print(f"  ocr.ps1: {len(lines_of(os.path.join(TRAE, 'ocr.ps1')))} 行")
for d in ("out", "out_v_unique"):
    p = os.path.join(TRAE, d)
    if os.path.isdir(p):
        n = sum(len(fn) for _dp, _dn, fn in os.walk(p))
        print(f"  {d}/: {n} 件")
print(f"  trae_factory HEAD: {git(TRAE, 'rev-parse', '--short', 'HEAD')}")

print("\n【四】本仓（书中锚点 @285da78）")
print(f"  mcopilot HEAD: {git(MCO, 'rev-parse', '--short', 'HEAD')} ｜ "
      f"未提交 {len(git(MCO, 'status', '--porcelain').splitlines())} 项")
official = os.path.join(MCO, "knowledge", "sdks", "official_api")
if os.path.isdir(official):
    for f in sorted(os.listdir(official)):
        if f.endswith(".csv"):
            print(f"  official_api/{f}: {len(lines_of(os.path.join(official, f)))} 行")
