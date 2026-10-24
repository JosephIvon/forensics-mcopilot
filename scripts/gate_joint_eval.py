#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_joint_eval.py —— G13：接缝 3（共享行为评测集）的账实相符门禁。

分两截 ✓
--------
**静态截**（任何环境都能跑 ✓，干净克隆里也跑 ✓）：
  S1 评测集存在且可解析 ✓
  S2 条数与差异条数 = meta.counts 自报数 ✓
  S3 id 唯一 ✓、id 形如 BEH-xx ✓
  S4 status ∈ {pass, partial, blank, n/a} ✓
  S5 有 mcopilot 验证点（且非机器比对）的条目 ✓ 必须在 mcopilot 侧模板
     `knowledge/templates/SelfCheck.cs.tmpl` 里有同名标签 ✓
  S6 工厂侧 status==pass 的条目 ✓ 分类必须完整（有 scope 或 mcopilot 键 ✓）
  S7 兄弟仓在位时：工厂侧 `gen/core.js` 的 [BEH-xx] 标签集合 ✓
     必须等于评测集里 status==pass 的 id 集合 ✓（**不许有没登记的断言** ✓）
  S8 兄弟仓不在位 ⟹ S7 记 SKIP ✓（不是失败 ✓，也不是通过 ✓）

**动态截**（要编译器 ✓ + 工厂兄弟仓 ✓）：
  D1 真跑 `scripts/joint_eval.py` ✓ —— 两侧逐条对齐 ✓
  D2 缺环境 ⟹ 脚本自己喊「当前不可自动复核」✓ → 本门禁记 SKIP ✓，**不许记 PASS** ✓

为什么要单独一道门 ✓
------------------
评测集是接缝 3 的**唯一数据源** ✓ —— 它一过期，两侧就会各说各话 ✓。
2026-10-20 那份矩阵里，工厂侧对 6 条断言的「实测命中」其实是**粗粒度匹配**
（只看 GlueDemo 整体 RESULT: PASS ✗，没逐条对上 ✗）✓。
现在两侧都打了 BEH 编号 ✓，本门禁就是防止编号与评测集**再次对不上** ✓。

输出约定 ✓：最后一行 `GATE-RESULT: PASS|SKIP|FAIL` ✓ + 原因 ✓。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = ROOT / "knowledge" / "shared_eval.json"
TEMPLATE = ROOT / "knowledge" / "templates" / "SelfCheck.cs.tmpl"
JOINT = ROOT / "scripts" / "joint_eval.py"
VALID_STATUS = {"pass", "partial", "blank", "n/a"}
BEH_ID_RE = re.compile(r"^BEH-\d{2}$")
TAG_RE = re.compile(r"\[?BEH-(\d+)\]?")

problems: list[str] = []
skips: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def skip(msg: str) -> None:
    skips.append(msg)


def find_trailing_repo():
    env = os.environ.get("TRAE_FACTORY_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    sib = ROOT.parent / "trae_factory"
    return sib if sib.is_dir() else None


# ── 静态截 ────────────────────────────────────────────────────────────
def static_checks() -> bool:
    if not EVAL_SET.is_file():
        fail("评测集不存在：%s（接缝 3 闭合后它必须在仓里）" % EVAL_SET)
        return False
    try:
        ev = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    except Exception as exc:
        fail("评测集解析失败：%s" % exc)
        return False

    cases = ev.get("cases") or []
    divs = ev.get("divergences") or []
    meta = ev.get("meta", {}).get("counts", {})

    # S2 自报数 vs 实际数
    if meta.get("cases_total") != len(cases):
        fail("cases_total 自报 %s，实际 %d 条" % (meta.get("cases_total"), len(cases)))
    if meta.get("divergences") != len(divs):
        fail("divergences 自报 %s，实际 %d 条" % (meta.get("divergences"), len(divs)))

    # S3 id 唯一 + 形状
    ids = [c.get("id") for c in cases]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        fail("id 重复：%s" % ", ".join(sorted(dup)))
    for c in cases:
        if not BEH_ID_RE.match(str(c.get("id", ""))):
            fail("id 形状不对（应 BEH-xx）：%r" % c.get("id"))
        if not c.get("name"):
            fail("%s 缺 name" % c.get("id"))
        if not c.get("domain"):
            fail("%s 缺 domain" % c.get("id"))
        # S4 status
        st = (c.get("factory") or {}).get("status")
        if st not in VALID_STATUS:
            fail("%s 的 factory.status 非法：%r（允许 %s）"
                 % (c.get("id"), st, "/".join(sorted(VALID_STATUS))))
        # S6 分类完整
        if st == "pass" and not c.get("mcopilot") and not c.get("scope"):
            fail("%s 是 pass 但既无 mcopilot 验证点也无 scope——分类说不清" % c.get("id"))
        if c.get("scope") and c.get("scope") not in ("factory_only", "single_sided"):
            fail("%s 的 scope 非法：%r" % (c.get("id"), c.get("scope")))

    # S5 mcopilot 侧标签（在仓内的模板上核对）
    if not TEMPLATE.is_file():
        skip("mcopilot 侧自检模板不在位：%s" % TEMPLATE)
    else:
        tmpl = TEMPLATE.read_text(encoding="utf-8")
        tmpl_ids = set()
        for m in re.finditer(r'Check\("(?P<id>BEH-\d{2})\s', tmpl):
            tmpl_ids.add(m.group("id"))
        expect = {c["id"] for c in cases
                  if c.get("mcopilot") and not c.get("compare")}
        missing = expect - tmpl_ids
        extra = tmpl_ids - expect
        if missing:
            fail("评测集说有 mcopilot 验证点，但 mcopilot 侧模板里没有这些标签：%s"
                 % ", ".join(sorted(missing)))
        if extra:
            fail("mcopilot 侧模板里有评测集没登记的标签：%s" % ", ".join(sorted(extra)))

    # S7 工厂侧标签（要兄弟仓）
    repo = find_trailing_repo()
    if repo is None:
        skip("工厂兄弟仓不在位（TRAE_FACTORY_DIR 或同级 ../trae_factory）——"
             "工厂侧标签核对**当前不可自动复核**")
    else:
        core = repo / "gen" / "core.js"
        if not core.is_file():
            skip("工厂侧 gen/core.js 不在位——标签核对当前不可自动复核")
        else:
            text = core.read_text(encoding="utf-8", errors="replace")
            gen_ids = set()
            for m in re.finditer(r"\[BEH-(\d+)\]", text):
                gen_ids.add("BEH-%02d" % int(m.group(1)))
            expect_pass = {c["id"] for c in cases
                           if (c.get("factory") or {}).get("status") == "pass"}
            missing = expect_pass - gen_ids
            extra = gen_ids - expect_pass
            if missing:
                fail("评测集登记为 pass，但工厂侧代码里没有这些标签：%s"
                     % ", ".join(sorted(missing)))
            if extra:
                fail("工厂侧代码里有评测集没登记的 BEH 标签：%s" % ", ".join(sorted(extra)))
    return True


# ── 动态截 ────────────────────────────────────────────────────────────
def dynamic_check() -> str:
    """返回 PASS / SKIP / FAIL"""
    if not JOINT.is_file():
        fail("对照脚本不存在：%s" % JOINT)
        return "FAIL"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(ROOT / "src")
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", str(JOINT)], cwd=str(ROOT),
                           env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=2400)
    except subprocess.TimeoutExpired:
        fail("对照脚本超时")
        return "FAIL"
    except OSError as exc:
        fail("对照脚本无法执行：%s" % exc)
        return "FAIL"
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        for line in out.splitlines():
            if line.strip().startswith(("- ", "⚠", "   -")):
                fail("对照脚本报：%s" % line.strip())
        fail("对照脚本退出码 %d" % p.returncode)
        return "FAIL"
    if "当前不可自动复核" in out or "未做实测" in out:
        skip("两侧未真跑（缺编译器或工厂兄弟仓）——本次**当前不可自动复核**，"
             "不算检测力已证明")
        return "SKIP"
    if "两侧逐条对齐" not in out:
        fail("对照脚本没有给出「两侧逐条对齐」的结论——判据读不懂")
        return "FAIL"
    return "PASS"


def main() -> int:
    print("G13 接缝 3（共享行为评测集）账实相符门禁")
    static_checks()
    dyn = dynamic_check()
    print("")
    for s in skips:
        print("  SKIP：%s" % s)
    for f in problems:
        print("  FAIL：%s" % f)
    if problems:
        print("GATE-RESULT: FAIL")
        return 1
    if skips:
        print("GATE-RESULT: SKIP")
        return 0
    print("GATE-RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
