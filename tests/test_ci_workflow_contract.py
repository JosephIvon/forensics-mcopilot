#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 工作流的**退出码契约**（评审 P0-1 的回归测试）。

背景
----
评审 P0-1 实测：GitHub Actions 的 pwsh step 只把**最后一条**命令的 `$LASTEXITCODE`
带出 step ✓。于是原来那个「六条门禁写在同一个 `run: |` 块里」的 step ✓ ——
第 1 条 exit 3、第 4 条 exit 7，**step 照样 exit 0** ✓✓。

后果（评审原话的意思）：这一条 step 曾经吞掉 6 条门禁里 5 条的失败信号 ✓ ——
README 中英不同步、文档行号引用失效、书锚点断链、裁剪件被改、书结构违规、
书里的数字对不上，任意一类发生，**CI 全绿** ✓✓。

为什么这条只能靠**契约测试**守住
------------------------------
`$ErrorActionPreference` 管不了 native command ✓，
`$PSNativeCommandUseErrorActionPreference` 默认 `$false` ✓ ——
语言层面没有任何东西会替你检查 ✓。
也就是说：下次有人往同一个 `run: |` 里再串两条命令，
**只有本文件会红** ✓✓（pytest 跑在本机，与 CI 是否绿无关 ✓）。

代码口径（能 parse 的理由）
------------------------
本仓运行时零三方依赖 ✓ → 不引入 PyYAML ✓（CI 也不装它 ✓）→
`run:` 块是缩进固定的文本 ✓，按行解析足够且**可审计** ✓。
解析器本身带**阴性对照**：把评审给的旧形态喂给它，它必须报违规 ✓
（否则「解析器恒返回空」也会让本文件假绿 ✓）。
"""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "gates.yml")

# 会**自己产生退出码**的调用形态（行首出现即算一条命令）
_INVOKER = re.compile(
    r"^\s*(?:&\s*)?(?:python|py|pwsh|powershell|\./|\.\\|node|pip|csc|msbuild|dotnet)\b"
)
# 明确的「消费上一条退出码」写法
_CHECKED = re.compile(r"\$LASTEXITCODE|\$\?|exit \$|trap\b")


def _blocks(text: str) -> list[tuple[int, list[str]]]:
    """抽出所有 `run: |` 块 → [(起始行号, 块内命令行)]。"""
    lines = text.splitlines()
    out: list[tuple[int, list[str]]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)run:\s*\|[-+]?\s*$", lines[i])
        if not m:
            i += 1
            continue
        base = len(m.group(1))
        start = i + 1
        i += 1
        body: list[str] = []
        while i < len(lines):
            ln = lines[i]
            if ln.strip() and (len(ln) - len(ln.lstrip())) <= base:
                break
            body.append(ln)
            i += 1
        out.append((start, body))
    return out


def find_swallowed_blocks(text: str) -> list[dict]:
    """返回**会吞掉退出码**的块：块内 ≥2 条命令，且全块都没检查 `$LASTEXITCODE`。

    判定刻意保守 ✓：只要块里出现过 `$LASTEXITCODE`/`exit`/`trap` 就认为**有人管** ✓
    （逐条判的写法正是评审认可的那种 ✓）。误报的代价是多看一行注释 ✓；
    漏报的代价是**整条门禁失效且 CI 全绿** ✓✓ —— 两者不对称，所以宁严勿松 ✓。
    """
    bad = []
    for start, body in _blocks(text):
        cmds = [ln for ln in body
                if _INVOKER.match(ln) and not ln.strip().startswith("#")]
        if len(cmds) < 2:
            continue          # 单命令块：step 退出码就是它的退出码，天然安全 ✓
        joined = "\n".join(body)
        if _CHECKED.search(joined):
            continue          # 有人逐条判退出码 ✓
        bad.append({"line": start, "commands": [c.strip() for c in cmds]})
    return bad


# ------------------------------------------------------------------ 契约
def test_所有多命令run块都检查了退出码():
    """CI 里每个多命令块都必须自己判退出码 ✓ —— 否则失败会被 Actions 吞掉 ✓。"""
    text = io.open(WORKFLOW, encoding="utf-8").read()
    bad = find_swallowed_blocks(text)
    assert not bad, (
        "这些 run: 块里有多条命令却没人检查退出码 —— "
        "除最后一条外的失败都会被 CI 吞掉，step 照样绿：\n"
        + "\n".join("  第 %d 行起：%s" % (b["line"], b["commands"]) for b in bad))


def test_解析器自己必须抓得住评审给的旧形态():
    """**阴性对照**：拿 P0-1 的原始形态喂解析器 → 必须报违规 ✓。

    没有这条，`find_swallowed_blocks` 恒返回空也能让上一条测试假绿 ✓✓。
    """
    old_shape = """\
      - name: 文档与电子书同步门禁
        run: |
          python scripts/verify_bilingual_parity.py
          python scripts/verify_doc_refs.py
          python book/tools/check_doc_refs_heads.py
          python book/tools/verify_crops_verbatim.py
          python book/tools/check_vol2s_structure.py
          python book/tools/verify_book_numbers.py
"""
    bad = find_swallowed_blocks(old_shape)
    assert len(bad) == 1, "旧形态必须被判定为「吞退出码」，实际 %d 条" % len(bad)
    assert len(bad[0]["commands"]) == 6


def test_逐条判退出码的形态必须放行():
    """**阳性对照**：现役那种 `foreach + $LASTEXITCODE` 写法不得被判违规 ✓。"""
    good = """\
        run: |
          $failed = @()
          foreach ($s in @("a.py", "b.py")) {
            python $s
            if ($LASTEXITCODE -ne 0) { $failed += $s }
          }
          if ($failed.Count -gt 0) { exit 1 }
"""
    assert find_swallowed_blocks(good) == [], "逐条判退出码的写法不该被判违规"


def test_单命令块不需要检查():
    """单命令块的 step 退出码天然就是它的退出码 ✓ → 不要求写 `$LASTEXITCODE` ✓。"""
    one = """\
        run: |
          python -m pytest -q
"""
    assert find_swallowed_blocks(one) == []


# ------------------------------------------------------- P1-5 的一半（pypdf）
def test_CI必须装pypdf():
    """`pypdf` 是 G5 引文反查与 SLMP 抽取的**硬依赖** ✓。

    评审 P1-5：它既不在 `pyproject` 的任何 extra 里，也不在 CI 安装清单里 ✓
    → 有原件的机器上硬失败、CI 上永远 SKIP ✓ → 这条验证两头都没跑过 ✓✓。
    """
    text = io.open(WORKFLOW, encoding="utf-8").read()
    pip_lines = [ln for ln in text.splitlines()
                 if "pip install" in ln and not ln.strip().startswith("#")]
    assert pip_lines, "CI 里找不到 pip install 行"
    assert any("pypdf" in ln for ln in pip_lines), \
        "CI 的 pip install 里没有 pypdf（G5 引文反查会永远 SKIP）：%s" % pip_lines


def test_CI不得安装本包():
    """布局契约要求「从仓库根 import mcopilot 应当不成立」✓ → CI 也不能装本包 ✓。"""
    text = io.open(WORKFLOW, encoding="utf-8").read()
    pip_lines = [ln for ln in text.splitlines()
                 if "pip install" in ln and not ln.strip().startswith("#")]
    for ln in pip_lines:
        assert " -e " not in ln and "pip install ." not in ln, \
            "CI 装本包会让 tests/test_layout_contract.py 变红：%s" % ln
