# -*- coding: utf-8 -*-
"""comm_log/1 现场通信日志校验器（零依赖，契约唯一裁判）。

契约唯一事实源：knowledge/contracts/comm_log_contract.json（schema comm_log/1，
axiscope C1 契约同款纪律）。本脚本逐条校验 JSONL 现场日志：

  · 文件级：UTF-8 可解码；自报 schema（如有）必须是 comm_log/1，不符整文件拒收；
  · 行级：必填/类型/枚举/取值域逐条对契约；不变式 I1-I6（流内 seq 单调、
    广播形态、异常归属、error 与 exception_code 互斥、other 必带 notes、时间合法）；
  · 输出 PASS/FAIL + 行号 + 违规摘要；**退出码 = 违规数**（0 = 全绿）；
    建议级（如广播/异常帧缺 frame_hex）只提示不计违规。

用法：
  python scripts/validate_comm_log.py <log.jsonl>          # 校验一个日志文件
  python scripts/validate_comm_log.py --selftest           # 内嵌 3 条样例自检（1 合法 2 非法）
可选：--contract <路径> 换契约文件（缺省即仓库契约，测试用）。

纪律：只报不修（R3）；带病日志不许进 eval_forensics（R2，那边自己也会再查一道）。
"""
from __future__ import annotations   # `Path | None` 注解在 3.9 上要靠它才不被运行期求值

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "knowledge" / "contracts" / "comm_log_contract.json"

SCHEMA_ID = "comm_log/1"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
RE_LNO = re.compile(r"^L(\d+):")

# 必填字段（契约 fields.required=true 的集合；device 展开 host_or_port）
REQUIRED = ("timestamp_utc", "seq", "channel", "direction", "unit_id",
            "function_code", "device")


def load_contract(path: Path | None = None) -> dict:
    p = Path(path) if path else CONTRACT
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA_ID:
        raise SystemExit(f"契约文件 {p} 的 schema 不是 {SCHEMA_ID}，拒载")
    return doc


def _bad_ts(s: str) -> bool:
    """格式对但日历不存在（02-30）也算非法。"""
    if not isinstance(s, str) or not TS_RE.match(s):
        return True
    try:
        datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return True
    return False


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def validate_records(records: list[dict], contract: dict) -> tuple[list[str], list[str]]:
    """逐条校验内存中的记录列表 → (violations, advisories)。

    violations/advisories 均为已带「L<行号>」前缀的摘要行；行号口径 =
    **非空行序号**（从 1 起，空行不占号），与 main 的整文件口径一致。
    """
    f = contract["fields"]
    violations: list[str] = []
    advisories: list[str] = []
    last_seq: dict[tuple[str, str], int] = {}

    for no, rec in enumerate(records, 1):
        L = f"L{no}"

        # 自报 schema：报了就必须报对（R1）
        if "schema" in rec and rec["schema"] != SCHEMA_ID:
            violations.append(f"{L}: schema 自报 {rec['schema']!r} ≠ {SCHEMA_ID}（整文件拒收口径）")

        for k in REQUIRED:
            if k not in rec or rec[k] is None:
                violations.append(f"{L}: 缺必填字段 {k}")
        dev = rec.get("device")
        if not isinstance(dev, dict) or not isinstance(dev.get("host_or_port"), str) \
                or not dev.get("host_or_port").strip():
            if isinstance(dev, dict) and "host_or_port" not in dev:
                violations.append(f"{L}: device.host_or_port 缺失")
            elif not isinstance(dev, dict):
                violations.append(f"{L}: device 不是对象")

        ts = rec.get("timestamp_utc")
        if ts is not None and _bad_ts(ts):
            violations.append(f"{L}: timestamp_utc 非法（须 ISO8601 UTC 以 Z 结尾且日历存在）: {ts!r}")

        seq = rec.get("seq")
        host = dev.get("host_or_port") if isinstance(dev, dict) else ""
        chan = rec.get("channel")
        if _is_int(seq) and seq >= 0:
            key = (str(chan), str(host))
            if key in last_seq and seq <= last_seq[key]:
                violations.append(
                    f"{L}: seq={seq} 未在流 {(chan, host)!s} 内严格递增（前值 {last_seq[key]}，I1）")
            last_seq[key] = max(seq, last_seq.get(key, seq))
        elif seq is not None:
            violations.append(f"{L}: seq 必须是 ≥0 的整数: {seq!r}")

        if chan is not None and chan not in f["channel"]["enum"]:
            violations.append(f"{L}: channel {chan!r} 不在词表 {f['channel']['enum']}")

        d = rec.get("direction")
        if d is not None and d not in f["direction"]["enum"]:
            violations.append(f"{L}: direction {d!r} 不在词表 {f['direction']['enum']}")

        uid = rec.get("unit_id")
        if _is_int(uid):
            if not 0 <= uid <= 255:
                violations.append(f"{L}: unit_id={uid} 超出 0..255（SL V1.02 §2.2 地址空间）")
            elif 248 <= uid <= 255:
                violations.append(f"{L}: unit_id={uid} 落在保留段 248-255（不该出现在现场日志）")

        fc = rec.get("function_code")
        if fc is not None and (not _is_int(fc) or not 1 <= fc <= 127):
            violations.append(f"{L}: function_code 必须是 1..127 的整数（低 7 位基础码）: {fc!r}")

        exc = rec.get("exception_code")
        if exc is not None:
            if not _is_int(exc) or not 1 <= exc <= 11:
                violations.append(f"{L}: exception_code 必须是 1..0x0B 的整数或 null: {exc!r}")
            if d is not None and d != "resp":
                violations.append(f"{L}: exception_code 只允许出现在 resp（I3，此行 direction={d!r}）")

        err = rec.get("error")
        if err is not None:
            if err not in f["error"]["enum"]:
                violations.append(f"{L}: error {err!r} 不在词表 {f['error']['enum']}")
            if exc is not None:
                violations.append(f"{L}: error 与 exception_code 互斥（I4：链路级失败 vs 协议级异常同帧矛盾）")
            if err == "other" and not (isinstance(rec.get("notes"), str) and rec["notes"].strip()):
                violations.append(f"{L}: error=other 必须带非空 notes（I5）")

        # I2 广播形态：四个合取条件逐条报
        if d == "broadcast":
            if chan != "rtu":
                violations.append(f"{L}: broadcast 只允许在 rtu（I2，此行 channel={chan!r}）")
            if uid != 0:
                violations.append(f"{L}: broadcast 必须 unit_id=0（I2，SL V1.02 §2.2 地址 0=广播）")
            if exc is not None:
                violations.append(f"{L}: broadcast 不得带 exception_code（I2，广播无响应）")
            if err is not None:
                violations.append(f"{L}: broadcast 不得带 error（I2，广播无响应语义）")

        fh = rec.get("frame_hex")
        if fh is not None:
            compact = "".join(str(fh).split())
            if len(compact) % 2 or not HEX_RE.match(compact):
                violations.append(f"{L}: frame_hex 须为偶数个十六进制字符: {str(fh)[:40]!r}")
        elif d == "broadcast" or exc is not None:
            advisories.append(f"{L}: 广播/异常帧建议携带 frame_hex（契约 recommended_when）")

    return violations, advisories


def validate_lines(path: Path, contract: dict) -> tuple[list[str], list[str], int]:
    """整文件口径：非空行逐行解析 → 整批校验（seq 单调需跨行看）。

    行号 = 非空行序号（空行不占号）；坏 JSON 行同样占一个序号并直接记违规。
    返回 (violations, advisories, 消耗的行数)。
    """
    try:
        raw = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        return [f"文件: 非 UTF-8（{e}）"], [], 0
    records: list[dict] = []
    pre: list[str] = []
    ordinals: list[int] = []
    for no, chunk in enumerate((c for c in raw.splitlines() if c.strip()), 1):
        try:
            rec = json.loads(chunk.strip())
        except json.JSONDecodeError as e:
            pre.append(f"L{no}: 不是合法 JSON（{e.msg}）")
            continue
        if not isinstance(rec, dict):
            pre.append(f"L{no}: 记录必须是 JSON 对象: {chunk.strip()[:40]!r}")
            continue
        records.append(rec)
        ordinals.append(no)
    v, a = validate_records(records, contract)
    # validate_records 按批内序号 L1..Ln 编号，这里换算回非空行序号。
    def remap(s: str) -> str:
        if not ordinals:
            return s
        return RE_LNO.sub(lambda m: f"L{ordinals[int(m.group(1)) - 1]}:", s)
    return pre + [remap(s) for s in v], [remap(s) for s in a], len(records) + len(pre)


def _selftest(contract: dict) -> int:
    """内嵌 3 条样例（1 合法 2 非法）：合法放行、非法逐条报出且违规数精确吻合。"""
    samples = [
        # 合法：RTU 广播帧（带 frame_hex，无建议）
        {"schema": "comm_log/1", "timestamp_utc": "2026-10-21T02:15:30.123Z",
         "seq": 0, "channel": "rtu", "direction": "broadcast", "unit_id": 0,
         "function_code": 6, "frame_hex": "00 06 00 01 00 03",
         "device": {"host_or_port": "COM3"}},
        # 非法×2：channel 出词表 + unit_id 超地址空间
        {"timestamp_utc": "2026-10-21T02:15:31Z", "seq": 1, "channel": "udp",
         "direction": "req", "unit_id": 300, "function_code": 3,
         "device": {"host_or_port": "192.168.0.10:502"}},
        # 非法×8：日历不存在 + 异常码越域 + 异常只许 resp(I3) + 互斥(I4) + other 无 notes(I5)
        #         + 广播形态三条(I2：channel/tcp、带异常码、带 error)
        {"timestamp_utc": "2026-02-30T00:00:00Z", "seq": 1, "channel": "tcp",
         "direction": "broadcast", "unit_id": 0, "function_code": 3,
         "exception_code": 200, "error": "other",
         "device": {"host_or_port": "plc1"}},
    ]
    expect = [0, 2, 8]
    ok = True
    for i, (rec, want) in enumerate(zip(samples, expect), 1):
        v, _ = validate_records([rec], contract)
        tag = "OK " if len(v) == want else "BAD"
        if len(v) != want:
            ok = False
        print(f"  selftest 样例{i}: 期望违规 {want}，实得 {len(v)} [{tag}]")
        for s in v:
            print("    -", s)
    print(f"validate_comm_log --selftest: {'PASS' if ok else 'FAIL'}"
          f"（3 条样例：1 合法 + 2 非法，违规数须精确吻合）")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="comm_log/1 现场日志契约校验器（退出码=违规数）")
    ap.add_argument("logfile", nargs="?", type=Path, help="待校验的 JSONL 日志文件")
    ap.add_argument("--selftest", action="store_true", help="内嵌 3 条样例自检（1 合法 2 非法）")
    ap.add_argument("--contract", type=Path, default=None,
                    help="契约文件路径（缺省 knowledge/contracts/comm_log_contract.json）")
    args = ap.parse_args(argv)
    contract = load_contract(args.contract)

    if args.selftest:
        return _selftest(contract)

    if args.logfile is None:
        ap.error("需要 <log.jsonl> 或 --selftest")
    violations, advisories, n = validate_lines(args.logfile, contract)
    for s in violations:
        print("  ✗", s)
    for s in advisories:
        print("  ·", s)
    if violations:
        print(f"comm_log 校验: FAIL（{n} 条记录，违规 {len(violations)}，建议 {len(advisories)}）"
              f"——退出码=违规数 {len(violations)}")
        return len(violations)
    print(f"comm_log 校验: PASS（{n} 条记录，0 违规，建议 {len(advisories)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
