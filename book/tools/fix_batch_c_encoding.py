#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""fix_batch_c_encoding.py —— 批 C 第 5 项：子进程 stdout 编码错位（公开仓 CI 必须绿）。

症状：pytest 里捕获子进程 stdout 的用例失败，而**同一条命令手动跑是绿的**。
原因：子进程按 Windows 控制台代码页（GBK/CP936）输出中文，父进程按 UTF-8 解码 → 乱码 →
断言里的正则（"quote 反查：(\d+)/(\d+) 通过"）匹配不上。
证据：干净 HEAD 基线同样 2 failed，且子进程 stdout 原始字节是 `\xb7\xb4\xb2\xe9`（GBK 的"反查"）。

处置：**沿用本仓已有的写法**（7 处捕获点已经这么干：env=dict(os.environ, PYTHONIOENCODING="utf-8")），
把漏掉的 4 处补齐——不改脚本行为、不改断言口径，只修编码通道 ✓。
"""
import io
import sys

MC = r"%WORKSPACE%\mcopilot"

FIXES = [
    (r"tests\test_protocol_modbus.py",
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_modbus_quotes.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=240, cwd=str(ROOT))''',
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_modbus_quotes.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       timeout=240, cwd=str(ROOT))''', 1),
    (r"tests\test_protocol_modbus.py",
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_modbus.py")],''',
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_modbus.py")],
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),''', 1),
    (r"tests\test_protocol_slmp.py",
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_slmp.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=180, cwd=str(ROOT))''',
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_slmp.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       timeout=180, cwd=str(ROOT))''', 1),
    (r"tests\test_protocol_slmp.py",
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_slmp.py")],''',
     '''    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_slmp.py")],
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),''', 1),
    # 这两个测试文件原本没 import os
    (r"tests\test_protocol_modbus.py",
     "import json\nimport re\nimport subprocess\nimport sys\n",
     "import json\nimport os\nimport re\nimport subprocess\nimport sys\n", 1),
    (r"tests\test_protocol_slmp.py",
     "import hashlib\nimport json\nimport re\nimport subprocess\nimport sys\n",
     "import hashlib\nimport json\nimport os\nimport re\nimport subprocess\nimport sys\n", 1),
]


def main():
    cache = {}
    applied, failed = 0, []
    for rel, old, new, cnt in FIXES:
        path = MC + "\\" + rel
        if path not in cache:
            cache[path] = io.open(path, encoding="utf-8", newline="").read()
        txt = cache[path]
        eol = "\r\n" if "\r\n" in txt else "\n"
        old_e, new_e = old.replace("\n", eol), new.replace("\n", eol)
        got = txt.count(old_e)
        if got != cnt:
            failed.append((rel, old[:60], got, cnt))
            continue
        cache[path] = txt.replace(old_e, new_e)
        applied += 1
    if failed:
        print("✗ 有替换未达期望命中数，未写盘：")
        for rel, old, got, cnt in failed:
            print(f"    {rel}  期望 {cnt} 实得 {got}  ← {old}")
        sys.exit(1)
    for path, txt in cache.items():
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
        print(f"  ✓ {path[len(MC)+1:]}")
    print(f"\n共 {applied} 处落盘（{len(cache)} 个文件）")


if __name__ == "__main__":
    main()
