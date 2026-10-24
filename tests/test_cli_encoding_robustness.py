# -*- coding: utf-8 -*-
"""CLI 脚本在**非 UTF-8 控制台**下不许崩。

2026-10-24 在 GitHub Actions runner 上查出来的：那边控制台编码是 **cp1252**，
本机是 UTF-8。这些脚本要往 stdout 打中文（锚点名、SKIP 理由、裁剪件核验结果……），
`print` 遇到不能编码的字符就抛 `UnicodeEncodeError` ——
**脚本崩在打印上，而不是给出判定**。

崩在打印上有三重坏处：
  ① 门禁"跑了"但没给结论，读日志的人只看到一段 traceback；
  ② 退出码非 0 ⇒ CI 变红，而红的原因**根本不是被测对象坏了**；
  ③ 本机绿、runner 红 —— 又是那种最坏的"作者机器绿、读者机器红"。

所以本测试把 runner 的条件**在本地复现**：用 `PYTHONIOENCODING=cp1252` 跑每一支
会被 CI 调用的脚本，要求**stderr 里不许出现 UnicodeEncodeError**。

判据为什么是"stderr 里不许出现 UnicodeEncodeError"而不是"退出码必须是 0"：
  · 退出码是各脚本自己的语义（有的门禁本来就会红），不该由这条测试断言；
  · 编码崩掉的**症状**是那条 traceback，盯住症状更准。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 会被 CI 调用的、且**要打中文**的脚本
CI_SCRIPTS = [
    "scripts/verify_bilingual_parity.py",
    "scripts/verify_doc_refs.py",
    "scripts/gate_anchors.py",
    "book/tools/check_doc_refs_heads.py",
    "book/tools/verify_crops_verbatim.py",
    "book/tools/check_vol2s_structure.py",
    "book/tools/verify_book_numbers.py",
    "book/tools/scan_absolute_paths.py",
    "book/tools/audit_vol2_coords.py",
]


def _run(rel: str, encoding: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(ROOT / rel)],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )


@pytest.mark.parametrize("rel", CI_SCRIPTS)
def test_非utf8控制台下不许崩在打印上(rel):
    """cp1252 控制台（= GitHub Actions runner 的实况）下不许 UnicodeEncodeError。"""
    p = _run(rel, "cp1252")
    blob = (p.stdout or "") + (p.stderr or "")
    assert "UnicodeEncodeError" not in blob, (
        f"{rel} 在 cp1252 控制台下崩在打印上（UnicodeEncodeError）——\n"
        f"处置：脚本里加 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`\n"
        f"（本仓既有做法见 scripts/verify_doc_refs.py）\n"
        f"stderr 尾部：\n{(p.stderr or '')[-800:]}"
    )


# 退出码一致性只对**跑得快**的脚本断言：两支慢的（锚点门禁要联网查 URL、
# 坐标审计要解 272 条坐标）各要 8–25 秒，跑两遍光它们就吃掉一分钟。
# 它们的编码暴露面与快脚本完全一样（同样要打中文），
# 上面那条 UnicodeEncodeError 检查已经把那条路盖住了。
SLOW = {"scripts/gate_anchors.py", "book/tools/audit_vol2_coords.py"}
FAST = [s for s in CI_SCRIPTS if s not in SLOW]


@pytest.mark.parametrize("rel", FAST)
def test_两种控制台编码下退出码一致(rel):
    """同一支脚本，控制台编码不同**不该改变它的判定**。"""
    u = _run(rel, "utf-8")
    c = _run(rel, "cp1252")
    assert u.returncode == c.returncode, (
        f"{rel}：utf-8 下退出码 {u.returncode}，cp1252 下 {c.returncode} —— "
        f"控制台编码不该影响判定"
    )
