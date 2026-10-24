# -*- coding: utf-8 -*-
"""comm_log/1 契约 + forensics 评测骨架的回归测试。

三条被守的结论：
  1) 契约文件本身可解析、schema id 正确、任务点名字段全部有定义（契约不许烂在库里）；
  2) validate_comm_log --selftest 退出码 0（校验器行为与契约一致：合法放行、
     非法逐条报出且违规数精确吻合）；
  3) eval_forensics 骨架可跑：--selftest 过 + 对临时样例三件套产出
     precision/recall/漏检清单；契约不合格的日志必须被 R2 拒跑。

诚实边界：全部样例合成——这里证明的是工具链可跑，不是归因质量。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "knowledge" / "contracts" / "comm_log_contract.json"
PY = sys.executable


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([PY, str(script), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=120, cwd=str(ROOT), env=env)


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8", newline="\n")
    return path


# --------------------------------------------------------------- 契约文件本体

def test_契约文件可解析且schema正确():
    doc = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert doc["schema"] == "comm_log/1"
    fields = doc["fields"]
    for name in ("timestamp_utc", "seq", "channel", "direction", "unit_id",
                 "function_code", "exception_code", "frame_hex", "error",
                 "device", "notes"):
        assert name in fields, f"任务点名字段 {name} 必须在契约中有定义"
    assert fields["channel"]["enum"] == ["tcp", "rtu"]
    assert fields["direction"]["enum"] == ["req", "resp", "broadcast"]
    assert "timeout" in fields["error"]["enum"] and "crc" in fields["error"]["enum"] \
        and "reset" in fields["error"]["enum"]
    assert fields["exception_code"]["min"] == 1 and fields["exception_code"]["max"] == 11
    assert doc["invariants"] and doc["red_lines"], "契约必须有不变式与红线"


# ------------------------------------------------------- validate_comm_log.py

def test_validate_comm_log_selftest退出码0():
    r = _run(ROOT / "scripts" / "validate_comm_log.py", "--selftest")
    assert r.returncode == 0, "selftest 未过（合法样例须放行、非法样例违规数须精确吻合）:\n" \
        + r.stdout[-1500:]
    assert "PASS" in r.stdout


def test_合法日志放行退出0():
    recs = [
        {"timestamp_utc": "2026-10-21T02:15:30.123Z", "seq": 0, "channel": "tcp",
         "direction": "req", "unit_id": 17, "function_code": 3,
         "device": {"host_or_port": "192.168.0.10:502"}},
        {"timestamp_utc": "2026-10-21T02:15:30.456Z", "seq": 1, "channel": "tcp",
         "direction": "resp", "unit_id": 17, "function_code": 3,
         "exception_code": 2, "device": {"host_or_port": "192.168.0.10:502"},
         "frame_hex": "83 83 02 b4 7b", "notes": "异常响应 FC=0x83（请求 3+0x80）"},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        log = _write_jsonl(Path(td) / "ok.jsonl", recs)
        r = _run(ROOT / "scripts" / "validate_comm_log.py", str(log))
    assert r.returncode == 0, "合法日志必须 PASS（含异常响应记录）:\n" + r.stdout
    assert "PASS" in r.stdout


def test_非法日志退出码等于违规数():
    recs = [
        {"timestamp_utc": "2026-10-21T02:15:30Z", "seq": 0, "channel": "udp",
         "direction": "req", "unit_id": 17, "function_code": 3,
         "device": {"host_or_port": "192.168.0.10:502"}},          # 1 违规：channel
        {"timestamp_utc": "2026-10-21T02:15:31Z", "seq": 0, "channel": "udp",
         "direction": "req", "unit_id": 250, "function_code": 0,
         "device": {"host_or_port": "192.168.0.10:502"}},          # 4 违规：channel、seq 未递增、保留段、fc=0
        "not-json",                                                  # 1 违规：坏 JSON
    ]  # 合计 6 违规（L1 channel 1 + L2 四项 + L3 坏 JSON 1）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bad.jsonl"
        p.write_text("".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n"
                             for r in recs), encoding="utf-8", newline="\n")
        r = _run(ROOT / "scripts" / "validate_comm_log.py", str(p))
    assert r.returncode == 6, f"退出码应为违规数 6，实得 {r.returncode}:\n" + r.stdout
    assert "FAIL" in r.stdout
    # 行号必须可见（现场按行修采集端）
    assert "L1:" in r.stdout and "L3:" in r.stdout


# ------------------------------------------------------------ eval_forensics.py

def test_eval_forensics_selftest退出码0():
    r = _run(ROOT / "scripts" / "eval_forensics.py", "--selftest")
    assert r.returncode == 0, "eval 骨架 selftest 未过:\n" + r.stdout[-1500:]
    assert "precision" in r.stdout and "recall" in r.stdout
    assert "不能对归因质量下结论" in r.stdout, "诚实边界声明必须随输出"


def test_eval_forensics样例三件套可跑():
    logs = [
        {"timestamp_utc": "2026-10-21T02:15:30.123Z", "seq": 0, "channel": "rtu",
         "direction": "req", "unit_id": 17, "function_code": 3,
         "device": {"host_or_port": "COM3"}},
        {"timestamp_utc": "2026-10-21T02:15:31.000Z", "seq": 1, "channel": "rtu",
         "direction": "resp", "unit_id": 17, "function_code": 3,
         "exception_code": 2, "device": {"host_or_port": "COM3"}},
        {"timestamp_utc": "2026-10-21T02:15:32.000Z", "seq": 2, "channel": "rtu",
         "direction": "req", "unit_id": 17, "function_code": 3,
         "error": "timeout", "device": {"host_or_port": "COM3"}},
    ]
    detections = [
        {"id": "L2", "cause": "EX02_ILLEGAL_DATA_ADDRESS"},
        {"id": "L3", "cause": "EX02_ILLEGAL_DATA_ADDRESS"},   # 错因：超时被归成异常码
    ]
    truth = [
        {"id": "L2", "cause": "EX02_ILLEGAL_DATA_ADDRESS"},
        {"id": "L3", "cause": "timeout_after_req"},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        logs_p = _write_jsonl(Path(td) / "logs.jsonl", logs)
        det_p = _write_jsonl(Path(td) / "det.jsonl", detections)
        tru_p = _write_jsonl(Path(td) / "tru.jsonl", truth)
        r = _run(ROOT / "scripts" / "eval_forensics.py", "--logs", str(logs_p),
                 "--detections", str(det_p), "--truth", str(tru_p))
    assert r.returncode == 0, "样例三件套必须可跑:\n" + r.stdout
    assert "precision = 0.5000" in r.stdout and "recall    = 0.5000" in r.stdout
    assert "漏检清单" in r.stdout and "timeout_after_req" in r.stdout


def test_契约不合格的日志被R2拒跑():
    logs = [{"timestamp_utc": "2026-10-21T02:15:30Z", "seq": 0, "channel": "udp",
             "direction": "req", "unit_id": 17, "function_code": 3,
             "device": {"host_or_port": "x"}}]
    detections = [{"id": "L1", "cause": "anything"}]
    truth = [{"id": "L1", "cause": "anything"}]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        logs_p = _write_jsonl(Path(td) / "logs.jsonl", logs)
        det_p = _write_jsonl(Path(td) / "det.jsonl", detections)
        tru_p = _write_jsonl(Path(td) / "tru.jsonl", truth)
        r = _run(ROOT / "scripts" / "eval_forensics.py", "--logs", str(logs_p),
                 "--detections", str(det_p), "--truth", str(tru_p))
    assert r.returncode == 2, "契约不合格的日志必须被 R2 拒跑（退出码 2）:\n" + r.stdout
    assert "拒跑" in r.stdout
