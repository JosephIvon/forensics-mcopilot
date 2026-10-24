#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""断链门禁的**检测力**自测（2026-10-25 独立第三方评审后补）。

背景
----
评审实测：`book/tools/check_doc_refs_heads.py` 的分类分支是
    elif MISSING_REPOS:  UNDECIDED  # 缺仓 → 不可判定
    else:                TRUE_GAPS  # 全仓都找不到 → 真断链
    sys.exit(1 if TRUE_GAPS else 0)
CI 只 checkout 本仓 → 兄弟仓必然不在位 → **TRUE_GAPS 结构性不可达** →
exit 1 永远不发生 → **这道门的检测力只存在于本地，从不存在于 CI**。

修法：加一条独立判死条件——**历史残留** ✓
    这条路径在**在位仓的 git 历史里存在过**（改名/删除前它在那儿），
    现在 HEAD 与工作树都没有 → 与兄弟仓在不在位无关 ✓。
    这正是评审点名的「本仓改名/删除文件后残留的引用」✓。

本文件用**注入**证明这道门现在会红 ✓：
造一个**忠实复刻真实布局**的合成仓（外层 git 仓 + 嵌套的 book/ 目录 ✓）→
提交 book/docs/gone.md → 删掉它 → 让 book/docs/ref.md 引用它 →
把两个兄弟仓指到不存在的目录（复刻 CI 场景 ✓）→ 门禁必须判它死 ✓✓

（没有注入自测的门禁，绿灯只能说明「没崩」✓。）
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "book", "tools", "check_doc_refs_heads.py")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


@pytest.fixture()
def layout_with_residue(tmp_path):
    """合成布局：outer/ 是 git 仓，outer/book/ 是嵌套的书目录（无自己的 .git）。

    book/docs/gone.md 提交过 → 现在被删 → book/docs/ref.md 仍引用着它。
    """
    outer = tmp_path / "outer"
    book = outer / "book"
    (book / "docs").mkdir(parents=True)
    (outer / "src" / "mcopilot").mkdir(parents=True)
    (outer / "src" / "mcopilot" / "__init__.py").write_text("", encoding="utf-8")
    _git(str(outer), "init", "-q")
    _git(str(outer), "config", "user.email", "t@example.com")
    _git(str(outer), "config", "user.name", "test")
    (book / "docs" / "gone.md").write_text("# 曾经存在过\n", encoding="utf-8")
    _git(str(outer), "add", "-A")
    _git(str(outer), "commit", "-q", "-m", "曾有 book/docs/gone.md")
    (book / "docs" / "gone.md").unlink()      # 删掉
    # 关键：**连 index 也要删掉并提交** ✓
    # 只删工作树不删 index 的话，`git ls-files` 仍会列出它 ✓
    # → 门禁看到「HEAD 与工作树都有」（其实只是索引里有）→ 不判断链 ✓
    #   —— 那样测的就不是「历史残留」，是「还在仓里」✓。
    _git(str(outer), "add", "-A")
    _git(str(outer), "commit", "-q", "-m", "删掉 book/docs/gone.md")
    # 措辞注意：这一行**不能**含「不在仓/删除/缺失」这类词——
    # 门禁会把明说路径不存在的引用判成「教材式举反例」放掉（那是刻意的 ✓），
    # 那就不是断链了。本测试要验的是**沉默的残留引用** ✓。
    (book / "docs" / "ref.md").write_text(
        "该机制的说明见 docs/gone.md 一节。\n", encoding="utf-8")
    return outer, book


def _run_tool(outer, book, missing_root):
    # 兄弟仓要「存在但空」才算**不在位** ✓：
    # _repo() 认环境变量时要求目录存在 ✓，指到不存在的目录会**回退到默认**
    # （默认位置在开发机上通常是在位的 ✓）→ 缺仓场景就复现不出来了 ✓。
    for name in ("axiscope", "trae_factory"):
        (missing_root / name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "MCOPILOT_REPO": str(outer),
        "BOOK_REPO": str(book),
        "AXISCOPE_REPO": str(missing_root / "axiscope"),
        "TRAE_REPO": str(missing_root / "trae_factory"),
        "PYTHONIOENCODING": "utf-8",
    })
    return subprocess.run([sys.executable, TOOL], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=600)


def test_历史残留的断链在缺仓场景下也必须判死(layout_with_residue, tmp_path):
    """CI 场景（兄弟仓不在位）下，本仓改名/删除文件后残留的引用必须判死。"""
    outer, book = layout_with_residue
    p = _run_tool(outer, book, tmp_path / "not_here")
    out = (p.stdout or "") + (p.stderr or "")
    assert "docs/gone.md" in out, \
        "门禁必须把这条历史残留认出来（输出里没有它）\n%s" % out[-2000:]
    assert p.returncode == 1, "认出来就必须 exit 1（现在 exit %d）" % p.returncode


def test_真实仓当前没有真断链():
    """阳性对照：真实仓现在不该有真断链（这条修法不能给现仓造出假断链）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, TOOL], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, "真实仓不该被判死链（exit %d）\n%s" % (p.returncode, out[-2000:])
