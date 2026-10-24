#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_vol2_into_two.py —— 卷二拆两册（V2S-M2，2026-10-22）。

册一（axiscope）chapters-vol2a/：9 章
  ch01 审计者姿态（搬）      ch02 证据等级（搬）        ch03 引进纪律（搬）
  ch04 契约七层与验证门控（新） ch05 真实数据打断契约（搬，自旧 ch06）
  ch06 厂商方言与上下文契约（新） ch07 没有真机时（自新）
  ch08 署名与脱敏（搬，自旧 ch07） ch09 文档即代码（搬，自旧 ch08）
册二（trae_factory）chapters-vol2b/：4 章
  ch01 代码工厂（搬，自旧 ch04） ch02 真值链（搬，自旧 ch05）
  ch03 手册进知识库（新）         ch04 双仓收尾实录（搬，自旧 ch09）

搬章同时重编章内 §编号（§6.x → §5.x 等）：本书体例是 §<章号>.<节号>，
章号变了，节号前缀必须跟着变，否则书内指针全部失效。
只改形如 §<旧章号> 或 §<旧章号>.<节> 的**本册内自指**；"卷一 §4.1"这类外部引用不动
（卷一不动，且其章号不在重编映射内）。
"""
import os
import re
import subprocess
import sys

REPO = r"%WORKSPACE%\forensics-learning-book"
OLD = "chapters-vol2"

# (旧文件名, 新目录, 新文件名, 旧章号, 新章号)
MOVES = [
    ("ch01-审计者姿态.md", "chapters-vol2a", "ch01-审计者姿态.md", "1", "1"),
    ("ch02-证据等级.md", "chapters-vol2a", "ch02-证据等级.md", "2", "2"),
    ("ch03-引进纪律.md", "chapters-vol2a", "ch03-引进纪律.md", "3", "3"),
    ("ch06-真实数据打断契约.md", "chapters-vol2a", "ch05-真实数据打断契约.md", "6", "5"),
    ("ch07-署名与脱敏.md", "chapters-vol2a", "ch08-署名与脱敏.md", "7", "8"),
    ("ch08-文档即代码.md", "chapters-vol2a", "ch09-文档即代码.md", "8", "9"),
    ("ch04-代码工厂.md", "chapters-vol2b", "ch01-代码工厂.md", "4", "1"),
    ("ch05-真值链.md", "chapters-vol2b", "ch02-真值链.md", "5", "2"),
    ("ch09-双仓收尾实录.md", "chapters-vol2b", "ch04-双仓收尾实录.md", "9", "4"),
]


def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True,
                          encoding="utf-8")


def main():
    for d in ("chapters-vol2a", "chapters-vol2b"):
        os.makedirs(os.path.join(REPO, d), exist_ok=True)
    for src, newdir, newname, oldno, newno in MOVES:
        srcp = os.path.join(REPO, OLD, src)
        dstp = os.path.join(REPO, newdir, newname)
        if not os.path.isfile(srcp):
            print(f"[MISSING] {src}")
            sys.exit(1)
        r = git("mv", f"{OLD}/{src}", f"{newdir}/{newname}")
        if r.returncode != 0:
            print(f"[GIT-MV FAILED] {src}: {r.stderr.strip()}")
            sys.exit(1)
        text = open(dstp, encoding="utf-8").read()
        if oldno != newno:
            # §6.3 → §5.3；§6 → §5；不动 §60 / §6.3.1 之外的误伤（§6.3.1 会变成 §5.3.1 ✓）
            pat = re.compile(r"§" + re.escape(oldno) + r"(?![0-9])")
            text, n = pat.subn("§" + newno, text)
            print(f"  {src} → {newdir}/{newname}：§{oldno}→§{newno} 重编 {n} 处")
        open(dstp, "w", encoding="utf-8", newline="\n").write(text)
    # 旧目录若已空则移除
    if os.path.isdir(os.path.join(REPO, OLD)) and not os.listdir(os.path.join(REPO, OLD)):
        os.rmdir(os.path.join(REPO, OLD))
        print("旧目录 chapters-vol2/ 已空，移除")
    print("\n搬章完成。当前册一/册二章表：")
    for d in ("chapters-vol2a", "chapters-vol2b"):
        print(f"  [{d}]")
        for f in sorted(os.listdir(os.path.join(REPO, d))):
            n = len(open(os.path.join(REPO, d, f), encoding="utf-8").read().splitlines())
            print(f"    {f}  ({n} 行)")


if __name__ == "__main__":
    main()
