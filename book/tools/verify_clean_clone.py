#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_clean_clone.py —— 发布硬门槛：**干净克隆**能不能跑（2026-10-23 新增）。

为什么要有这道门 ✓
------------------
本机工作树绿 ≠ 公开后能用 ✓。2026-10-23 发布前实测，本机全绿，
但**本地路径克隆**（= GitHub 将提供的同一份内容 ✓）里挖出四个真缺陷 ✓：
  ① `.gitignore` 的 `*.log` 把三个测试夹具扫掉 → 克隆里 14 个测试因缺夹具而红 ✓
  ② 原始数据按 A-131 口径不入库 → axiscope 87 个测试函数报 FileNotFoundError ✓
  ③ mcopilot 的 G5 与 G7/G12 缺件口径不一致 → G5 把「原件不在位」判成失败 ✓
  ④ 负向门禁 N1 在缺件时**假绿**：拒绝的是「规范文本缺失」，
     却记成「编造引文被拒」的检测力已证明 ✓
四个都是**只有换一副眼睛才看得见**的缺陷 ✓ → 所以固化成门禁 ✓。

它做什么 ✓
----------
把三个仓克隆到临时目录 ✓（干净、无未跟踪文件 ✓），
按各自 `.github/workflows/` 的步骤**逐条复演** ✓，
任何一步非零退出就红 ✓，并在最后把 **SKIP 的条数与原因**原样带出来 ✓
（跳过 ≠ 通过 ✓）。

用法 ✓
------
    python tools/verify_clean_clone.py            # 三仓全验
    python tools/verify_clean_clone.py mcopilot   # 只验一个
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from _localenv import expand

BOOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = expand(r"%WORKSPACE%")

PY = sys.executable
if not os.path.isfile(PY):
    PY = sys.executable

# 每个仓：(目录, [(步骤名, 可执行文件, 参数...)] )
STEPS = {
    "mcopilot": [
        ("pytest 全量", PY, ["-X", "utf8", "-m", "pytest", "-q"]),
        ("门禁 G1–G12", "pwsh", ["-NoProfile", "-File", r"scripts\gate_protocol.ps1"]),
        ("真实语料门禁", "pwsh", ["-NoProfile", "-File", r"scripts\gate_corpus.ps1"]),
        ("外部真值锚点门禁", PY, ["-X", "utf8", r"scripts\gate_anchors.py"]),
        ("文档一致性门禁", "pwsh", ["-NoProfile", "-File", r"scripts\gate_docsync.ps1"]),
        ("负向门禁", "pwsh", ["-NoProfile", "-File", r"scripts\gate_negative.ps1"]),
        ("故障注入农场", "pwsh", ["-NoProfile", "-File", r"scripts\gate_farm.ps1"]),
        ("接入闭环", "pwsh", ["-NoProfile", "-File", r"scripts\gate_onboard.ps1"]),
    ],
    "axiscope": [
        ("pytest 全量", PY, ["-X", "utf8", "-m", "pytest", "-q"]),
        ("脱敏自检", PY, ["-X", "utf8", r"data\probe_pii.py"]),
    ],
    "trae_factory": [
        ("全品牌套件再生", "node", ["test_gen.js", "all"]),
        ("单品牌再生", "node", ["test_gen.js", "gts"]),
        ("单文件 concat", "node", ["concat.js"]),
    ],
}

ENVS = {
    "mcopilot": {"PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8"},
    "axiscope": {"PYTHONIOENCODING": "utf-8"},
    "trae_factory": {},
}


def run(cmd, cwd, env):
    e = dict(os.environ)
    e.update(env)
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 99, "超时（1800s）"
    except OSError as exc:
        return 98, "无法执行：%s" % exc


def main(argv):
    only = argv[1:] or list(STEPS)
    tmp = tempfile.mkdtemp(prefix="cleanclone_")
    failures = []
    try:
        # ① 先把要验的仓**全部克隆出来**，再逐仓跑步骤。
        #    顺序不能反：mcopilot 的接缝 3 对照（门禁 G13）要靠同级兄弟目录
        #    ../trae_factory 才能真跑——边克隆边跑的话，跑 mcopilot 时兄弟仓还没到，
        #    对照只能记 SKIP。读者是三个仓一起克隆的，这里也该照那个场景来。
        clones = {}
        for repo in only:
            src = os.path.join(WS, repo)
            dst = os.path.join(tmp, repo)
            print("=" * 78)
            print("【%s】干净克隆复验" % repo)
            print("=" * 78)
            rc, out = run(["git", "clone", "--quiet", src, dst], os.path.dirname(dst), {})
            if rc != 0:
                print("  ✗ 克隆失败（退出码 %d）" % rc)
                failures.append((repo, "克隆", "退出码 %d" % rc))
                continue
            clones[repo] = dst

        # ② 再逐仓跑它的 CI 步骤（只测已提交内容：测的是"读者拿到的"）
        for repo in only:
            dst = clones.get(repo)
            if dst is None:
                continue
            for name, exe, args in STEPS[repo]:
                rc, out = run([exe] + args, dst, ENVS.get(repo, {}))
                tail = [ln for ln in out.splitlines() if ln.strip()][-1:] if out.strip() else []
                mark = "✓" if rc == 0 else "✗"
                print("  %s %-22s 退出码 %-3s %s" % (mark, name, rc,
                                                    (tail[0][:90] if tail else "")))
                if rc != 0:
                    failures.append((repo, name, "退出码 %d" % rc))
                # 抓 SKIP 条数与原因：跳过 ≠ 通过，必须让人看见
                for ln in out.splitlines():
                    if "SKIP" in ln and ("不可自动复核" in ln or "没跑" in ln):
                        print("      · %s" % ln.strip()[:130])
            # trae_factory：单文件与 gen/ 同源（concat 后不得有差异）
            if repo == "trae_factory":
                rc, _ = run(["git", "diff", "--quiet", "--", "上位机代码工厂.html"], dst, {})
                print("  %s 单文件与 gen/ 同源" % ("✓" if rc == 0 else "✗"))
                if rc != 0:
                    failures.append((repo, "单文件同源", "有差异"))
                # 产物里不得出现本机绝对路径
                rc, out = run(["git", "grep", "-InE", r"[A-Za-z]:\\", "--", "out"], dst, {})
                if rc == 0 and out.strip():
                    print("  ✗ 产物里出现本机绝对路径")
                    failures.append((repo, "产物绝对路径", "有命中"))
                else:
                    print("  ✓ 产物绝对路径 0 处")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    if failures:
        print("【结论】干净克隆复验**未通过**（%d 项）——发布前必须清偿：" % len(failures))
        for repo, name, why in failures:
            print("  ✗ [%s] %s：%s" % (repo, name, why))
        print("=" * 78)
        return 1
    print("【结论】三仓的干净克隆全部通过（读者克隆下来能跑）✓")
    print("  注意：SKIP 不算通过——上面标出的 SKIP 是「当前不可自动复核」的范围 ✓")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
