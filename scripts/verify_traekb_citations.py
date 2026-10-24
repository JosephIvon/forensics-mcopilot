#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真值桥：机检 Trae 代码工厂知识库 `gen/adapters_kb.js` 里嵌入的真值行号引用。

为什么需要这个
--------------
Trae 的 `gen/adapters_kb.js` 是**手抄**的官方真值：函数原型与出处都写死在
`chk: '官方原型 GT_Open(...)（gts.csv:326 / gts_hdr.csv:398）'` 这种散文里。
生成器**从不读** `official_api/` 下的 CSV —— 那些 `file:line` 只是自由文本，
没有任何东西保证它还对得上。

真值 CSV 一改，引用就悄悄过期；而**过期的引用比没有引用更坏**：
读的人会以为出处仍然可信。同类的真实事故已经发生过 ——
`knowledge/cam_rules.json` 曾把 9 个「官方 C# 绑定里没有的符号」写错 7 个。

所以这里把「散文里的出处」变成**可执行的断言**：
每条 `file:line` 引用都必须指向真值文件里**真的含有它所声称的那个符号**的那一行。

支持的引用写法
--------------
    gts.csv:326            单行
    gts.csv:129/393/336    斜杠列表（多个行号对应多个符号）
    gts_hdr_macros.csv:163-169  行号范围（对应一段宏）
    gts.csv:180/396        混合

三类引用分别判
--------------
    函数原型   —— 该行必须含有被引的函数名（如 `GT_Open,gts.dll,"GT_Open(...)"`）
    常量/宏    —— 宏表/结构体表，该行的**键名**必须在引用所在的那句话里出现
    范围       —— 范围首行必须命中，且范围内必须真的存在被引的宏

用法
----
    python scripts/verify_traekb_citations.py
    python scripts/verify_traekb_citations.py --kb C:\\path\\to\\adapters_kb.js
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "knowledge", "sdks", "official_api")
# trae_factory 仓的位置：环境变量 TRAE_FACTORY_DIR 优先，其次按同级兄弟目录找
_TRAE = os.environ.get("TRAE_FACTORY_DIR") or os.path.join(os.path.dirname(ROOT), "trae_factory")
DEFAULT_KB = os.path.join(_TRAE, "gen", "adapters_kb.js")

# 真值文件 -> 类别
FUNC_CSV = {"gts.csv", "leisai.csv", "zmotion.csv", "zmotion_cpp.csv",
            "gts_hdr.csv", "leisai_cpp.csv", "dll_exports.csv", "binding_returns.csv"}
CONST_CSV = {"gts_hdr_macros.csv", "gts_structs.csv"}

# 引用写法：file:N  file:N/M  file:N-M
CITE = re.compile(r"(?P<file>[a-z0-9_]+\.csv)\s*[:：]\s*(?P<spec>\d+(?:\s*[/–—-]\s*\d+)*)")

# 厂商函数名
FUNC = re.compile(r"\b((?:dmc|GT|GTN|ZAux|ZMC)_[A-Za-z0-9_]+)\b")
# 宏名 / 结构体名（全大写或驼峰的标识符）
IDENT = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

# 一条「主张」= 一段文本（chk 字符串或注释行），引用必须在其中被解释
CLAIM_UNIT = re.compile(r"chk:\s*'((?:[^'\\]|\\.)*)'")


def load_lines(name):
    path = os.path.join(API, name)
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8-sig", errors="replace") as fh:
        return fh.read().splitlines()


def parse_spec(spec):
    """'129/393/336' -> [(129,), (393,), (336,)]；'163-169' -> [(163,169)]。"""
    out = []
    for part in re.split(r"[/]", spec):
        part = part.strip()
        rng = re.match(r"^(\d+)\s*[–—-]\s*(\d+)$", part)
        if rng:
            a, b = int(rng.group(1)), int(rng.group(2))
            out.append(tuple(range(a, b + 1)))
        elif part.isdigit():
            out.append((int(part),))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="机检 Trae 知识库里的真值行号引用")
    ap.add_argument("--kb", default=DEFAULT_KB, help="adapters_kb.js 路径")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.kb):
        print("找不到知识库 %s（用 --kb 指定）" % args.kb)
        return 2
    txt = io.open(args.kb, encoding="utf-8", errors="replace").read()

    # ---- 切出「主张单元」 ----
    # 单元 = 一条完整的主张文本。`chk:` 是单行字符串；注释则按**连续注释块**切，
    # 因为一条真值说明常跨两行（函数名在上一行，行号在下一行）。
    units = []
    for m in CLAIM_UNIT.finditer(txt):
        units.append((m.group(1), m.start()))
    for m in re.finditer(r"(?m)(?:^[ \t]*//[^\n]*\n?)+", txt):
        units.append((m.group(0), m.start()))
    units.sort(key=lambda x: x[1])

    cache = {}

    def lines_of(name):
        if name not in cache:
            cache[name] = load_lines(name)
        return cache[name]

    stats = defaultdict(int)
    problems = []
    caveats = []

    for unit, _pos in units:
        cites = list(CITE.finditer(unit))
        if not cites:
            continue
        funcs = set(FUNC.findall(unit))
        idents = set(IDENT.findall(unit))
        for cm in cites:
            fname = cm.group("file")
            L = lines_of(fname)
            if L is None:
                problems.append(("真值文件不存在", fname, cm.group("spec"), ""))
                stats["missing_file"] += 1
                continue
            for group in parse_spec(cm.group("spec")):
                first = group[0]
                if not (1 <= first <= len(L)):
                    problems.append(("行号越界", fname, str(group), "文件共 %d 行" % len(L)))
                    stats["out_of_range"] += 1
                    continue
                target = L[first - 1]
                if fname in CONST_CSV:
                    # 常量/宏引用：该行的键名必须在主张里出现
                    key = target.split(",")[0].strip()
                    if key and key in unit:
                        stats["const_ok"] += 1
                        if len(group) > 1:
                            # 范围引用：**方向是 claim ⊆ range** ——
                            # 主张里点名的宏必须都落在引用的范围内；
                            # 范围比主张宽没关系（那是「指到这一族」的意思）。
                            inrange = {L[i - 1].split(",")[0].strip()
                                       for i in group if i <= len(L)}
                            named = {k for k in idents
                                     if any(L[i - 1].split(",")[0].strip() == k
                                            for i in range(1, len(L) + 1))}
                            miss = sorted(named - inrange)
                            if miss:
                                problems.append(("主张点名的宏不在引用范围内", fname,
                                                 "%d-%d" % (group[0], group[-1]),
                                                 "范围外: " + ", ".join(miss)))
                                stats["range_miss"] += 1
                            # 同族宏外溢：范围内还有同前缀的宏没被点名，
                            # 或范围外还有同族宏 —— 读者按范围找会漏
                            # 同族宏外溢：取**两层**前缀（HOME_MODE_LIMIT → HOME_MODE_），
                            # 一层会把 HOME_STAGE_* / HOME_ERROR_* 全拉进来，没有信息量
                            parts = key.split("_")
                            fam = "_".join(parts[:2]) + "_" if len(parts) >= 2 else ""
                            if fam:
                                sib = [(i, L[i - 1].split(",")[0].strip())
                                       for i in range(1, len(L) + 1)
                                       if L[i - 1].split(",")[0].strip().startswith(fam)]
                                outside = [(i, k) for i, k in sib if i < group[0] or i > group[-1]]
                                if outside:
                                    caveats.append(
                                        ("同族宏在引用范围之外", "%s:%d-%d" % (fname, group[0], group[-1]),
                                         "、".join("%s(%d)" % (k, i) for i, k in outside)
                                         + " —— 读者按引用范围找不到它们"))
                    else:
                        problems.append(("宏引用对不上", fname, str(group), target.strip()[:80]))
                        stats["const_bad"] += 1
                    continue
                # 函数原型引用：该行必须含有主张里提到的某个函数名
                if any(f in target for f in funcs):
                    stats["func_ok"] += 1
                    continue
                # 该行本身可能是别的函数（斜杠列表对应多个符号）——逐行核
                problems.append(("该行未见所引函数", fname, str(group), target.strip()[:80]))
                stats["func_bad"] += 1

    # ---- 语义未背书的宏（真值表只有名+值，没说它是什么）----
    # 真值宏表只有「宏名,值」两列，没有说明这个常量**是什么**。
    # 主张里若引用了这类宏而没自己标注「真值未说明」，那就是把未背书的语义
    # 当成已背书的来用 —— 机器查不出来，只能靠人自觉标注，这里替人查一遍。
    for m in re.finditer(r"MC_GP[IO]", txt):
        s = max(0, m.start() - 200)
        e = min(len(txt), m.end() + 300)
        seg = txt[s:e]
        if not any(k in seg for k in ("真值未标注", "待手册确认", "对应关系", "候选值")):
            problems.append(("宏语义无真值背书且未标注", "gts_hdr_macros.csv:17,22",
                             "MC_GPI/MC_GPO", "主张里没说它的含义从哪来"))
            stats["unsupported_macro"] += 1
        else:
            caveats.append(("宏语义未背书（已自行标注）",
                            "gts_hdr_macros.csv:17,22",
                            "MC_GPI/MC_GPO 与 diType/doType 的对应关系 —— 已列入厂商索取清单"))
        break

    total = sum(stats.values())
    # 同一条引用会同时出现在 chk 字符串和注释块里 —— 去重，别把一件事报两遍
    def dedup(seq):
        seen, out = set(), []
        for item in seq:
            k = item[:3]
            if k in seen:
                continue
            seen.add(k)
            out.append(item)
        return out
    problems = dedup(problems)
    caveats = dedup(caveats)

    print("### Trae 知识库真值引用机检：%s" % args.kb)
    print("  主张单元            : %d" % len(units))
    print("  校验的引用组        : %d" % total)
    print("  函数原型引用 命中    : %d" % stats["func_ok"])
    print("  常量/宏引用   命中   : %d" % stats["const_ok"])
    print("  不命中              : %d" % (stats["func_bad"] + stats["const_bad"]))
    print("  行号越界            : %d" % stats["out_of_range"])
    print("  真值文件缺失        : %d" % stats["missing_file"])
    print()
    if problems:
        print("### 不命中的引用（必须修）")
        for why, fname, spec, detail in problems:
            print("  [%s] %s:%s  %s" % (why, fname, spec, detail))
        print()
    if caveats:
        print("### 需要人背书的语义（不是错误，但真值里查不到）")
        for why, where, what in caveats:
            print("  [%s] %s" % (why, where))
            print("       %s" % what)
        print()
    print("结论: %s" % ("全部引用对得上" if not problems else "存在失配，见上表"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
