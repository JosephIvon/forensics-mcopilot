#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_exe_rebuild.py —— 判定 mcopilot 模板 exe 的"重建 vs 元数据抖动"（2026-10-22）。

口径：exe 与其 .cs 源码最后一次同在 c079336 提交 ⇒ 工作树那份是同源重建。
本脚本比两版的可打印字符串集合与 PE 头时间戳，判断是否只有构建元数据不同。
"""
import hashlib
import io
import os
import re
import subprocess
import struct

REPO = r"%WORKSPACE%\mcopilot"
REL = "knowledge/templates/protocol/ModbusRtuContractRunner.exe"
WT = os.path.join(REPO, REL.replace("/", os.sep))
TMP = os.path.join(os.environ["TEMP"], "head_runner.exe")

with open(TMP, "wb") as f:
    p = subprocess.run(["git", "-C", REPO, "show", f"HEAD:{REL}"], capture_output=True)
    f.write(p.stdout)

STR = re.compile(rb"[ -~]{6,}")


def strings(path):
    b = io.open(path, "rb").read()
    return sorted({s.decode("latin-1") for s in STR.findall(b)})


def pe_info(path):
    b = io.open(path, "rb").read()
    if b[:2] != b"MZ":
        return "非 PE"
    off = struct.unpack_from("<I", b, 0x3C)[0]
    if b[off:off + 4] != b"PE\0\0":
        return "非 PE"
    ts = struct.unpack_from("<I", b, off + 8)[0]
    machine = struct.unpack_from("<H", b, off + 4)[0]
    nsec = struct.unpack_from("<H", b, off + 6)[0]
    opt_size = struct.unpack_from("<H", b, off + 20)[0]
    sec_off = off + 24 + opt_size
    secs = []
    for i in range(nsec):
        o = sec_off + i * 40
        name = b[o:o + 8].rstrip(b"\0").decode("latin-1")
        vsize = struct.unpack_from("<I", b, o + 8)[0]
        secs.append(f"{name}:{vsize}")
    return f"machine={machine} sections={nsec} [{', '.join(secs)}] PE时间戳={ts}"


for label, path in (("HEAD 版", TMP), ("工作树版", WT)):
    h = hashlib.sha256(io.open(path, "rb").read()).hexdigest()
    print(f"  {label}: sha256={h[:16]}… 大小={os.path.getsize(path)}")
    print(f"            {pe_info(path)}")

a, b = strings(TMP), strings(WT)
only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
print(f"\n  字符串集合：HEAD {len(a)} 条 / 工作树 {len(b)} 条 ｜ 仅 HEAD 有 {len(only_a)} / 仅工作树有 {len(only_b)}")
for s in (only_a + only_b)[:10]:
    print(f"    差异串：{s[:110]}")
if not only_a and not only_b:
    print("  → 字符串集合完全一致：差异仅来自 PE 时间戳等构建元数据（**同源重建，非代码变更**）")
else:
    print("  → 存在字符串级差异：**不是**纯元数据抖动，需按代码变更对待")
