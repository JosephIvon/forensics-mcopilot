#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""joint_eval.py —— 接缝 3 的对照脚本：**真跑两边**，逐条对齐 BEH 断言。

为什么要有它 ✓
--------------
工厂端到端 PASS 里的每一步，都要能指到共享评测集的一条断言上——
否则就是**无背书的自证** ✓。这个脚本就是那个"背书"的机器：

  侧 A（mcopilot）✓：编译并**真跑**仿真器自检（`scripts/compile_check.ps1`）✓
  侧 B（工厂）✓：编译并**真跑** GlueDemo 工艺流程（`out/mc_all/build/build_net48.bat`）✓
  比对 ✓：按 BEH 编号逐条对齐 ✓ + BEH-19 的 SPC **机器比对** ✓
  产出 ✓：`out/joint_eval.md`（对照矩阵 ✓）

三条纪律 ✓
----------
① **verdict 只认本次实测** ✓ —— 不许拿"上次跑过"当证据 ✓；
   两侧的每一条都从**本次运行的输出**里解析 ✓。
② **缺环境 = SKIP，不是 PASS** ✓ —— 找不到编译器 ✓ / 找不到工厂兄弟仓 ✓，
   一律记 SKIP 并在汇总行喊「当前不可自动复核」✓，退出码 0 但**不许算通过** ✓。
③ **评测集是唯一数据源** ✓ —— 本脚本不内置任何断言清单 ✓，
   清单在 `knowledge/shared_eval.json` ✓，改了清单不用改本脚本 ✓。

用法 ✓
------
    python scripts/joint_eval.py
    TRAE_FACTORY_DIR=<工作区>\\\\trae_factory python scripts/joint_eval.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = ROOT / "knowledge" / "shared_eval.json"
OUT_MD = ROOT / "out" / "joint_eval.md"

BEH_RE = re.compile(r"BEH-(\d+)")
# mcopilot 侧自检的输出形状：[ok]   BEH-01 跟随误差必须非零（抓假反馈）
MC_OK_RE = re.compile(r"^\[ok\]\s+(BEH-\d+)\s+(.*)$")
MC_FAIL_RE = re.compile(r"^\[fail\]\s+(BEH-\d+)\s*(.*)$")

SKIP_REASON = ""


# ── 基础设施 ───────────────────────────────────────────────────────────
def _run(cmd, cwd, timeout=1800, stdin_null=False):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        if stdin_null:
            with open(os.devnull, "r") as devnull:
                p = subprocess.run(cmd, cwd=cwd, env=env, stdin=devnull,
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
        else:
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 99, "超时（%ss）" % timeout
    except OSError as exc:
        return 98, "无法执行：%s" % exc


def find_trailing_repo():
    """工厂兄弟仓：环境变量优先，其次按同级兄弟目录找（与仓内其它脚本同口径）。"""
    env = os.environ.get("TRAE_FACTORY_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    for name in ("forensics-code-factory", "trae_factory"):
        sib = ROOT.parent / name
        if sib.is_dir():
            return sib
    return None


def have_compiler():
    """有没有能编译 C# 的东西：Roslyn / .NET SDK / .NET Framework。"""
    import glob
    candidates = []
    for base in [r"C:\Program Files (x86)\Microsoft Visual Studio",
                 r"C:\Program Files\Microsoft Visual Studio"]:
        candidates += glob.glob(base + r"\*\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe")
        candidates += glob.glob(base + r"*\MSBuild\Current\Bin\Roslyn\csc.exe")
    candidates += glob.glob(r"C:\Program Files\dotnet\sdk\*\Roslyn\bincore\csc.dll")
    fw = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                      r"Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if os.path.isfile(fw):
        candidates.append(fw)
    return [c for c in candidates if os.path.isfile(c)]


# ── 侧 A：mcopilot ─────────────────────────────────────────────────────
def run_mcopilot_side():
    """返回 (hits, detail_lines, note)。hits = {BEH-xx: 'pass'|'fail'}"""
    # 生成物在位吗？不在就按 knowledge/sdks/ 里的清单**逐个生成**——
    # compile_check.ps1 要三个适配器都在才肯编译（契约测试那一步要用），
    # 只生成一个的话，自检会被它 skip 掉，本脚本就一条都测不到（干净克隆里踩过）。
    gen = ROOT / "out" / "csharp" / "MotionSelfCheck.cs"
    if not gen.is_file():
        sdk_dir = ROOT / "knowledge" / "sdks"
        sdks = sorted(p.stem for p in sdk_dir.glob("*.json")) if sdk_dir.is_dir() else []
        if not sdks:
            return {}, [], "knowledge/sdks/ 里没有可用 SDK —— 当前不可自动复核"
        for sdk in sdks:
            rc, out = _run([sys.executable, "-X", "utf8", "-m", "mcopilot",
                            "adapter", "gen", "--sdk", sdk], cwd=ROOT)
            if rc != 0:
                return {}, [], "适配层生成失败（sdk=%s，退出码 %d）" % (sdk, rc)
    rc, out = _run(["pwsh", "-NoProfile", "-File",
                    str(ROOT / "scripts" / "compile_check.ps1")], cwd=ROOT)
    hits, details = {}, []
    for line in out.splitlines():
        m = MC_FAIL_RE.match(line.strip())
        if m:
            hits[m.group(1)] = "fail"
            details.append(line.strip())
            continue
        m = MC_OK_RE.match(line.strip())
        if m:
            hits[m.group(1)] = "pass"
            details.append(line.strip())
    if not hits:
        return {}, details, ("编译自检未产出任何 BEH 条目（退出码 %d）——"
                             "当前不可自动复核" % rc)
    return hits, details, ""


# ── 侧 B：工厂 ────────────────────────────────────────────────────────
def run_factory_side(repo):
    """返回 (hits, detail_lines, note, cpk_factory, report_csv)"""
    build_dir = repo / "out" / "mc_all" / "build"
    bat = build_dir / "build_net48.bat"
    if not bat.is_file():
        return {}, [], "工厂侧未生成套件（out/mc_all/build/build_net48.bat 不在位）", None, None
    # stdin 接 NUL：批处理末尾有 pause，脚本里不能等按键
    rc, out = _run(["cmd", "/c", "build_net48.bat"], cwd=str(build_dir), stdin_null=True)
    hits, details = {}, []
    cpk = None
    for line in out.splitlines():
        ids = BEH_RE.findall(line)
        if not ids:
            continue
        details.append(line.strip())
        for num in ids:
            bid = "BEH-%02d" % int(num)
            if "FAIL" in line.upper():
                hits[bid] = "fail"
            else:
                hits.setdefault(bid, "pass")
        m = re.search(r"Cpk=([0-9]+\.[0-9]+)", line)
        if m and bid_is_spc(line):
            cpk = float(m.group(1))
    csv = build_dir / "glue_report.csv"
    if rc != 0:
        return hits, details, "工厂侧构建/运行退出码 %d" % rc, cpk, (csv if csv.is_file() else None)
    return hits, details, "", cpk, (csv if csv.is_file() else None)


def bid_is_spc(line):
    return "SPC" in line.upper()


# ── BEH-19 的 SPC 机器比对：独立重算 Cpk ───────────────────────────────
def recompute_cpk(csv_path):
    """从工厂的原始样本独立重算 Cpk（与工厂同公式：样本标准差 n-1）。"""
    samples = []
    with csv_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(("sample", "mean", "sigma", "cpk")):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                samples.append(float(parts[1]))
            except ValueError:
                continue
    n = len(samples)
    if n < 2:
        return None, None, 0
    mean = sum(samples) / n
    var = sum((v - mean) ** 2 for v in samples) / (n - 1)
    sigma = var ** 0.5
    usl, lsl = 3.0, 2.0
    cpk = min(usl - mean, mean - lsl) / (3 * sigma) if sigma > 1e-9 else 99.0
    return cpk, sigma, n


# ── 判定 ───────────────────────────────────────────────────────────────
def judge(ev, mc_hits, fa_hits, spc):
    """逐条判定。返回 (rows, counts, problems)

    计数口径（与 2026-10-20 那份矩阵同拆法 ✓）：
      both          两侧都有验证点且本次都跑到了 ✓
      factory_only  工厂侧有断言、mcopilot 侧**无对应工具也无对应断言** ✓（BEH-16 ✓）
      single_sided  只有一侧有对应工具 ✓（BEH-17/18 工厂独有单边 ✓ +
                    BEH-02/05/06/10/11 mcopilot 独有单边 ✓）
      not_applicable  工厂接口无此概念 ✓（是 single_sided 的子集 ✓）
      blank_or_partial 工厂应验未验 = 整改清单 ✓
    """
    rows, problems = [], []
    counts = {"both": 0, "factory_only": 0, "single_sided": 0,
              "not_applicable": 0, "blank_or_partial": 0}
    for c in ev["cases"]:
        bid, status = c["id"], c["factory"]["status"]
        mc = mc_hits.get(bid)
        fa = fa_hits.get(bid)
        compare = c.get("compare")
        # BEH-19 这类：mcopilot 侧的验证点是**机器比对**（重算 Cpk），不是自检条目
        cmp_ok = None
        if compare == "cpk":
            if spc["recomputed"] is None or spc["factory"] is None:
                cmp_ok = False
                problems.append("%s 的 SPC 机器比对没做成（缺样本或缺工厂 Cpk）" % bid)
            else:
                cmp_ok = abs(spc["recomputed"] - spc["factory"]) <= 0.01
                if not cmp_ok:
                    problems.append("%s 的 SPC Cpk 对不上：独立重算 %.3f vs 工厂 %.3f"
                                    % (bid, spc["recomputed"], spc["factory"]))
        if status in ("blank", "partial"):
            counts["blank_or_partial"] += 1
            rows.append((c, mc, fa, "空白/部分（整改清单）"))
            continue
        if status == "n/a":
            # not_applicable 是 single_sided 的子集，这里只记 not_applicable，
            # 汇总行会把两者相加（见 render()）——两处都记就成了重复计数。
            counts["not_applicable"] += 1
            if fa is not None:
                problems.append("%s 登记为 n/a，但工厂侧实测到了（%s）——评测集过期了"
                                % (bid, fa))
            if mc is None:
                problems.append("%s 登记 n/a 且 mcopilot 侧未实测到——两侧都没验" % bid)
            rows.append((c, mc, fa, "单边（mcopilot 侧）" if mc else "两侧皆无"))
            continue
        # status == pass：工厂侧必须有实测命中
        if fa is None:
            problems.append("%s 登记为 pass，但工厂侧本次没实测到——工厂侧漏了断言" % bid)
        elif fa == "fail":
            problems.append("%s 工厂侧实测失败" % bid)
        mc_verified = (mc == "pass") if not compare else bool(cmp_ok)
        if compare:
            mc_label = "机器比对" + ("✓" if cmp_ok else "✗")
        else:
            mc_label = mc or "—"
            if c.get("mcopilot"):
                if mc is None:
                    problems.append("%s 登记两侧都验，但 mcopilot 侧本次没实测到" % bid)
                elif mc == "fail":
                    problems.append("%s mcopilot 侧实测失败" % bid)
        if c.get("mcopilot"):
            if fa and mc_verified:
                counts["both"] += 1
                verdict = "双方都验"
            else:
                counts["single_sided"] += 1
                verdict = "单边"
        else:
            # 工厂侧有、mcopilot 侧无——具体归哪一类由评测集的 scope 字段说，
            # 脚本不猜：factory_only（工厂自己的端到端流程）vs single_sided（普通行为，单边）。
            scope = c.get("scope")
            if scope == "factory_only":
                counts["factory_only"] += 1
                verdict = "工厂独有"
            elif scope == "single_sided":
                counts["single_sided"] += 1
                verdict = "单边（工厂侧）"
            else:
                problems.append("%s 没有 scope 字段——评测集不完整（该条该归哪类说不清）" % bid)
                counts["single_sided"] += 1
                verdict = "单边（工厂侧）·scope 缺失"
        if compare:
            verdict += "（SPC 机器比对 %s）" % ("一致" if cmp_ok else "不一致")
        rows.append((c, mc_label, fa, verdict))
    return rows, counts, problems


def render(ev, rows, counts, mc_hits, fa_hits, spc, problems, note):
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    s = ["# 共享行为评测集 · 实测对照矩阵（接缝 3）", "",
         "> 生成时间：%s　|　数据源：knowledge/shared_eval.json（唯一数据源）" % now,
         "> 本矩阵由 scripts/joint_eval.py **真跑两边**后生成：",
         "> mcopilot 侧 = 仿真器自检（scripts/compile_check.ps1）；",
         "> 工厂侧 = 全品牌套件 GlueDemo 工艺流程（out/mc_all/build/build_net48.bat）。",
         "> **verdict 只认本次实测**。", ""]
    if note:
        s += ["> ⚠ **%s**" % note, ""]
    s += ["- mcopilot 侧实测条目：%d 条（通过 %d / 失败 %d）"
          % (len(mc_hits), sum(1 for v in mc_hits.values() if v == "pass"),
             sum(1 for v in mc_hits.values() if v == "fail")),
          "- 工厂侧实测命中条目：%d 条（通过 %d / 失败 %d）"
          % (len(fa_hits), sum(1 for v in fa_hits.values() if v == "pass"),
             sum(1 for v in fa_hits.values() if v == "fail")), ""]
    s += ["| 断言 | 域 | mcopilot 实测 | 工厂实测 | 判定 |",
          "|---|---|---|---|---|"]
    for c, mc, fa, verdict in rows:
        s.append("| %s %s | %s | %s | %s | %s |"
                 % (c["id"], c["name"], c["domain"],
                    mc or "—", fa or "—", verdict))
    s += ["",
          "**汇总**：双方都验 %d · 工厂独有 %d · 单边 %d（其中 n/a %d）· 空白或部分 %d · 共 %d 条"
          % (counts["both"], counts["factory_only"],
             counts["single_sided"] + counts["not_applicable"],
             counts["not_applicable"], counts["blank_or_partial"], len(rows)), ""]
    if spc.get("recomputed") is not None:
        s += ["**BEH-19 SPC 机器比对**：工厂打印 Cpk = %.3f；"
              "本脚本从工厂原始样本（%s）独立重算 Cpk = %.3f（样本 σ=%.4f, n=%d）→ %s"
              % (spc["factory"] or float("nan"), spc.get("csv_name", "glue_report.csv"),
                 spc["recomputed"], spc.get("sigma") or 0.0, spc.get("n") or 0,
                 "一致 ✓" if spc["factory"] is not None
                 and abs(spc["recomputed"] - spc["factory"]) <= 0.01 else "不一致 ✗"), ""]
    if ev.get("divergences"):
        s += ["## 合法行为差异（不是 FAIL）", "", "| 议题 | mcopilot | 工厂 | 说明 |",
              "|---|---|---|---|"]
        for d in ev["divergences"]:
            s.append("| %s %s | %s | %s | %s |"
                     % (d["id"], d["topic"], d["mcopilot"], d["factory"], d["note"]))
        s.append("")
    s += ["## 判定依据", "",
          "- 本表每一行的 mcopilot/工厂两列都来自**本次运行**的输出解析 ✓；",
          "- 「工厂独有」= 工厂侧有断言、mcopilot 侧无对应工具与断言 ✓；",
          "- 「单边」= 只有一侧有对应工具 ✓（其中 n/a = 工厂接口无此概念 ✓）；",
          "- 「空白/部分」= 工厂应验未验，是**整改清单** ✓，不算 FAIL 也不算通过 ✓；",
          "- 评测集与两侧代码的编号一致性由 `scripts/gate_joint_eval.py` 静态核对 ✓。", ""]
    if problems:
        s += ["## 本次发现的问题（必须清偿）", ""]
        for p in problems:
            s.append("- ⚠ %s" % p)
        s.append("")
    s += ["---", "",
          "本评测集与 P/Invoke 真值链同一来源纪律：数据在 mcopilot 仓库，"
          "工厂生成时实时读取，绝不另设副本。", ""]
    return "\n".join(s)


def main():
    global SKIP_REASON
    if not EVAL_SET.is_file():
        print("✗ 找不到评测集：%s" % EVAL_SET)
        return 2
    ev = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    note = ""
    mc_hits, fa_hits = {}, {}
    spc = {"recomputed": None, "factory": None, "sigma": None, "n": 0}

    comps = have_compiler()
    repo = find_trailing_repo()
    if not comps:
        note = ("本机没有可用的 C# 编译器 —— 两侧**都没真跑**，本表**当前不可自动复核**。"
                "跳过 ≠ 通过。")
    elif repo is None:
        note = ("找不到工厂兄弟仓（TRAE_FACTORY_DIR 或同级 ../trae_factory）—— "
                "工厂侧**没真跑**，本表**当前不可自动复核**。跳过 ≠ 通过。")
    else:
        mc_hits, _mc_detail, mc_note = run_mcopilot_side()
        if mc_note:
            note = "mcopilot 侧：%s" % mc_note
        fa_hits, _fa_detail, fa_note, cpk_f, csv_p = run_factory_side(repo)
        if fa_note and not note:
            note = "工厂侧：%s" % fa_note
        spc["factory"] = cpk_f
        if csv_p and csv_p.is_file():
            cpk_r, sigma_r, n_r = recompute_cpk(csv_p)
            spc["recomputed"], spc["sigma"], spc["n"] = cpk_r, sigma_r, n_r
            spc["csv_name"] = csv_p.name

    rows, counts, problems = judge(ev, mc_hits, fa_hits, spc)
    if note:
        # 缺环境时不允许给出"通过"的判定
        for i, r in enumerate(rows):
            rows[i] = (r[0], r[1], r[2], "**未实测（当前不可自动复核）**")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render(ev, rows, counts, mc_hits, fa_hits, spc, problems, note),
                       encoding="utf-8")

    print("【接缝 3 对照】mcopilot 实测 %d 条 · 工厂实测 %d 条"
          % (len(mc_hits), len(fa_hits)))
    print("汇总：双方都验 %d · 工厂独有 %d · 单边 %d（n/a %d）· 空白或部分 %d · 共 %d 条"
          % (counts["both"], counts["factory_only"],
             counts["single_sided"] + counts["not_applicable"],
             counts["not_applicable"], counts["blank_or_partial"], len(rows)))
    print("产出：%s" % OUT_MD)
    if note:
        print("⚠ %s" % note)
        print("总退出码 0：本次**未做实测**，不是通过——当前不可自动复核。")
        return 0
    if problems:
        print("⚠ 本次发现 %d 个问题（必须清偿）：" % len(problems))
        for p in problems:
            print("   - %s" % p)
        print("总退出码 1：有对不上的地方。")
        return 1
    # 与评测集自报的计数核对——防止评测集过期
    meta = ev.get("meta", {}).get("counts", {})
    expect = {"cases_total": len(rows),
              "both_sides_verified": counts["both"],
              "factory_only": counts["factory_only"],
              "single_sided": counts["single_sided"] + counts["not_applicable"],
              "not_applicable": counts["not_applicable"],
              "blank_or_partial": counts["blank_or_partial"],
              "divergences": len(ev.get("divergences", []))}
    drift = [("%s: 评测集记 %s，实测 %s" % (k, meta.get(k), v))
             for k, v in expect.items() if k in meta and meta[k] != v]
    if drift:
        print("⚠ 评测集自报计数与实测不一致（评测集已过期）：")
        for d in drift:
            print("   - %s" % d)
        print("总退出码 1：计数对不上，评测集该更新了。")
        return 1
    print("总退出码 0：两侧逐条对齐，无问题（verdict 全部来自本次实测）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
