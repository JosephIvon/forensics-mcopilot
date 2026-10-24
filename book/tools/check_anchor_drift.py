#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_anchor_drift.py —— 查书中坐标在"锚点"与"当前 HEAD"之间是否漂移（2026-10-22）。

起因：axiscope 在书中锚点 `7b0fd88` 之后有提交 `a57e67b`（KB0 +7/-3、新增 7 篇 wiki）。
若书里的坐标在锚点处指的不是同一句话，锚点就是假的（看着对、其实对不齐）。
本脚本：把书里全部 `KB0:行号` / `KB0-conventions.md:行号` 引用，在锚点与 HEAD 两处各取该行，
逐条比对文本是否相同；其余 KB / 契约 / src 文件同样比对（确认零漂移）。
"""
import io
import os
import re
import subprocess
import sys
from _localenv import expand

BOOK = expand(r"%WORKSPACE%\forensics-learning-book")
AXI = expand(r"%WORKSPACE%\axiscope")
ANCHOR = "7b0fd88"
HEAD = "a57e67b"

CITE = re.compile(
    r"(?P<file>(?:docs/kb/KB\d[\w\-]*\.md|KB\d-\w[\w\-]*\.md|docs/contracts/C\d[\w\-]*\.md|"
    r"[A-Za-z0-9_\-/\.]+\.(?:py|md|json|jsonl|sha256|js|cs|csv|txt|ps1)))[:：](?P<a>\d+)(?:[-–](?P<b>\d+))?"
)
ALIAS = re.compile(r"(?<![A-Za-z0-9_\-/\.])(?:KB(?P<kn>\d))[:：](?P<line>\d+)(?:[-–](?P<line2>\d+))?")

KB_FILES = {
    "KB0": "docs/kb/KB0-conventions.md",
    "KB2": "docs/kb/KB2-waveform-formats.md",
    "KB3": "docs/kb/KB3-tuning-rules.md",
    "KB4": "docs/kb/KB4-attribution-model.md",
    "KB5": "docs/kb/KB5-simulation-plant.md",
    "KB6": "docs/kb/KB6-coupling-and-calibration.md",
    "KB7": "docs/kb/KB7-dataset-da-rus-cat.md",
    "KB8": "docs/kb/KB8-benchmark-cases.md",
}


def at(rev, path):
    r = subprocess.run(["git", "-C", AXI, "show", f"{rev}:{path}"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").splitlines()


def worktree(path):
    fp = os.path.join(AXI, path.replace("/", os.sep))
    if not os.path.isfile(fp):
        return None
    return io.open(fp, encoding="utf-8", errors="replace").read().splitlines()


# 1) 收集书里所有 KB0 坐标
refs = []
for d in ("chapters",):
    for fn in sorted(os.listdir(os.path.join(BOOK, d))):
        if not fn.endswith(".md"):
            continue
        text = io.open(os.path.join(BOOK, d, fn), encoding="utf-8").read()
        for m in ALIAS.finditer(text):
            if m.group("kn") == "0":
                refs.append((d + "/" + fn, int(m.group("line")),
                             int(m.group("line2") or m.group("line"))))
        for m in CITE.finditer(text):
            if m.group("file").startswith(("docs/kb/KB0", "KB0-")):
                refs.append((d + "/" + fn, int(m.group("a")),
                             int(m.group("b") or m.group("a"))))

print(f"[1] 书里 KB0 坐标共 {len(refs)} 处，逐处比对锚点 {ANCHOR} 与 HEAD {HEAD}：")
drift = 0
for src, a, b in sorted(set(refs)):
    la = at(ANCHOR, KB_FILES["KB0"])
    lh = worktree(KB_FILES["KB0"])
    ta = " ".join(x.strip() for x in la[a - 1:b])[:70] if la and len(la) >= b else "<越界>"
    th = " ".join(x.strip() for x in lh[a - 1:b])[:70] if lh and len(lh) >= b else "<越界>"
    same = ta == th
    if not same:
        drift += 1
    print(f"  {'同' if same else '★漂移'} {src}:{a}-{b}")
    if not same:
        print(f"      锚点：{ta}")
        print(f"      HEAD：{th}")

# 2) 其余被引文件在锚点与 HEAD 之间是否变化
print("\n[2] 其余被引工件在锚点与 HEAD 之间的变化（git diff --numstat）：")
r = subprocess.run(["git", "-C", AXI, "diff", "--numstat", f"{ANCHOR}..{HEAD}"],
                   capture_output=True, text=True)
for l in r.stdout.strip().splitlines():
    print(f"  {l}")

# 3) 锚点与 HEAD 的 KB 总行数（口径：物理行）
for rev, getter in ((ANCHOR, at), (HEAD, at)):
    tot = 0
    for name, path in KB_FILES.items():
        lines = getter(rev, path)
        tot += len(lines) if lines else 0
    print(f"\n[3] KB 8 件物理行合计 @{rev} = {tot}")
tot = sum(len(worktree(p)) for p in KB_FILES.values())
print(f"[3] KB 8 件物理行合计 @工作树 = {tot}")
print(f"\n结论：KB0 坐标漂移 {drift} 处")
sys.exit(1 if drift else 0)
