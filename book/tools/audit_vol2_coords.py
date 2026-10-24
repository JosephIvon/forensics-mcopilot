#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_vol2_coords.py —— 卷二坐标审计：把章节里每个「文件:行号」引用解析回源文件，
打印被引行的真实内容，供人工核对"挂的那一行是不是真说了那句话"。

判据：
  - 引用可解析（文件找到 + 行号存在）→ 打 [OK]，附被引行原文（截断）
  - 文件找不到 → [MISSING-FILE]
  - 行号超出文件行数 → [MISSING-LINE]（行锚腐烂/指向未来行）
  - 同一文件不同章节引用行号不一致 → 汇总提示

**按锚点读源文件（2026-10-22 补）**：源仓文件的内容从**锚点 commit** 取（git show），
不在移动中的工作树取。起因：axiscope 在锚点 `b95ffb2` 之后有提交改了 KB0（+7/-3），
若读工作树，书里 20 处 KB0 坐标会指向另一行——而"行还在"仍判 [OK]，
于是"0 失败"变成假话（只验了存在，没验指对了没有）。锚点冻结 = 坐标含义冻结。
路径发现仍在工作树（找得到即认为路径有效），内容取自锚点。
"""
import os
import re
import subprocess
import sys
from collections import defaultdict

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from _localenv import expand
# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

BOOK_DIR = Path(__file__).resolve().parents[1]          # <repo>/book
WS = BOOK_DIR.parents[1]                              # <repo>/.. —— 仓外同级目录


def _first_existing(*cands):
    """按候选名取第一个存在的目录/文件；都没有就返回第一个候选（保持报错信息可读）。"""
    for c in cands:
        if c.exists():
            return str(c)
    return str(cands[0])


# 源仓根：**本仓**（forensics-mcopilot）。
#
# 为什么锚在本仓而不是旧仓 `mcopilot`：
#   旧仓是**发布前的工作副本**，公开后读者手里只有本仓——坐标锚在读者拿不到的
#   地方，等于"只对作者可核"。锚点必须落在**读者 clone 下来就有**的那个仓。
#   旧仓仍在本地时，它只作历史对照，不再作锚点。
REPO_ROOT = BOOK_DIR.parent
MCO_REPO = str(REPO_ROOT)
ROOTS = [
    _first_existing(WS / "axiscope"),
    _first_existing(WS / "trae_factory"),
    MCO_REPO,
    _first_existing(WS / "mcopilot-pending-20261022"),
    str(BOOK_DIR),
    expand(r"%USERPROFILE%\self-improving"),
    _first_existing(WS / "mcopilot-external"),
]
BOOK_REPO = str(BOOK_DIR)
BOOKS = [
    ("卷一(本仓)", str(BOOK_DIR / "chapters")),
    ("书级(前言/尾声)", [str(BOOK_DIR / "前言.md"),
                          str(BOOK_DIR / "尾声.md")]),
]

# 源仓锚点：内容从这些 commit 取（工作树移动、改名、合并都不改坐标的含义）
ANCHORS = {
    expand(r"%WORKSPACE%\axiscope"): "b95ffb2",
    expand(r"%WORKSPACE%\trae_factory"): "954c210",
    MCO_REPO: "2dfc6d2",
}

# 短名 → 相对路径候选（KB2:804 这类简写）
ALIAS = {
    "KB0": ["docs/kb/KB0-conventions.md", "docs/kb/KB0-判据库.md"],
    "KB2": ["docs/kb/KB2-waveform-formats.md"],
    "KB5": ["docs/kb/KB5-simulation-plant.md"],
    "KB7": ["docs/kb/KB7-dataset-da-rus-cat.md"],
    "kb3": ["docs/kb/kb3_判据抽取.md"],
    "KB3": ["docs/kb/KB3-tuning-rules.md"],
    "KB4": ["docs/kb/KB4-attribution-model.md"],
    "KB6": ["docs/kb/KB6-coupling-and-calibration.md"],
    "KB8": ["docs/kb/KB8-benchmark-cases.md"],
    "README": ["README.md"],
    "C1": ["docs/contracts/C1-canonical-waveform.md"],
    "C2": ["docs/contracts/C2-features.md"],
    "C3": ["docs/contracts/C3-diagnosis.md"],
    "C4": ["docs/contracts/C4-validation.md"],
    "C5": ["docs/contracts/C5-evaluation-protocol.md"],
    "C6": ["docs/contracts/C6-machine-context.md"],
    "C7": ["docs/contracts/C7-process-context.md"],
}

CITE = re.compile(
    r"(?P<file>[A-Za-z0-9_\-一-鿿\./]+\.(?:md|py|js|cs|txt|json|csv))"
    r"[:：](?P<line>\d+)(?:[-–](?P<line2>\d+))?"
)
ALIAS_CITE = re.compile(
    r"(?<![A-Za-z0-9_\-/\.])(?:KB(?P<kn>\d)|C(?P<cn>[1-7]))[:：](?P<line>\d+)"
    r"(?:[-–](?P<line2>\d+))?"
)
cache = {}
acache = {}


def anchored_read(abs_path):
    """源仓文件按锚点 commit 读内容。

    **本书仓（book/）不读锚点**：书是**正在写的活物**，锚点是**代码的快照**。
    锚点切到本仓之后，`book/` 恰好落在锚点根下面——若不排除，
    书里对 `decision-lists/*.md` 的引用会被拿**上一次提交的文字**去核，
    核的是旧行号、报的是假结果（"0 失败"反而成了假话）。
    书的内容一律读**工作树**；只有**代码**读锚点。
    """
    if os.path.abspath(abs_path).lower().startswith(os.path.abspath(BOOK_REPO).lower() + os.sep):
        return None
    for root, rev in ANCHORS.items():
        if abs_path.lower().startswith(root.lower() + os.sep):
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            key = (root, rev, rel)
            if key not in acache:
                r = subprocess.run(["git", "-C", root, "show", f"{rev}:{rel}"],
                                   capture_output=True)
                acache[key] = (r.stdout.decode("utf-8", "replace").splitlines()
                               if r.returncode == 0 else None)
            return acache[key]
    return None


def load(abs_path):
    if abs_path not in cache:
        anchored = anchored_read(abs_path)
        if anchored is not None:
            cache[abs_path] = anchored
            return anchored
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                cache[abs_path] = fh.read().splitlines()
        except Exception:
            cache[abs_path] = None
    return cache[abs_path]


def resolve(rel, hint_root=None):
    """按给定顺序找文件（先 hint_root，再各 ROOTS），返回 (abs_path, lines)。
    basename 命中多处时按 hint_root 优先，否则返回第一个并由调用方报 AMBIGUOUS。"""
    cands = []
    rel = rel.replace("/", os.sep)
    if hint_root:
        cands.append(os.path.join(hint_root, rel))
    for r in ROOTS:
        cands.append(os.path.join(r, rel))
    # 只给文件名时，全库按 basename 找
    if os.sep not in rel:
        for r in ROOTS:
            for dirpath, _dirs, files in os.walk(r):
                if ".git" in dirpath:
                    continue
                if os.path.basename(rel) in files:
                    cands.append(os.path.join(dirpath, os.path.basename(rel)))
    for c in cands:
        lines = load(c)
        if lines is not None:
            return c, lines
    # 尾路径匹配：`real_corpora/sources.md` 这类省略上级目录的写法，
    # 在各仓里按路径尾部匹配（book 里允许省略中间层，但不许省略文件名）
    if os.sep in rel:
        tail = rel.replace("\\", "/")
        for r in ROOTS:
            for dirpath, _dirs, files in os.walk(r):
                if ".git" in dirpath:
                    continue
                for f in files:
                    p = os.path.join(dirpath, f)
                    if p.replace("\\", "/").lower().endswith("/" + tail.lower()):
                        lines = load(p)
                        if lines is not None:
                            return p, lines
    return None, None


def all_matches(rel):
    """同名文件的全库落点（用于消歧提示）。"""
    out = []
    rel = rel.replace("/", os.sep)
    for r in ROOTS:
        if os.sep in rel:
            p = os.path.join(r, rel)
            if os.path.isfile(p):
                out.append(p)
        else:
            for dirpath, _dirs, files in os.walk(r):
                if ".git" in dirpath:
                    continue
                if os.path.basename(rel) in files:
                    out.append(os.path.join(dirpath, os.path.basename(rel)))
    return out


def chapter_roots(text):
    """从素材坐标块判断本章的素材仓顺序（trae/axiscope/mcopilot/书仓）。"""
    head = text[:600]
    order = []
    for key, root in (("trae_factory", ROOTS[1]), ("axiscope", ROOTS[0]),
                      ("mcopilot", ROOTS[2]), ("forensics-learning-book", BOOK_REPO)):
        if key in head:
            order.append(root)
    for r in ROOTS:
        if r not in order:
            order.append(r)
    return order


def main():
    total = ok = bad = 0
    per_file = defaultdict(list)
    for volname, BOOK in BOOKS:
      if isinstance(BOOK, list):
          files = list(BOOK)
      else:
          files = sorted(os.path.join(BOOK, f) for f in os.listdir(BOOK) if f.endswith(".md"))
      for path in files:
        fn = os.path.basename(path)
        text = open(path, encoding="utf-8").read()
        roots = chapter_roots(text)
        ch_total = ch_ok = 0
        print("=" * 90)
        print("章：", fn, "｜ 素材仓顺序：", [os.path.basename(r) for r in roots[:2]])
        print("=" * 90)
        # 章节自己的坐标行不算（尾注清单里会重复列同样的坐标）
        for m in CITE.finditer(text):
            f, ln = m.group("file"), int(m.group("line"))
            ln2 = int(m.group("line2")) if m.group("line2") else ln
            abs_p, lines = resolve(f, hint_root=roots[0])
            total += 1
            ch_total += 1
            if lines is None:
                others = all_matches(f)
                if others:
                    bad += 1
                    print(f"  [AMBIGUOUS] {f}:{ln} → 仓内同名 {len(others)} 处：{others[:3]}")
                else:
                    print(f"  [EXTERNAL-TARGET] {f}:{ln}（仓外原件指针，非断链）")
                continue
            if ln < 1 or ln > len(lines):
                bad += 1
                print(f"  [MISSING-LINE] {f}:{ln}（该文件共 {len(lines)} 行）")
                continue
            ok += 1
            ch_ok += 1
            per_file[abs_p].append((fn, ln, ln2))
            seg = lines[ln - 1].strip()
            if ln2 != ln and ln2 <= len(lines):
                seg = (seg + " … " + lines[ln2 - 1].strip()).strip()
            if len(seg) > 150:
                seg = seg[:150] + "…"
            print(f"  [OK] {f}:{ln}{'-' + str(ln2) if ln2 != ln else ''} → {seg}")
        for m in ALIAS_CITE.finditer(text):
            key = ("KB%s" % m.group("kn")) if m.group("kn") else ("C%s" % m.group("cn"))
            ln = int(m.group("line"))
            rel = None
            for cand in ALIAS.get(key, []):
                abs_p, lines = resolve(cand)
                if lines is not None:
                    rel, lines = cand, lines
                    break
            if rel is None:
                bad += 1
                print(f"  [MISSING-FILE] {key}:{ln}（别名未解析）")
                continue
            total += 1
            ln2 = int(m.group("line2")) if m.group("line2") else ln
            if ln > len(lines) or ln2 > len(lines) or ln2 < ln:
                bad += 1
                print(f"  [MISSING-LINE] {key}:{ln}{'-' + str(ln2) if ln2 != ln else ''}（该文件共 {len(lines)} 行）")
                continue
            ok += 1
            per_file[os.path.join(ROOTS[0], rel)].append((fn, ln, ln2))
            seg = " ".join(lines[i - 1].strip() for i in range(ln, min(ln2, ln + 1) + 1))
            if len(seg) > 150:
                seg = seg[:150] + "…"
            print(f"  [OK] {key}:{ln}{'-' + str(ln2) if ln2 != ln else ''} → {seg}")
    print()
    print("=" * 90)
    print(f"坐标审计合计：引用 {total} ｜ 可解析 {ok} ｜ 失败 {bad}")
    # 同一文件被多章引用不同行号 → 提示
    print("=" * 90)
    for abs_p, cites in per_file.items():
        byfile = defaultdict(set)
        for fn, a, b in cites:
            byfile[fn].add((a, b))
        if len(byfile) > 1:
            print(f"[多章引用同一文件] {abs_p}")
            for fn, ls in byfile.items():
                print(f"    {fn}: {sorted(ls)}")


if __name__ == "__main__":
    main()
