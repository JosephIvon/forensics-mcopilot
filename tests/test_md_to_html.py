#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付形态转换的**行为**断言（评审 P2-7）。

背景
----
`src/mcopilot/core/util.py` 的 `md_to_html` 是 Markdown → HTML 转换器 ✓
（表格 / 代码块 / 图片 / 内联 / `_esc` 转义 ✓），
`Report.write()` **每次**都调用它产出 HTML 交付物 ✓ —— 但它此前**零测试** ✓。

评审点名的风险 ✓
--------------
`<`/`&` 未转义会**直接损坏交付物** ✓，
而 `.md` 侧一切正常 ✓ → **两个形态不一致却没人发现** ✓✓。

口径
----
这里断言的不是「HTML 好看」✓，而是**两种交付形态对同一份 Markdown 的解释一致** ✓：
`a < b & c` 在 `.md` 里是字面量 ✓ → 在 `.html` 里必须也是字面量（转义形态）✓，
不能变成标签、也不能被吞掉 ✓。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcopilot.core.util import md_to_html  # noqa: E402


def test_表格必须转成table_th_td():
    md = "\n".join([
        "| 项 | 值 |",
        "|---|---|",
        "| 回零模式 | 0~12 |",
    ])
    html = md_to_html(md)
    assert "<table>" in html and "</table>" in html
    assert "<th>项</th><th>值</th>" in html, "表头没转成 <th>"
    assert "<td>回零模式</td><td>0~12</td>" in html, "表体没转成 <td>"
    # 分隔行 |---|---| 必须被吃掉，不能当数据行
    assert "---" not in html.split("<table>")[1].split("</table>")[0]


def test_代码块内容必须原样保留且以pre包裹():
    md = "\n".join([
        "```python",
        "if a < b and c & d:",
        "    pass",
        "```",
    ])
    html = md_to_html(md)
    assert "<pre>" in html and "</pre>" in html
    # 代码块里的 < 和 & 必须在源码层面转义，否则浏览器会把它们当标签解析
    assert "a &lt; b" in html and "c &amp; d" in html
    assert "if a < b" not in html, "代码块里的 < 未转义 → 交付物会被浏览器吃坏"


def test_正文里的尖括号与和号必须转义():
    """`a < b & c` —— 这是评审点名的那个例子 ✓。"""
    html = md_to_html("比值满足 a < b & c 时报警。")
    assert "a &lt; b &amp; c" in html, "正文里的 < / & 未转义"
    assert "a < b & c" not in html


def test_行内代码保留反引号语义且内容转义():
    html = md_to_html("见 `x<y` 这一处。")
    assert "<code>x&lt;y</code>" in html, "行内代码没转成 <code> 或内容未转义"


def test_标题与粗体的基本转换():
    html = md_to_html("# 一级\n\n这是 **重点**。")
    assert "<h1>一级</h1>" in html
    assert "<strong>重点</strong>" in html


def test_标题参数也要转义():
    """报告标题是外部输入（单号/设备名）→ 必须转义 ✓。"""
    html = md_to_html("正文", title="A<B&C")
    assert "A&lt;B&amp;C" in html
    assert "<title>A<B&C</title>" not in html


def test_空正文不得崩():
    html = md_to_html("")
    assert "<!doctype html>" in html
    assert "</body></html>" in html
