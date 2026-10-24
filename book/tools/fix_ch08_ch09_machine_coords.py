#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ch08_ch09_machine_coords.py —— 册一 ch08/ch09 旧章坐标机判化（2026-10-22）。

对应 OUTLINE-VOL2S.md §十一 欠账第 1 条（作者 2026-10-22 指令"旧章坐标机判化"）。
成因：这两章（卷二旧章、已过审关闭）的正文与尾注里有 40 处"（`:786`）"式裸行号——
文件名单独出现、行号成组，机器判不了，等于这些坐标没被核过。
处置：每处裸行号补上自己的文件（KB 文件用该章既有别名体例，其余用相对路径），
尾注整块改写成 `路径:行号` 清单。
纪律：替换前验命中数，为 0 或多于 1 即报错退出。
"""
import io
import os
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
CH08 = os.path.join(REPO, "chapters-vol2a", "ch08-署名与脱敏.md")
CH09 = os.path.join(REPO, "chapters-vol2a", "ch09-文档即代码.md")

SIDE = "data/raw/Export10_244531.csv.source.txt"
PROBE = "data/probe_doc_line_refs.py"

CH08_PAIRS = [
    ("§六（`:780`–`:818`）", "§六（`KB2:780-818`）"),
    ("规则表（`:786`–`:795`）", "规则表（`KB2:786-795`）"),
    ("**均**替换\"（`:789`）", "**均**替换\"（`KB2:789`）"),
    ("redaction 自检行（`:814`–`:815`）", "redaction 自检行（`KB2:814-815`）"),
    ("（`:812`–`:813`）——两个数字不是一回事", "（`KB2:812-813`）——两个数字不是一回事"),
    ("侧车就地纠偏（`:6` 加纠偏注、`:14`\n  notes 记脱敏与哈希）",
     f"侧车就地纠偏（`{SIDE}:6` 加纠偏注、\n  `{SIDE}:14` notes 记脱敏与哈希）"),
    ("故意不填的空**（`:51`–`:53`）", "故意不填的空**（`README.md:51-53`）"),
    ("Reichenbach**\"（`:65`–`:67`）", "Reichenbach**\"（`README.md:65-67`）"),
    ("§6.2 署名块（`:797`–`:803`）", "§6.2 署名块（`KB2:797-803`）"),
]

OLD_TAIL = """*本章事实性句子坐标：`axiscope@b95ffb2 docs/kb/KB2-waveform-formats.md`（`:786`–`:795`
字段规则表、`:797`–`:804` 署名与"绝不清除"纪律、`:806`–`:817` 发布门与门判据、
`:527`/`:561` 样本卡"发布前必做"行）、`data/redact_pii_20261022.py`（执行记录与
头注）、`data/raw/Export10_244531.csv.source.txt`（`:6` 标题纠偏、`:9` 导出时刻
令牌化、`:14` notes 脱敏与 md5 前后对照）、`data/raw/DD_head.csv.source.txt`
（`:9` 墙钟、`:14` 脱敏完成记录）、`data/probe_pii.py`（计数口径说明段）、
`README.md`（`:51`–`:53` 待补段、`:74`–`:81` 脱敏门禁段、`:85`–`:86` 归属纪律、
`:88`–`:99` 复用标注表、`:101`–`:103` 引用纪律）、`docs/kb/KB7-dataset-da-rus-cat.md`
（`:10` 标题、`:13` 许可、`:17` 署名要求）；§8.5、§8.6 为作者亲历叙事。*"""

NEW_TAIL = """*本章事实性句子坐标：`axiscope@b95ffb2` —
`docs/kb/KB2-waveform-formats.md:786-795`（字段规则表）、
`docs/kb/KB2-waveform-formats.md:797-804`（署名与"绝不清除"纪律）、
`docs/kb/KB2-waveform-formats.md:806-817`（发布门与门判据）、
`docs/kb/KB2-waveform-formats.md:527`/`docs/kb/KB2-waveform-formats.md:561`
（样本卡"发布前必做"行）、`data/redact_pii_20261022.py`（执行记录与头注）、
`data/raw/Export10_244531.csv.source.txt:6`（标题纠偏）、
`data/raw/Export10_244531.csv.source.txt:9`（导出时刻令牌化）、
`data/raw/Export10_244531.csv.source.txt:14`（notes 脱敏与 md5 前后对照）、
`data/raw/DD_head.csv.source.txt:9`（墙钟）、
`data/raw/DD_head.csv.source.txt:14`（脱敏完成记录）、`data/probe_pii.py`（计数口径说明段）、
`README.md:51-53`（待补段）、`README.md:74-81`（脱敏门禁段）、`README.md:85-86`（归属纪律）、
`README.md:88-99`（复用标注表）、`README.md:101-103`（引用纪律）、
`docs/kb/KB7-dataset-da-rus-cat.md:10`（标题）、
`docs/kb/KB7-dataset-da-rus-cat.md:13`（许可）、
`docs/kb/KB7-dataset-da-rus-cat.md:17`（署名要求）；§8.5、§8.6 为作者亲历叙事。*"""

CH09_PAIRS = [
    ("不在本仓可核范围（`:9-10`）", f"不在本仓可核范围（`{PROBE}:9-10`）"),
    ("制造机**\"（`:16`）", f"制造机**\"（`{PROBE}:16`）"),
    ("负责（`:18-20`）", f"负责（`{PROBE}:18-20`）"),
    ("反例写在 `:21-22`——", f"反例写在 `{PROBE}:21-22`——"),
    ("`--quote-backtick --multiline`（`:46`）", f"`--quote-backtick --multiline`（`{PROBE}:46`）"),
    ("等于没有检查**\"（`:303`）", "等于没有检查**\"（`KB0-conventions.md:303`）"),
    ("改判、不计病例（`:9-10`）", f"改判、不计病例（`{PROBE}:9-10`）"),
    ("`:768`、`:761` 这类续写", "`KB2:768`、`KB2:761` 这类续写"),
    ("默认保守不判（`:35-36`）", f"默认保守不判（`{PROBE}:35-36`）"),
    ("记 `no-quote`，不判（`:14`）", f"记 `no-quote`，不判（`{PROBE}:14`）"),
    ("**全部记 `no-quote`**（`:39-40`）", f"**全部记 `no-quote`**（`{PROBE}:39-40`）"),
    ("跳过（`:37-38`）", f"跳过（`{PROBE}:37-38`）"),
    ("报不出\"行号错\"（`:33-34`）", f"报不出\"行号错\"（`{PROBE}:33-34`）"),
    ("**口径混用**（`:563-565`，A-108）", "**口径混用**（`KB0-conventions.md:563-565`，A-108）"),
    ("**自指反例**（`:302`，A-104）", "**自指反例**（`KB0-conventions.md:302`，A-104）"),
]

fail = 0
for path, pairs in ((CH08, CH08_PAIRS + [(OLD_TAIL, NEW_TAIL)]), (CH09, CH09_PAIRS)):
    t = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        n = t.count(old)
        if n != 1:
            print(f"[SKIP 命中 {n} 次] {os.path.basename(path)}: {old[:52]!r}")
            fail += 1
            continue
        t = t.replace(old, new)
        print(f"[OK] {os.path.basename(path)}: {old[:40]!r}")
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
print("失败条数：", fail)
sys.exit(1 if fail else 0)
