# -*- coding: utf-8 -*-
"""forensics_comm 检出引擎的回归测试（规则逐条 / 误报抑制 / 证据可回查 / CLI）。

三条被守的结论：
  1) 七条规则逐条可检出且检出引用的日志行可回查（L<n> 指向的条目真的满足该
     规则的结构化前提）——检出不是黑盒打分，是可反驳的证据链；
  2) 误报抑制：干净流、孤例异常（<3 连）、词表外形态（refused/no_response）、
     无 TID 证据的 other，一律零检出——宁可少报也不误报；
  3) CLI 纪律：合法日志产出 detections 落盘退出 0；契约不合格的日志被 R2 拒跑
     退出 2；--selftest 退出 0。

诚实边界：全部样例内嵌合成——这里证明的是检出机制对已知形态零漏检、对未知
形态不硬套，不证明现场故障分布覆盖率（农场 Phase 1 构造性真值同款边界）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcopilot.agents.forensics_comm import (  # noqa: E402
    CAUSE_CRC, CAUSE_MALFORMED, CAUSE_RESET, CAUSE_SHORT_READ, CAUSE_STALE_TID,
    CAUSE_STORM, CAUSE_TIMEOUT, detect_entries,
)

MODULE = ROOT / "src" / "mcopilot" / "agents" / "forensics_comm.py"


def mk(seq, direction="resp", fc=3, channel="tcp", host="127.0.0.1:15030", **kw):
    """构造一条契约合法的 comm_log 条目（None 值字段不落，同农场发射器）。"""
    rec = {"timestamp_utc": "2026-10-21T02:15:30.000Z", "seq": seq,
           "channel": channel, "direction": direction, "unit_id": 1,
           "function_code": fc, "device": {"host_or_port": host}}
    rec.update({k: v for k, v in kw.items() if v is not None})
    return rec


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(MODULE), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=120, cwd=str(ROOT), env=env)


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8", newline="\n")
    return path


def _causes(records):
    return [(d["id"], d["cause"]) for d in detect_entries(records)]


# --------------------------------------------------------------- 逐规则检出
def test_timeout规则_检出等待超时条目():
    recs = [mk(0, "req", 3, frame_hex="000100000006010300000002"),
            mk(1, "req", 3, error="timeout", notes="等待响应超时（>1.2s）")]
    got = _causes(recs)
    assert got == [("L2", CAUSE_TIMEOUT)], f"期望仅 L2 超时，实得 {got}"
    d = detect_entries(recs)[0]
    assert d["seq"] == 1 and d["evidence"] == [2], "检出必须携带条目 seq 与行号证据"


def test_conn_reset规则_检出连接重置条目():
    recs = [mk(0, "req", 3), mk(1, "req", 3, error="reset", notes="WinError 10054")]
    assert _causes(recs) == [("L2", CAUSE_RESET)]


def test_crc_error规则_检出RTU链路失败条目():
    recs = [mk(0, "req", 3, channel="rtu", host="COM3"),
            mk(1, "resp", 3, channel="rtu", host="COM3", error="crc",
               frame_hex="0103041234567805 33".replace(" ", ""),
               notes="RTU CRC 校验失败（收 0533，算 33FA）")]
    assert _causes(recs) == [("L2", CAUSE_CRC)]


def test_short_read规则_帧长承诺不满足():
    recs = [mk(0, "req", 3),
            mk(1, "resp", 3, error="malformed", expected_len=6, got_len=3,
               frame_hex="00010000000601030" + "8402", notes="响应正文短读")]
    assert _causes(recs) == [("L2", CAUSE_SHORT_READ)]


def test_malformed_frame规则_MBAP头非法且无短读证据():
    recs = [mk(0, "req", 3),
            mk(1, "resp", 3, error="malformed", frame_hex="deadbeef",
               notes="MBAP 头非法（协议标识=48879）")]
    assert _causes(recs) == [("L2", CAUSE_MALFORMED)]


def test_short与malformed互斥_同一条目只产一条检出():
    """malformed+短读签名 → 只归 short_read；不得同时挂 malformed_frame。"""
    recs = [mk(1, "resp", 3, error="malformed", expected_len=6, got_len=3)]
    causes = [c for _, c in _causes(recs)]
    assert causes == [CAUSE_SHORT_READ] and CAUSE_MALFORMED not in causes


def test_stale_frame_tid规则_陈旧帧事务标识不匹配():
    recs = [mk(0, "req", 3), mk(1, "resp", 3), mk(2, "req", 3),
            mk(3, "resp", 3, error="other", tid_expected=2, tid_got=0,
               frame_hex="0000000000050103020000", notes="陈旧帧占管道")]
    got = _causes(recs)
    assert got == [("L4", CAUSE_STALE_TID)], f"期望 L4 陈旧帧，实得 {got}"
    d = detect_entries(recs)[0]
    assert d["seq"] == 3, "陈旧帧检出的 seq 证据必须指向被读到的陈旧条目"


def test_exception_storm_三连触发且只报一条_id为首条证据行():
    recs = []
    for k in range(4):
        recs.append(mk(2 * k, "req", 3))
        recs.append(mk(2 * k + 1, "resp", 3, exception_code=[1, 2, 3, 5][k]))
    dets = detect_entries(recs)
    assert [(d["id"], d["cause"]) for d in dets] == [("L2", CAUSE_STORM)], \
        "4 连异常只报一条风暴，id=首条异常响应行"
    assert dets[0]["evidence"] == [2, 4, 6, 8], "风暴证据必须含全段行号"


def test_exception_storm_两连不触发_被干净响应截断后重新起算():
    recs = [mk(0, "req", 3), mk(1, "resp", 3, exception_code=1),
            mk(2, "req", 3), mk(3, "resp", 3, exception_code=2),
            mk(4, "resp", 3),                                    # 干净 resp 截断
            mk(5, "req", 3), mk(6, "resp", 3, exception_code=3)]
    assert _causes(recs) == [], "2+1 连不构成风暴（被截断后未达 3 连）"


def test_exception_storm_按流隔离_跨流不合并():
    h1, h2 = "127.0.0.1:15031", "127.0.0.1:15032"
    recs = [mk(0, "resp", 3, host=h1, exception_code=1),
            mk(1, "resp", 3, host=h2, exception_code=1),
            mk(2, "resp", 3, host=h1, exception_code=2),
            mk(3, "resp", 3, host=h2, exception_code=2),
            mk(4, "resp", 3, host=h1, exception_code=3)]   # h1 三连；h2 仅两连
    got = _causes(recs)
    assert got == [("L1", CAUSE_STORM)], "风暴按 (channel, host_or_port) 流内判定"


# --------------------------------------------------------------- 误报抑制
def test_干净流零误报_读写对与孤例异常都不检出():
    recs = [mk(0, "req", 6, frame_hex="0001000000060106000100 6f".replace(" ", "")),
            mk(1, "resp", 6),                                  # FC6 回显
            mk(2, "req", 3), mk(3, "resp", 3),                 # FC3 正常读
            mk(4, "req", 3), mk(5, "resp", 3, exception_code=2),  # 孤例异常≠风暴
            mk(6, "req", 3, frame_hex="000700000006010300000002"),
            mk(7, "resp", 3, frame_hex="0007000000070103041234 5678".replace(" ", ""))]
    assert _causes(recs) == [], "干净流（含合法孤例异常）必须零检出"


def test_未知形态不硬套_refused与no_response与无证据other():
    recs = [mk(0, "req", 3, error="refused", notes="TCP 拒连"),
            mk(1, "req", 3, error="no_response", notes="RTU 静默（物理层无载波）"),
            mk(2, "resp", 3, error="other", notes="说不清的失败"),       # 无 TID 证据
            mk(3, "resp", 3, error="other", tid_expected=5, tid_got=5)]  # TID 相等≠陈旧
    assert _causes(recs) == [], "词表外/证据不足的形态一律不硬套（宁可少报不误报）"


# --------------------------------------------------------------- 证据可回查
def test_检出证据可回查_混合日志逐条指向满足前提的行():
    """农场形态的混合日志：每条检出的首证据行拆出来必须真的满足该规则前提。"""
    recs = [
        mk(0, "req", 6), mk(1, "resp", 6),                                  # clean
        mk(2, "req", 3),                                                    # sticky
        mk(3, "resp", 3, error="other", tid_expected=2, tid_got=0),
        mk(4, "resp", 3),
        mk(5, "req", 3, error="timeout", notes="超时"),                      # timeout
        mk(6, "resp", 3, error="malformed", expected_len=6, got_len=3),     # short
        mk(7, "resp", 3, error="malformed", notes="MBAP 头非法"),           # malformed
        mk(8, "req", 3, error="reset", notes="RST"),                        # reset
        mk(9, "resp", 3, channel="rtu", host="COM3", error="crc"),          # crc
        mk(10, "req", 3), mk(11, "resp", 3, exception_code=1),
        mk(12, "req", 3), mk(13, "resp", 3, exception_code=2),
        mk(14, "req", 3), mk(15, "resp", 3, exception_code=3),              # storm
    ]
    dets = detect_entries(recs)
    assert len(dets) == 7, f"期望 7 条检出（7 规则各 1），实得 {len(dets)}"
    for d in dets:
        rec = recs[int(d["evidence"][0]) - 1]
        cause, e = d["cause"], rec.get("error")
        if cause == CAUSE_TIMEOUT:
            ok = e == "timeout"
        elif cause == CAUSE_RESET:
            ok = e == "reset"
        elif cause == CAUSE_CRC:
            ok = e == "crc"
        elif cause == CAUSE_SHORT_READ:
            ok = (e == "malformed" and rec.get("got_len", 99) < rec["expected_len"])
        elif cause == CAUSE_MALFORMED:
            ok = e == "malformed" and "expected_len" not in rec
        elif cause == CAUSE_STALE_TID:
            ok = (e == "other" and rec.get("tid_expected") != rec.get("tid_got"))
        elif cause == CAUSE_STORM:
            ok = isinstance(rec.get("exception_code"), int)
        else:
            ok = False
        assert ok, f"{d['id']}/{cause} 的证据行不满足规则前提（不可回查即不可信）"


def test_农场粘包形态端到端_三事务三检出与农场真值同构():
    """复刻农场 sticky_stale 场景的条目形态：4 事务 → 3 条陈旧帧检出。"""
    recs = [mk(0, "req", 3), mk(1, "resp", 3)]
    for k in range(2, 5):                       # 事务 k：陈旧帧(TID=k-2) + 真实响应
        recs.append(mk(3 * (k - 1), "req", 3))
        recs.append(mk(3 * (k - 1) + 1, "resp", 3, error="other",
                       tid_expected=k, tid_got=k - 2))
        recs.append(mk(3 * (k - 1) + 2, "resp", 3))
    got = [(d["id"], d["cause"]) for d in detect_entries(recs)]
    assert got == [("L4", CAUSE_STALE_TID), ("L7", CAUSE_STALE_TID),
                   ("L10", CAUSE_STALE_TID)]


# --------------------------------------------------------------- CLI 纪律
def test_CLI_合法日志检出落盘退出0():
    recs = [mk(0, "req", 3), mk(1, "req", 3, error="timeout", notes="超时")]
    with tempfile.TemporaryDirectory() as td:
        log = _write_jsonl(Path(td) / "log.jsonl", recs)
        out = Path(td) / "det.jsonl"
        r = _run_cli("--log", str(log), "--out", str(out))
        assert r.returncode == 0, f"CLI 应退出 0：\n{r.stdout}\n{r.stderr}"
        assert "COMM-DETECT" in r.stdout and "detections=1" in r.stdout
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()
                if x.strip()]
        assert rows and rows[0]["id"] == "L2" and rows[0]["cause"] == CAUSE_TIMEOUT, \
            "detections 落盘内容必须与内存检出一致"


def test_CLI_契约不合格的日志被R2拒跑退出2():
    recs = [mk(0, "req", 3)]
    recs[0]["channel"] = "udp"                  # 契约词表外 → 必须拒跑
    with tempfile.TemporaryDirectory() as td:
        log = _write_jsonl(Path(td) / "bad.jsonl", recs)
        out = Path(td) / "det.jsonl"
        r = _run_cli("--log", str(log), "--out", str(out))
        assert r.returncode == 2, f"R2 拒跑应退出 2，实得 {r.returncode}:\n{r.stdout}"
        assert "拒跑" in r.stdout
        assert not out.exists(), "拒跑时不得产出检出文件"


def test_CLI_selftest退出0():
    r = _run_cli("--selftest")
    assert r.returncode == 0, f"--selftest 应退出 0：\n{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout and "诚实边界" in r.stdout
