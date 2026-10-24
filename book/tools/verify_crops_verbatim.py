#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_crops_verbatim.py —— 裁剪件"原样裁剪"核验。

纪律：各章「可验证主张」与「讲师 90 分钟」段必须**一字未改**地出现在裁剪件里。

判据：**直接调用生成器自己的抽取函数**取块，再逐行核对该块的每一行都原样出现在裁剪件中——
这才是"原样裁剪"的真判据（不用正则猜"哪一行是主张"，章头也有
`> **可验证主张**：见 §x.y` 指针行，正则会抓错）。

2026-10-24：裁剪件由两件合成一件（简历版 / 讲师版 → 裁剪版），
核验范围随之收成一件；仓根从 `__file__` 反推，不写死绝对路径。
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_crops import CROP_NAME, OUT, SRC, CHAPTERS, extract_claim, extract_teacher  # noqa: E402

# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

crop_path = OUT / CROP_NAME
if not crop_path.exists():
    print(f"[FAIL] 裁剪件不存在：{crop_path}")
    sys.exit(1)
crops = io.open(crop_path, encoding="utf-8").read()

bad = 0
for fn in sorted(x for x in os.listdir(SRC) if x.endswith(".md") and x != "00-导读.md"):
    # 00-导读.md 是卷首导读页，按体例不含主张/切分，不参与裁剪核验
    text = io.open(SRC / fn, encoding="utf-8").read()
    for label, block in (
        ("可验证主张", extract_claim(text)),
        ("讲师切分", extract_teacher(text)),
    ):
        if not block:
            print(f"[SKIP] {fn} {label}：章内无可抽取块")
            continue
        missing = [l for l in block if l.strip() and l.strip() not in crops]
        if not missing:
            print(f"[OK] {CROP_NAME} ← {fn} {label}：{len(block)} 行逐字命中")
        else:
            bad += 1
            print(f"[DIFF] {CROP_NAME} ← {fn} {label}：{len(missing)} 行未原样出现")
            for l in missing[:3]:
                print(f"        缺：{l.strip()[:100]}")

# 求职口径不该再出现（开源对象是"一类开发者"，不是一个人的求职）。
# 「为什么只有一版」那一节**点名被删掉的东西**是允许的——那是判据，不是用法；
# 所以先把它摘掉，再查剩下的部分。
import re as _re
_body = _re.split(r"^## 为什么只有一版\s*$", crops, flags=_re.M)
_body = _body[0] + (_body[2] if len(_body) > 2 else "")
JOB_HUNTING = ["简历版", "简历句", "按岗位", "投递", "面试官", "勿全贴", "求职", "挑选建议"]
leftover = [w for w in JOB_HUNTING if w in _body]
if leftover:
    bad += 1
    print(f"[DIFF] 裁剪件里仍有求职口径：{leftover}")

# 结构：裁剪件只能有一件（不再按用途分两型）
others = sorted(p.name for p in OUT.glob("*.md") if p.name != CROP_NAME)
if others:
    bad += 1
    print(f"[DIFF] crops/ 下应当只有一件裁剪件，还多出：{others}")

print("不一致条数：", bad)
sys.exit(1 if bad else 0)
