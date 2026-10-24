# -*- coding: utf-8 -*-
"""forensics_comm —— comm_log/1 通信日志检出引擎（规则可解释、证据可回查、零依赖）。

定位：fault_farm（scripts/fault_farm.py）批产的带标签 comm_log/1 日志流 → 本模块
按规则集检出故障形态 → 输出 detections jsonl，交 scripts/eval_forensics.py 对
构造性真值判卷（G11 门禁闭环的"检出"一环）。与 src/mcopilot/agents/forensics.py
同一套纪律，但对象不同（设备文本日志 vs comm_log 帧级 JSONL），不共用代码与词表。

设计原则（与 forensics.py 同源）：
  · 每条检出都引用日志**行号**（L<n>，非空行序号，同 validate_comm_log 口径）与
    流内 seq，人可回查、可反驳；
  · 规则只吃条目里的**结构化特征**（error 枚举值、exception_code、
    tid_expected/tid_got、expected_len/got_len），不做自由文本猜测；
  · 宁可少报也不误报：未知形态不硬套——error=refused / no_response、以及
    error=other 而无 TID 证据的条目，一律**不**产出检出；
  · 不带病检出（R2 同款）：输入日志必须先过 comm_log/1 契约门（复用
    scripts/validate_comm_log.py，不另抄口径），违规即拒跑。

规则集（7 条，cause 词表封闭）：
  cause             触发条件（结构化）                                   粒度
  ----------------  --------------------------------------------------  ------
  crc_error         error=crc 的 RTU 链路失败条目                        逐条
  timeout           error=timeout 的等待超时失败条目                     逐条
  conn_reset        error=reset 的连接重置失败条目                       逐条
  short_read        error=malformed 且 expected_len/got_len 在场且
                    got_len < expected_len（帧长承诺不满足=短读）        逐条
  malformed_frame   error=malformed 但无短读证据（如 MBAP 头本身非法）   逐条
  stale_frame_tid   error=other 且 tid_expected/tid_got 在场且不等
                    （接收缓冲陈旧帧占管道 → 事务标识不匹配）            逐条
  exception_storm   同一 (channel, host_or_port) 流内**连续** ≥3 条带
                    exception_code 的 resp（req 条目不断开连续性，无异常
                    码的 resp 截断）；一段风暴只报一条，id=首条证据行    每段

CLI：
  python src/mcopilot/agents/forensics_comm.py --log <comm_log.jsonl> --out <detections.jsonl>
  python src/mcopilot/agents/forensics_comm.py --selftest

诚实边界（2026-10-21）：规则与阈值由故障注入农场构造性场景钉住（注入参数即真值），
只证明「检出机制对已知形态零漏检、对 clean 零误报」；**不证明现场故障分布的覆盖
率**——那要等 Phase 2 真实语料与 Phase 3 真机波次。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量
CAUSE_CRC = "crc_error"
CAUSE_TIMEOUT = "timeout"
CAUSE_SHORT_READ = "short_read"
CAUSE_STALE_TID = "stale_frame_tid"
CAUSE_STORM = "exception_storm"
CAUSE_RESET = "conn_reset"
CAUSE_MALFORMED = "malformed_frame"

KNOWN_CAUSES = frozenset({
    CAUSE_CRC, CAUSE_TIMEOUT, CAUSE_SHORT_READ, CAUSE_STALE_TID,
    CAUSE_STORM, CAUSE_RESET, CAUSE_MALFORMED,
})

STORM_MIN = 3          # 连续异常响应达到该条数即判风暴（农场 sweep 场景 4 连钉住）
MALFORMED_MAX_LEN = 254  # MBAP 合法长度上限（单元标识 1B + PDU ≤253B）

RULE_BRIEF = {
    CAUSE_CRC: "error=crc（RTU 链路校验失败条目）",
    CAUSE_TIMEOUT: "error=timeout（等待响应超时条目）",
    CAUSE_RESET: "error=reset（连接被重置条目）",
    CAUSE_SHORT_READ: "error=malformed 且 got_len<expected_len（短读）",
    CAUSE_MALFORMED: "error=malformed 无短读证据（帧布局解析失败）",
    CAUSE_STALE_TID: "error=other 且 tid_expected≠tid_got（陈旧帧占管道）",
    CAUSE_STORM: "同流连续 ≥%d 条 exception_code resp（风暴段报一条）" % STORM_MIN,
}


# ---------------------------------------------------------------- 工具
def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _stream_key(rec: dict) -> tuple[str, str]:
    dev = rec.get("device") if isinstance(rec.get("device"), dict) else {}
    return (str(rec.get("channel")), str(dev.get("host_or_port")))


def _is_resp(rec: dict) -> bool:
    return rec.get("direction") == "resp"


def _has_exception(rec: dict) -> bool:
    return _is_int(rec.get("exception_code"))


def _short_signature(rec: dict) -> bool:
    """短读证据：malformed 且带 expected_len/got_len 且实收小于承诺。"""
    if rec.get("error") != "malformed":
        return False
    want, got = rec.get("expected_len"), rec.get("got_len")
    return _is_int(want) and _is_int(got) and 0 <= got < want


def _tid_mismatch(rec: dict) -> bool:
    a, b = rec.get("tid_expected"), rec.get("tid_got")
    return _is_int(a) and _is_int(b) and a != b


def _det(no: int, rec: dict, cause: str, evidence: list[int], detail: str) -> dict:
    """一条检出：id 引日志行号，evidence 引全部证据行号，seq/流随条目。"""
    return {"id": f"L{no}", "cause": cause, "rule": RULE_BRIEF[cause],
            "seq": rec.get("seq"), "channel": rec.get("channel"),
            "stream": _stream_key(rec)[1], "evidence": evidence, "detail": detail}


# ---------------------------------------------------------------- 检出引擎
def detect_entries(records: list[dict]) -> list[dict]:
    """对内存中的 comm_log 条目流检出，返回 detections 列表（按日志行序稳定）。"""
    detections: list[dict] = []

    # ---- 逐条规则（结构化特征触发；未知形态不硬套）----
    for no, rec in enumerate(records, 1):
        err = rec.get("error")
        note = str(rec.get("notes", ""))[:70]
        if err == "crc":
            detections.append(_det(
                no, rec, CAUSE_CRC, [no],
                f"seq={rec.get('seq')} CRC 失败条目：{note}"))
        elif err == "timeout":
            detections.append(_det(
                no, rec, CAUSE_TIMEOUT, [no],
                f"seq={rec.get('seq')} 超时条目：{note}"))
        elif err == "reset":
            detections.append(_det(
                no, rec, CAUSE_RESET, [no],
                f"seq={rec.get('seq')} 连接重置条目：{note}"))
        elif err == "malformed":
            if _short_signature(rec):
                detections.append(_det(
                    no, rec, CAUSE_SHORT_READ, [no],
                    f"seq={rec.get('seq')} 帧长承诺不满足：承诺 {rec.get('expected_len')}B，"
                    f"实收 {rec.get('got_len')}B"))
            else:
                detections.append(_det(
                    no, rec, CAUSE_MALFORMED, [no],
                    f"seq={rec.get('seq')} 帧布局解析失败且无短读证据：{note}"))
        elif err == "other" and _tid_mismatch(rec):
            detections.append(_det(
                no, rec, CAUSE_STALE_TID, [no],
                f"seq={rec.get('seq')} 事务标识不匹配：期待 TID={rec.get('tid_expected')}，"
                f"先读到 TID={rec.get('tid_got')}（接收缓冲陈旧帧）"))
        # 其余形态（refused / no_response / 无 TID 证据的 other / 正常帧）不产出检出。

    # ---- exception_storm：按流扫描连续异常响应段 ----
    runs: dict[tuple[str, str], list[tuple[int, dict]]] = {}

    def flush(key) -> None:
        run = runs.pop(key, [])
        if len(run) >= STORM_MIN:
            first_no, first_rec = run[0]
            nos = [n for n, _ in run]
            detections.append(_det(
                first_no, first_rec, CAUSE_STORM, nos,
                f"流 {key[0]}/{key[1]} 连续 {len(run)} 条异常响应（seq="
                + ",".join(str(r.get("seq")) for _, r in run) + "），判异常风暴"))

    for no, rec in enumerate(records, 1):
        key = _stream_key(rec)
        if _is_resp(rec) and _has_exception(rec):
            runs.setdefault(key, []).append((no, rec))
        elif _is_resp(rec):
            flush(key)          # 无异常码的 resp 截断当前风暴段
        # req / error=req 等非 resp 条目不断开连续性（请求夹在异常响应间是正常形态）
    for key in list(runs):
        flush(key)

    detections.sort(key=lambda d: int(d["id"][1:]))
    return detections


def read_log(path: Path) -> tuple[list[dict], list[str]]:
    """读 JSONL 日志 → (条目列表, 坏行摘要)。行号口径=非空行序号（同校验器）。"""
    records: list[dict] = []
    bad: list[str] = []
    for no, chunk in enumerate((c for c in path.read_text(encoding="utf-8").splitlines()
                                if c.strip()), 1):
        try:
            rec = json.loads(chunk)
        except json.JSONDecodeError as e:
            bad.append(f"L{no}: 不是合法 JSON（{e.msg}）")
            continue
        if not isinstance(rec, dict):
            bad.append(f"L{no}: 记录必须是 JSON 对象")
            continue
        records.append(rec)
    return records, bad


def _load_validator():
    """复用 scripts/validate_comm_log.py 当契约裁判（R2：不另抄口径）。"""
    for anc in Path(__file__).resolve().parents:
        cand = anc / "scripts" / "validate_comm_log.py"
        if cand.is_file():
            if str(anc / "scripts") not in sys.path:
                sys.path.insert(0, str(anc / "scripts"))
            import validate_comm_log as vcl  # noqa: E402
            return vcl
    return None


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    try:  # Windows 控制台缺省码页兜底（仓库环境本就 UTF-8，此行只是保险）
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    ap = argparse.ArgumentParser(
        description="comm_log/1 检出引擎：规则可解释、证据可回查（零依赖）")
    ap.add_argument("--log", type=Path, help="comm_log/1 日志 jsonl（先过契约门再检出）")
    ap.add_argument("--out", type=Path, help="检出结果 jsonl 输出路径")
    ap.add_argument("--contract", type=Path, default=None,
                    help="契约文件路径（缺省仓库契约）")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌逐规则样例自检（7 规则 + 3 抑制样例）")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not (args.log and args.out):
        ap.error("需要 --log 与 --out（或 --selftest）")

    vcl = _load_validator()
    if vcl is None:
        print("✗ 找不到 scripts/validate_comm_log.py（契约裁判必须在场，R2）")
        return 3
    contract = vcl.load_contract(args.contract)
    violations, _, n = vcl.validate_lines(args.log, contract)
    if violations:
        print(f"✗ 日志未过 comm_log/1 契约门（{n} 条记录，违规 {len(violations)}），拒跑检出（R2）")
        for s in violations[:20]:
            print("  ✗", s)
        return 2

    records, bad = read_log(args.log)
    if bad:
        print("✗ 日志存在坏行（契约门之后的二次防线）：")
        for s in bad[:10]:
            print("  ✗", s)
        return 2

    detections = detect_entries(records)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(str(args.out), "w", encoding="utf-8", newline="\n") as fh:
        for d in detections:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    by_cause: dict[str, int] = {}
    for d in detections:
        by_cause[d["cause"]] = by_cause.get(d["cause"], 0) + 1
    print(f"COMM-DETECT\tentries={len(records)}\tdetections={len(detections)}\t"
          f"by_cause=" + ",".join(f"{k}:{v}" for k, v in sorted(by_cause.items())))
    for d in detections:
        print(f"  DETECT\t{d['id']}\t{d['cause']}\tseq={d['seq']}\t{d['detail']}")
    return 0


def _selftest() -> int:
    """内嵌样例：7 条规则各 1 检出 + 3 抑制样例 0 检出，(id,cause) 集须精确吻合。"""
    def mk(seq, direction="resp", fc=3, channel="tcp", host="127.0.0.1:15030", **kw):
        rec = {"timestamp_utc": "2026-10-21T02:15:30.000Z", "seq": seq,
               "channel": channel, "direction": direction, "unit_id": 1,
               "function_code": fc, "device": {"host_or_port": host}}
        rec.update({k: v for k, v in kw.items() if v is not None})
        return rec

    # 7 检出样例：一条流塞 6 条逐条规则 + 另一条流塞风暴段
    main_stream = [
        mk(0, "req", 3),                                                     # L1 正常
        mk(1, "req", 3, error="timeout", notes="等待响应超时"),               # L2 timeout
        mk(2, "req", 3, error="reset", notes="连接被重置"),                   # L3 conn_reset
        mk(3, "resp", 3, error="crc", frame_hex="0103840000b804"),           # L4 crc_error
        mk(4, "resp", 3, error="malformed", expected_len=6, got_len=3),      # L5 short_read
        mk(5, "resp", 3, error="malformed", notes="MBAP 协议标识非 0"),       # L6 malformed_frame
        mk(6, "resp", 3, error="other", tid_expected=7, tid_got=6),          # L7 stale_frame_tid
    ]
    sweep = [
        mk(0, "req", 3, channel="tcp", host="127.0.0.1:15036"),              # L8
        mk(1, "resp", 3, exception_code=1, channel="tcp", host="127.0.0.1:15036"),   # L9  ┐
        mk(2, "req", 3, channel="tcp", host="127.0.0.1:15036"),                      # L10 │
        mk(3, "resp", 3, exception_code=2, channel="tcp", host="127.0.0.1:15036"),   # L11 │连续 4
        mk(4, "req", 3, channel="tcp", host="127.0.0.1:15036"),                      # L12 │
        mk(5, "resp", 3, exception_code=3, channel="tcp", host="127.0.0.1:15036"),   # L13 │
        mk(6, "req", 3, channel="tcp", host="127.0.0.1:15036"),                      # L14 │
        mk(7, "resp", 3, exception_code=5, channel="tcp", host="127.0.0.1:15036"),   # L15 ┘
    ]
    # 抑制样例：干净流 + 孤例异常 + 未知形态
    quiet = [
        mk(0, "req", 6), mk(1, "resp", 6),                                   # 正常读写对
        mk(2, "req", 3), mk(3, "resp", 3, exception_code=2),                 # 孤例异常≠风暴
        mk(4, "req", 3, error="refused", notes="TCP 拒连"),                  # 词表外形态：不硬套
        mk(5, "resp", 3, error="other", notes="说不清的失败"),               # other 无 TID 证据：不硬套
    ]

    records = main_stream + sweep + quiet
    got = {(d["id"], d["cause"]) for d in detect_entries(records)}
    want = {("L2", CAUSE_TIMEOUT), ("L3", CAUSE_RESET), ("L4", CAUSE_CRC),
            ("L5", CAUSE_SHORT_READ), ("L6", CAUSE_MALFORMED),
            ("L7", CAUSE_STALE_TID), ("L9", CAUSE_STORM)}
    ok = got == want
    print(f"  selftest 检出: 期望 {len(want)} 条（7 规则各 1），实得 {len(got)} "
          f"[{'OK ' if ok else 'BAD'}]")
    for miss in sorted(want - got):
        print(f"    - 漏检 {miss}")
    for extra in sorted(got - want):
        print(f"    - 误报 {extra}")
    n_quiet = sum(1 for d in detect_entries(quiet))
    ok_quiet = n_quiet == 0
    print(f"  selftest 抑制: 干净流+孤例+未知形态 检出 {n_quiet} 条 "
          f"[{'OK ' if ok_quiet else 'BAD'}]（期望 0）")
    # 证据可回查：每条检出的首证据行必须真的满足该规则前提
    roundtrip = True
    for d in detect_entries(records):
        rec = records[int(d["evidence"][0]) - 1]
        if d["cause"] == CAUSE_TIMEOUT and rec.get("error") != "timeout":
            roundtrip = False
        if d["cause"] == CAUSE_CRC and rec.get("error") != "crc":
            roundtrip = False
        if d["cause"] == CAUSE_RESET and rec.get("error") != "reset":
            roundtrip = False
        if d["cause"] == CAUSE_SHORT_READ and not _short_signature(rec):
            roundtrip = False
        if d["cause"] == CAUSE_STORM and not _has_exception(rec):
            roundtrip = False
    print(f"  selftest 回查: 检出证据行满足规则前提 [{'OK ' if roundtrip else 'BAD'}]")
    all_ok = ok and ok_quiet and roundtrip
    print(f"forensics_comm --selftest: {'PASS' if all_ok else 'FAIL'}")
    print("诚实边界：规则由故障注入农场构造性场景钉住，不证明现场故障分布覆盖率。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
