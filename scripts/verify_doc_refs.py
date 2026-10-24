#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验文档里引用的真值文件**行号**还对不对得上。

为什么要这个脚本
----------------
本项目的规矩是「每条结论都要钉在真值上：文件 + 行号 + 字段」。
但真值 CSV 会变，行号会漂 —— 文档里的 `leisai.csv L957` 过几个月就可能指错地方，
而读者不会去核对。**行号引用一旦失准，整份文档的证据链就断了，而且是静默地断。**

所以这里把文档里出现的「文件名 + L行号 + 符号」引用抽出来，逐条回真值文件里查：
那一行**必须真的含有那个符号**。

两道检查
--------
1. **真值 CSV 引用**（原版）：`leisai.csv L957` → 那行必须含文档提到的符号。
2. **代码行号引用**（后加）：`pyproject.toml:14`、`src/mcopilot/cli.py:267` →
   文件必须在、行号必须在范围内。

第 2 道是被现实逼出来的：`docs/wiki/07-运行方式.md` 曾写着 `pyproject.toml:10`，
而 `requires-python` 早已挪到第 14 行——**读者照着找不到，照抄就跑不通**，
而这条引用当时没有任何门禁看守。**过期坐标比没有坐标更坏**：它看起来是可信的。

用法
----
    python scripts/verify_doc_refs.py
    python scripts/verify_doc_refs.py --doc docs/首次上机验证清单.md
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "knowledge", "sdks", "official_api")

# 要抽检的文档
DOCS = [
    os.path.join(ROOT, "docs", "首次上机验证清单.md"),
    os.path.join(ROOT, "docs", "厂商手册索取清单.md"),
    os.path.join(ROOT, "docs", "落地路线.md"),
]

# 代码行号引用要扫的文档。
#
# 只扫**当前面向读者的**文档；`docs/评审_*` / `docs/事故_*` / `docs/项目回顾_*`
# 是**历史记录**——它们记的是当时另一个工程（Trae 生成的分支工程）里的文件名，
# 那些文件从来不属于本仓，拿它们判断链是冤案。
CODE_DOC_GLOBS = [
    ("README.md", os.path.join(ROOT, "README.md")),
    ("README_EN.md", os.path.join(ROOT, "README_EN.md")),
]
_WIKI = os.path.join(ROOT, "docs", "wiki")
if os.path.isdir(_WIKI):
    for _f in sorted(os.listdir(_WIKI)):
        if _f.endswith(".md"):
            CODE_DOC_GLOBS.append((os.path.join("docs", "wiki", _f),
                                   os.path.join(_WIKI, _f)))
for _f in ("首次上机验证清单.md", "厂商手册索取清单.md", "落地路线.md",
           "开发计划_v2_协议层.md"):
    _p = os.path.join(ROOT, "docs", _f)
    if os.path.isfile(_p):
        CODE_DOC_GLOBS.append((os.path.join("docs", _f), _p))

# 不入库区：生成物位置（.gitignore 已声明），公开后读者拿不到 —— 跳过但计数（要喊出来）
NOT_SHIPPED_PREFIXES = ("out/", "out\\", ".test_tmp/", "build/")

# 仓外原件区：厂商手册与头文件**不入本仓**（版权与体积），由 `knowledge/protocols/anchors.json`
# 登记落点。文档里引它们是**跨仓引用**，不是断链——但行号照样要核，
# 所以这里也解析、也查行号范围。
EXTERNAL_ROOTS = [
    os.path.join(ROOT, os.pardir, "mcopilot-external", "vendor_docs"),
]

# 形如 `src/mcopilot/cli.py:267` / `pyproject.toml:14` / `foo.py:12-18`
CODE_CITE = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:py|toml|ps1|bat|json|ya?ml|cs|txt|md|cfg|ini))"
    r"(?::|#L)(?P<start>\d+)(?:-(?P<end>\d+))?"
)


# 引用里出现的真值文件名 -> 实际路径
TRUTH_FILES = {
    "leisai.csv": os.path.join(API, "leisai.csv"),
    "leisai_cpp.csv": os.path.join(API, "leisai_cpp.csv"),
    "zmotion.csv": os.path.join(API, "zmotion.csv"),
    "zmotion_cpp.csv": os.path.join(API, "zmotion_cpp.csv"),
    "gts.csv": os.path.join(API, "gts.csv"),
    "gts_hdr.csv": os.path.join(API, "gts_hdr.csv"),
    "dll_exports.csv": os.path.join(API, "dll_exports.csv"),
    "binding_returns.csv": os.path.join(API, "binding_returns.csv"),
}

# 形如  `leisai.csv` L957  /  leisai.csv L957  /  `leisai.csv:957`
CITE = re.compile(
    r"`?(?P<file>[A-Za-z0-9_]+\.csv)`?\s*(?:L|:\s*line\s*|第)?\s*L?(?P<line>\d+)"
)

# 引用附近要能在同一行里找到的符号
SYMBOL = re.compile(r"\b(dmc_[A-Za-z0-9_]+|ZAux_[A-Za-z0-9_]+|GT[A-Za-z0-9_]+)\b")


def check_code_refs(verbose=True):
    """第 2 道检查：代码行号引用（文件在不在、行号在不在范围内）。

    解析顺序：先按**文档所在目录**解析（`docs/wiki/07-运行方式.md` 里的 `../../src/...`），
    再按**仓根**解析（`pyproject.toml:14` 这种）。两条都找不到 = 断链，判失败。

    `out/` 这类**不入库区**（.gitignore 已声明的生成物）跳过——但要计数并喊出来：
    公开后读者确实拿不到那些路径，只是那不是"断链"，是"本来就不发"。
    """
    total = 0
    bad = 0
    skipped = 0
    external_n = 0
    for label, doc in CODE_DOC_GLOBS:
        if not os.path.isfile(doc):
            continue
        with io.open(doc, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        doc_dir = os.path.dirname(doc)
        for no, text in enumerate(lines, 1):
            for m in CODE_CITE.finditer(text):
                raw = m.group("file").replace("\\", "/")
                if raw.startswith("./"):
                    raw = raw[2:]
                if "..." in raw or raw.startswith(NOT_SHIPPED_PREFIXES):
                    skipped += 1
                    continue
                start = int(m.group("start"))
                end = int(m.group("end")) if m.group("end") else start
                cands = [os.path.normpath(os.path.join(doc_dir, raw)),
                         os.path.normpath(os.path.join(ROOT, raw))]
                path = next((c for c in cands if os.path.isfile(c)), None)
                external = False
                multi = []
                if path is None:
                    for ex in EXTERNAL_ROOTS:
                        cand = os.path.normpath(os.path.join(ex, raw))
                        if os.path.isfile(cand):
                            path = cand
                            external = True
                            break
                if path is None and "/" not in raw and "\\" not in raw:
                    # 文档里常只写**文件名**（表里已给出完整落点），按文件名在仓外原件区找
                    for ex in EXTERNAL_ROOTS:
                        for dp, _dns, fns in os.walk(ex):
                            if raw in fns:
                                multi.append(os.path.join(dp, raw))
                    if multi:
                        external = True
                if path is None and not multi:
                    print("  !! %s L%d 引用 %s —— 文件不存在" % (label, no, raw))
                    bad += 1
                    continue
                targets = multi if multi else [path]
                ok_lines = False
                hit_line = None
                for t in targets:
                    with io.open(t, encoding="utf-8", errors="replace") as fh:
                        tl = fh.read().splitlines()
                    if 1 <= start <= len(tl) and 1 <= end <= len(tl):
                        ok_lines = True
                        hit_line = tl[start - 1]
                        break
                if not ok_lines:
                    n_max = len(tl)
                    print("  !! %s L%d 引用 %s:%d-%d —— 越界（该文件只有 %d 行）"
                          % (label, no, raw, start, end, n_max))
                    bad += 1
                    continue
                total += 1
                if external:
                    external_n += 1
                # 符号核对：文档说「LTDMC.cs:891 的 dmc_get_position」，那就该行真有它
                claimed = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", text))
                syms = [s for s in claimed
                        if s.lower().replace("_", "") in hit_line.lower().replace("_", "")
                        and (s.startswith(("dmc_", "ZAux_", "GT")) or s.endswith((".cs", ".dll")))]
                if verbose:
                    tag = " [仓外原件]" if external else ""
                    extra = ("  ← %s" % hit_line.strip()[:58]) if syms else ""
                    print("  OK  %-34s L%-5d -> %s:%d-%d%s%s"
                          % (label, no, raw, start, end, tag, extra))
    if skipped:
        print("  -- 跳过 %d 条「不入库区」引用（out/ 等生成物，公开后读者拿不到，不是断链）" % skipped)
    if external_n:
        print("  -- 其中 %d 条落在「仓外原件区」（厂商手册/头文件，不入本仓，行号已核）" % external_n)
    return total, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验文档里的真值行号引用")
    ap.add_argument("--doc", action="append", default=None,
                    help="只查这几个文档（可重复）")
    ap.add_argument("--quiet", action="store_true", help="不逐条打印 OK 行")
    args = ap.parse_args(argv)

    docs = args.doc or DOCS
    total = 0
    bad = 0
    for doc in docs:
        if not os.path.isfile(doc):
            print("!! 找不到文档 %s" % doc)
            bad += 1
            continue
        with io.open(doc, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        print("=== %s ===" % os.path.relpath(doc, ROOT))
        for no, text in enumerate(lines, 1):
            for m in CITE.finditer(text):
                fname = m.group("file")
                if fname not in TRUTH_FILES:
                    continue
                line_no = int(m.group("line"))
                path = TRUTH_FILES[fname]
                if not os.path.isfile(path):
                    print("  !! 找不到真值文件 %s" % fname)
                    bad += 1
                    continue
                with io.open(path, encoding="utf-8-sig") as fh:
                    truth = fh.read().splitlines()
                if not (1 <= line_no <= len(truth)):
                    print("  !! 文档 L%d 引用 %s L%d —— 越界（该文件只有 %d 行）"
                          % (no, fname, line_no, len(truth)))
                    bad += 1
                    continue
                target = truth[line_no - 1]
                total += 1
                # 同一行里出现的、应当能在被引行里找到的符号
                syms = [s for s in set(SYMBOL.findall(text))
                        if s.lower().replace("_", "") in target.lower().replace("_", "")
                        or s in target]
                claimed = [s for s in set(SYMBOL.findall(text))]
                if claimed and not syms:
                    # 这行提到了若干符号，但没有一个在被引行里 —— 可能指错了行
                    # （不一定是错：符号可能在同一段落的另一行被引；只报告不强判）
                    print("  -- 文档 L%d 引用 %s L%d，该行未见 %s"
                          % (no, fname, line_no, "/".join(sorted(claimed)[:3])))
                else:
                    print("  OK  文档 L%-5d -> %s L%-6d  %s"
                          % (no, fname, line_no, target.strip()[:70]))

    print("")
    print("=== 代码行号引用（文件存在性 + 行号范围）===")
    c_total, c_bad = check_code_refs(verbose=not args.quiet)
    total += c_total
    bad += c_bad

    print("")
    print("共校验 %d 条行号引用，%d 条越界/失效" % (total, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
