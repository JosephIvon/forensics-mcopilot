#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_batch_c_cjkpaths.py —— 批 C 第 7 项：中文路径漏检（工具缺陷）+ 由此暴露的 7 处泄露（2026-10-22）。

一、工具缺陷（比它查出的泄露更重要）
`git ls-files` 对**非 ASCII 路径**默认加引号并转义（`"docs/jd_\350\257\201..."`）✗，
于是按该列表拼路径必然 `isfile` 失败 → **整批中文名文件被静默跳过** ✗。
实证：mcopilot 有 **29 个**这样的文件 ✗。
后果：scan_absolute_paths.py 报"家目录 0 处" ✗（实为漏检），
      check_doc_refs_heads.py 的 HEAD 集合同样缺这批 ✗，
      probe_publish_readiness.py 的跟踪清单同样缺 ✗。
**静默漏检的工具比没有工具更坏** ✗ —— 它给出的是假的"0"。
处置：全部改用 `git ls-files -z`（NUL 分隔，不加引号）✓。

二、工具补上以后暴露的 7 处真泄露（mcopilot）
用户目录与第三方工具的会话目录混在文档里 ✗：
  docs/交叉验证_Export10.md、docs/评审_Trae修复.md、docs/评审_Trae修复验证.md、
  docs/项目回顾与收尾_20261021.md、docs/jd_证据_20261021/tag_jds.py、
  src/mcopilot/core/twincat.py（docstring 示例）、docs/事故_G6幽灵功能_20261022.md（追记）
按三仓既有的脱敏体例改：路径整体换成占位，只留 basename 或语义 ✓。
"""
import io
import os
import sys

BOOK = r"%WORKSPACE%\forensics-learning-book"
MC = r"%WORKSPACE%\mcopilot"

# ── 一、工具层：ls-files → ls-files -z ────────────────────────────────────
TOOL_FIXES = [
    ("tools/scan_absolute_paths.py",
     'files = [f for f in git(repo, "ls-files").splitlines() if f]',
     'files = [f for f in git(repo, "ls-files", "-z").split("\\0") if f]   # -z：中文路径不加引号'),
    ("tools/check_doc_refs_heads.py",
     'HEADS = {name: set(git(repo, "ls-files").splitlines()) for name, repo in REPOS.items()}',
     'HEADS = {name: set(f for f in git(repo, "ls-files", "-z").split("\\0") if f)\n'
     '         for name, repo in REPOS.items()}   # -z：中文路径不加引号（否则整批中文名文件漏检）'),
    ("tools/check_doc_refs_heads.py",
     'tracked = git(repo, "ls-files").splitlines()',
     'tracked = [f for f in git(repo, "ls-files", "-z").split("\\0") if f]'),
    ("tools/check_doc_refs_heads.py",
     'untracked = [f for f in git(repo, "ls-files", "--others", "--exclude-standard").splitlines()',
     'untracked = [f for f in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\\0") if f'),
    ("tools/probe_publish_readiness.py",
     'tracked = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True,',
     'tracked = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True, text=True,'),
]

# ── 二、mcopilot 文档层：7 处路径改占位 ───────────────────────────────────
MC_FIXES = [
    ("docs/jd_证据_20261021/tag_jds.py",
     'import json\nimport re\nimport sys\n',
     'import json\nimport os\nimport re\nimport sys\n'),
    ("docs/jd_证据_20261021/tag_jds.py",
     'SRC = r"%USERPROFILE%\\Documents\\deepseek-harness\\default-workspace\\out\\_boss\\jds.jsonl"',
     '# 输入件在会话工作区（不随仓分发）：用环境变量 JDS_JSONL 指到它\n'
     'SRC = os.environ.get("JDS_JSONL") or r"<会话工作区>\\out\\_boss\\jds.jsonl"'),
    ("docs/交叉验证_Export10.md",
     'cd %USERPROFILE%\\.minimax\\sessions\\mvs_838bec01bb00476594f48711e6b172d0\\workspace\\mcopilot',
     'cd <本仓根目录>'),
    ("docs/评审_Trae修复.md",
     '> 评审对象：`%USERPROFILE%\\Documents\\Trae-CN\\temp_20261019_01`',
     '> 评审对象：`<Trae-CN 会话工作区>\\temp_20261019_01`'),
    ("docs/评审_Trae修复.md",
     'cd <家目录>/Documents/Trae-CN/temp_20261019_01',
     'cd <Trae-CN 会话工作区>/temp_20261019_01'),
    ("docs/评审_Trae修复验证.md",
     '> 复核对象：`%USERPROFILE%\\Documents\\Trae-CN\\temp_20261019_01`',
     '> 复核对象：`<Trae-CN 会话工作区>\\temp_20261019_01`'),
    ("docs/评审_Trace修复验证.md",  # 占位：下面用真实文件名替换
     'x', 'x'),
    ("docs/评审_Trae修复验证.md",
     '- 复核环境里 `%USERPROFILE%\\Documents\\Trae-CN\\temp_20261019_01` **没有 `.git`**',
     '- 复核环境里 `<Trae-CN 会话工作区>\\temp_20261019_01` **没有 `.git`**'),
    ("docs/项目回顾与收尾_20261021.md",
     '- 删 `%USERPROFILE%\\chrome-cdp-profile`',
     '- 删 `<用户目录>\\chrome-cdp-profile`'),
    ("src/mcopilot/core/twincat.py",
     '   ``<工作区>\\\\\\\\axiscope\\\\data\\\\raw\\\\Export10_244531.csv``',
     '   ``<axiscope 仓>/data/raw/Export10_244531.csv``'),
    ("docs/事故_G6幽灵功能_20261022.md",
     '**（追记 2026-10-22：已同日清偿——三项目 path 改指 %WORKSPACE%\\{trae_factory,\n'
     '  mcopilot, axiscope}，账本 updated 同步 2026-10-22，见后续账本修复提交。）**',
     '**（追记 2026-10-22：已同日清偿——三项目 path 改指同级兄弟相对路径\n'
     '  （trae_factory / mcopilot / axiscope），账本 updated 同步 2026-10-22，见后续账本修复提交。）**'),
]
# 去掉占位行
MC_FIXES = [f for f in MC_FIXES if f[1] != "x"]


def apply(fixes, root, label):
    cache = {}
    failed = []
    applied = 0
    for rel, old, new in fixes:
        path = os.path.join(root, rel.replace("/", os.sep))
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        eol = "\r\n" if "\r\n" in txt else "\n"
        old_e, new_e = old.replace("\n", eol), new.replace("\n", eol)
        got = txt.count(old_e)
        if got != 1:
            failed.append((rel, old[:60], got))
            continue
        cache[path] = txt.replace(old_e, new_e)
        applied += 1
    if failed:
        print(f"✗ {label} 有替换未命中（未写盘）：")
        for rel, old, got in failed:
            print(f"    {rel}  实得 {got} 处  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ {path.replace(root, '')}")
    print(f"  {label}：{applied} 处落盘（{len(cache)} 个文件）")


apply(TOOL_FIXES, BOOK, "工具层")
print()
apply(MC_FIXES, MC, "mcopilot 文档层")
