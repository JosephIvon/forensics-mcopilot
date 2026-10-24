# -*- coding: utf-8 -*-
"""probe_scanner_gap.py —— 查清 scan_absolute_paths.py 为什么漏掉那 7 处。"""
import io
import re

S = r"%USERPROFILE%\.minimax\sessions\mvs_838bec01bb00476594f48711e6b172d0\workspace\mcopilot"
pats = {
    "家目录/用户名": re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"'<>|]+"),
    "本机工作区": re.compile(r"[A-Za-z]:\\workspace\\[^\\\s\"'<>|,;)]+"),
}
for name, p in pats.items():
    print(f"  {name} 命中: {bool(p.search(S))}")

src = io.open(r"%WORKSPACE%\forensics-learning-book\tools\scan_absolute_paths.py", encoding="utf-8").read()
print("\n== 扫描器里与文件选择/白名单有关的行 ==")
for i, line in enumerate(src.splitlines(), 1):
    if any(k in line for k in ("SKIP", "ALLOW", "suffix", "glob", "ls-files", "rglob", "EXTS", "SKIP_DIR")):
        print(f"  :{i} {line.strip()[:110]}")
