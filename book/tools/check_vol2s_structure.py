#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_vol2s_structure.py —— 本书结构体检（2026-10-24 随并仓收敛为一本）。

逐章检查必备件：
  标题 / **本章承接**（须在章首 12 行内）/ **学完你会** / **前置** / 素材坐标 / 已验算 /
  证据与坐标区 / 可验证主张 / 讲师切分 / 习题 / 尾注坐标
检查导读页：标题 / 写给读者的建议 / 章速查表 / 证据与坐标区指引。
并扫描违禁项：会话坐标、未经口径的计数、裸行号坐标。

2026-10-24 变更：书随 `mcopilot` 仓开源，**只留与本仓代码对得上的一册**；
另两册（axiscope / code factory）随各自的仓走，不在本仓体检范围内。
"简历句框"改称"可验证主张"——开源后面对的是一类开发者，不是一个人的求职。
仓根从 `__file__` 反推，不写死绝对路径。
"""
import io
import os
import re
import sys
from pathlib import Path
# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

REPO = str(Path(__file__).resolve().parents[1])
VOLS = [
    ("卷一", os.path.join(REPO, "chapters"), 9),
]
BAD_PATTERNS = [
    # 「不设会话坐标」是正文里的否定用法（"本段不设会话坐标"），不是违禁项 → 一并排除
    (re.compile(r"(?<![禁不无])(?<!不设)会话坐标|本轮对话|上文提到|前面说过"), "会话坐标"),
    (re.compile(r"（`:\d+"), "裸行号坐标"),
]

bad = 0
for volname, src, want in VOLS:
    guide = os.path.join(src, "00-导读.md")
    files = sorted(x for x in os.listdir(src) if x.endswith(".md") and x != "00-导读.md")
    print(f"[{volname}] 章数 {len(files)} / 预期 {want}", "OK" if len(files) == want else "❌")
    if len(files) != want:
        bad += 1
    # 导读页体检
    if os.path.isfile(guide):
        g = io.open(guide, encoding="utf-8").read()
        gneed = {
            "标题": g.startswith("# "),
            "读者建议": "写给读者的建议" in g,
            "章速查": "速查" in g,
            "证据区指引": "证据与坐标" in g,
        }
        gmiss = [k for k, v in gneed.items() if not v]
        ghits = [lbl for pat, lbl in BAD_PATTERNS if pat.search(g)]
        if gmiss or ghits:
            bad += 1
            print(f"  ❌ 00-导读.md：缺 {gmiss or '无'}{' ｜ ' + ', '.join(ghits) if ghits else ''}")
        else:
            print(f"  ✅ 00-导读.md（{len(g.splitlines())} 行）")
    else:
        bad += 1
        print("  ❌ 00-导读.md：不存在")

    for fn in files:
        text = io.open(os.path.join(src, fn), encoding="utf-8").read()
        lines = text.splitlines()
        head = "\n".join(lines[:12])
        need = {
            "标题": text.startswith("# "),
            "承接段": "**本章承接**" in head,
            "学完你会": "**学完你会**" in head,
            "前置": "**前置**" in head,
            "素材坐标": "**素材坐标**" in text,
            "已验算": "**已验算**" in text,
            "证据与坐标区": "## 证据与坐标" in text,
            # 判据必须是**起始行**：`or ("可验证主张" in text)` 会让后半句作废前半个子句——
                # 章节里随便哪个位置出现这五个字就算合格，整节删掉也照样「问题章数 0」。
                # （2026-10-25 评审实测：删掉 ch04 整节 13 行，本门仍 exit 0。）
                "可验证主张": text.count("> **可验证主张**") >= 2,
            "讲师切分": ("**讲师 90 分钟**" in text) or ("讲师切分" in text),
            "尾注坐标": "事实性句子坐标" in text,
            "习题": "习题" in text,
        }
        miss = [k for k, v in need.items() if not v]
        hits = []
        for pat, label in BAD_PATTERNS:
            for m in pat.finditer(text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{label}@L{line}")
        if miss:
            bad += 1
            print(f"  ❌ {fn}：缺 {miss}")
        elif hits:
            bad += 1
            print(f"  ❌ {fn}：{' ｜ '.join(hits)}")
        else:
            print(f"  ✅ {fn}（{len(lines)} 行）")

# ---- 书级前后言体检 ----
for fn in ("前言.md", "尾声.md"):
    path = os.path.join(REPO, fn)
    if not os.path.isfile(path):
        print(f"  ❌ {fn}：文件不存在")
        bad += 1
        continue
    text = io.open(path, encoding="utf-8").read()
    need = {
        "标题": text.startswith("# "),
        "主张块": "> **" in text,
        "尾注坐标": "事实性句子坐标" in text,
    }
    miss = [k for k, v in need.items() if not v]
    hits = []
    for pat, label in BAD_PATTERNS:
        for m in pat.finditer(text):
            hits.append(f"{label}@L{text[:m.start()].count(chr(10)) + 1}")
    if miss or hits:
        bad += 1
        print(f"  ❌ {fn}：缺 {miss or '无'}{' ｜ ' + ', '.join(hits) if hits else ''}")
    else:
        print(f"  ✅ {fn}（{len(text.splitlines())} 行）")

print("问题章数：", bad)
sys.exit(1 if bad else 0)
