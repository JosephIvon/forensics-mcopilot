#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
fault_farm.py —— 故障注入农场 Phase 1：构造性真值的带标签通信日志批产（零依赖）
================================================================================

职责（G11 全链闭环的第一环）：
  场景驱动器：对每个故障场景「注入 → 客户端/探针收发与错误事件落成 comm_log/1 条目
  → 按注入参数构造标签（真值在注入那一刻即知，不依赖事后观测）」。
  产出（--out 目录，缺省 out/farm/）：
    <scenario>/comm_log.jsonl   单场景日志（每场景一条独立的 (channel, 设备) 流）
    <scenario>/label.json       标签 {scenario, injected_fault, expected_detection,
                                       status, assertions, truth(场景内下标)}
    comm_log_all.jsonl          全场景合并日志（行号 L<n> 是判卷与检出的统一坐标）
    truth_all.jsonl             合并真值 [{id:"L<n>", cause}]
    detections 的坐标由 src/mcopilot/agents/forensics_comm.py 产出（门禁第二环）
    scenario_index.json         场景→合并日志行区间（门禁混淆矩阵用）
    n1_target.json              负向 N1 的错标目标行（门禁第五环用）
    farm_summary.json           机器可读汇总

场景清单（注入参数 → 构造性真值）：
  TCP 路（起 tests/fixtures/modbus/modbus_tcp_slave.py 于独立端口，fixture 只读复用）：
    clean            正常读写 4 事务（FC6 写/FC3 读交替）      负样本，检出必须为 0
    sticky_stale     --sticky-stale 1：每响应附发旧 TID 陈旧帧  每事务≥2 检出 stale_frame_tid
    fragment_byte1   --fragment byte1：响应逐字节滴流           时序容忍：检出必须为 0
    short_read       沙盒副本对客户端注入劣化（只读 length-3）  检出 short_read；阳性对照=0
    timeout          农场静默桩：连接后从站停答                 检出 timeout
    conn_reset       农场 RST 桩：SO_LINGER(1,0) 中途断连       检出 conn_reset
    malformed_reply  农场乱码桩：回协议标识≠0 的垃圾帧          检出 malformed_frame
    exception_sweep  --exception-sweep：逐请求回异常码 01..     检出 exception_storm
  RTU 路（com0com COM3/COM4，先探测，缺失整路记 SKIP 不算败）：
    crc_corrupt      modbus_rtu_slave --corrupt-next（只读复用）首响应坏 CRC 检出 crc_error
    rtu_timeout      农场 no-respond 桩（复用 G4 同款做法）     检出 timeout

构造性真值三断言（每场景自动执行，任一不满足即该场景 FAIL）：
  ① 注入生效：从站 stdout 标记在场（粘包/坏 CRC/扫掠），或探针观测到注入特征
    （逐字节滴流的 chunk 数、静默时长、RST 异常、承诺长度不满足）；
  ② 构造==现实：真值行指向的日志条目必须携带该 cause 的结构化签名
    （如 timeout 条目 error=timeout 在场）；
  ③ 日志合法：场景日志必须通过 scripts/validate_comm_log.py 全量校验
    （绝不带病出农场——采集端缺陷在农场就地暴露，不流到检出层）。

退出码：0 = 全 PASS（RTU 缺席按 SKIP 不算败）；21 = 有场景 FAIL；22 = 环境错误；
        100 = 兜底异常。总退出码域 = 20（scripts/gate_farm.ps1 / G11）。

零第三方依赖（仅 Python 标准库；RTU 走 kernel32，复用只读 fixture 的串口层）。
诚实边界：本农场的真值全部是注入参数的构造性推论——它证明「批产→检出→判卷」
管线的机制正确（构造类 100% 检出、clean 零误报），**不证明现场故障分布**；
分布校准属 Phase 2（真实语料）与 Phase 3（真机波次）。
================================================================================
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "modbus"
TCP_SLAVE = FIXTURES / "modbus_tcp_slave.py"
RTU_SLAVE = FIXTURES / "modbus_rtu_slave.py"

EXIT_OK = 0
EXIT_SCENARIO = 21
EXIT_ENV = 22
EXIT_BROKEN = 100

PORT_BASE = 15030          # 农场专用端口段（避开协议域门禁的 15020-15024）
UNIT_ID = 1
FC_READ_HOLDING = 3
FC_WRITE_REG = 6
SEEDS = "0=1234,1=5678"

SHORT_READ_MARKER = "GATE-FARM-SHORTREAD"
# 行首锚定（^ + 4 空格缩进）：只命中 tcp_read_body 的真函数体行，
# 不会误命中 SHORT_READ_REPLACEMENT 常量字符串里的同名文本（教训：注入点
# 的口径必须避开"注入器自己的源码字面量"，否则副本注入即自毁）。
SHORT_READ_PATTERN = r"(?m)^    return recv_exact\(sock, length, chunks\)$"
SHORT_READ_REPLACEMENT = ("    length = max(1, length - 3)  # " + SHORT_READ_MARKER + "\n"
                          "    return recv_exact(sock, length, chunks)")

GARBAGE_REPLY = bytes.fromhex("DEADBEEFCAFEBABE01020304")   # 协议标识=0xBEEF≠0


# ---------------------------------------------------------------- 小工具
def utc_iso() -> str:
    """ISO 8601 UTC（毫秒、Z 结尾）——契约 fields.timestamp_utc 的合法形态。"""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def find_free_port(start: int) -> int:
    """从 start 起找一个可绑定的回环端口（绑定后立即释放，竞态窗口可忽略）。"""
    for port in range(start, start + 64):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise EnvironmentError(f"{start} 起 64 个端口都绑不上")


def port_open(host: str, port: int, timeout_ms: int = 300) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout_ms / 1000.0)
        s.close()
        return True
    except OSError:
        return False


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def emit(line: str) -> None:
    print(line, flush=True)


# ---------------------------------------------------------------- comm_log 落记
class CommLogger:
    """一个场景流的 comm_log/1 条目收集器（seq 流内严格递增，可带基址续流）。"""

    def __init__(self, channel: str, host_or_port: str, seq_base: int = 0):
        self.channel = channel
        self.host_or_port = host_or_port
        self.seq = seq_base
        self.entries: list[dict] = []

    def emit(self, direction: str, unit_id: int, function_code: int, **extra) -> int:
        """落一条记录，返回场景内下标（0 起）。None 值 extra 字段不落（契约缺省语义）。"""
        rec = {"timestamp_utc": utc_iso(), "seq": self.seq, "channel": self.channel,
               "direction": direction, "unit_id": unit_id,
               "function_code": function_code,
               "device": {"host_or_port": self.host_or_port}}
        self.seq += 1
        for k, v in extra.items():
            if v is not None:
                rec[k] = v
        self.entries.append(rec)
        return len(self.entries) - 1


# ---------------------------------------------------------------- Modbus 帧
def mbap(tid: int, uid: int, pdu: bytes) -> bytes:
    return (tid.to_bytes(2, "big") + (0).to_bytes(2, "big")
            + (len(pdu) + 1).to_bytes(2, "big") + bytes([uid]) + pdu)


def pdu_read_holding(start: int, qty: int) -> bytes:
    return bytes([FC_READ_HOLDING]) + start.to_bytes(2, "big") + qty.to_bytes(2, "big")


def pdu_write_reg(addr: int, val: int) -> bytes:
    return bytes([FC_WRITE_REG]) + addr.to_bytes(2, "big") + val.to_bytes(2, "big")


def recv_exact(sock: socket.socket, n: int, chunks: list) -> bytes:
    """循环 recv 直至凑满 n 字节；对端提前关闭返回不足 n 的已收部分
    （调用方按 len 判短读）。chunks[0] 累计 recv 调用次数（滴流观测用）。"""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        chunks[0] += 1
        if not chunk:
            break
        buf += chunk
    return bytes(buf)


def tcp_read_body(sock: socket.socket, length: int, chunks: list) -> bytes:
    """按 MBAP 长度承诺读响应正文（length = 单元标识 + PDU 字节数）。

    短读注入点：农场沙盒副本把下面的 return 改写为「先扣 3 字节再读」
    （探针标记 GATE-FARM-SHORTREAD），构造「承诺 N 实收 M<N」的构造性短读。
    """
    return recv_exact(sock, length, chunks)


def tcp_transact(sock: socket.socket, tid: int, uid: int, req_pdu: bytes,
                 log: CommLogger, timeout_s: float) -> dict:
    """一次 Modbus TCP 事务：发请求 → 按 MBAP 重组响应 → 逐事件落 comm_log。

    返回 outcome：kind ∈ ok / exception / stale_resync / timeout / reset /
    short / malformed / closed / send_error；stale_idx 记陈旧帧条目下标，
    chunks 记 recv 次数（滴流证据）。异常帧/TID 不匹配按合同词表如实落记。
    """
    frame = mbap(tid, uid, req_pdu)
    chunks = [0]
    fc_req = req_pdu[0]
    log.emit("req", uid, fc_req, frame_hex=frame.hex())
    sock.settimeout(timeout_s)
    try:
        sock.sendall(frame)
    except OSError as exc:
        log.emit("req", uid, fc_req, error="other",
                 notes=f"请求发送失败（{exc}）——词表外形态如实记 other")
        return {"kind": "send_error", "chunks": chunks[0], "stale_idx": []}

    stale_idx: list[int] = []
    try:
        while True:
            head = recv_exact(sock, 7, chunks)
            if len(head) < 7:
                if not head:
                    log.emit("req", uid, fc_req, error="other",
                             notes="等待响应中对端 orderly 关闭（FIN，0 字节）"
                                   "——词表无精确类目，如实记 other")
                    return {"kind": "closed", "chunks": chunks[0], "stale_idx": stale_idx}
                log.emit("resp", uid, fc_req, error="malformed", expected_len=7,
                         got_len=len(head), frame_hex=head.hex(),
                         notes=f"MBAP 头短读：承诺 7 字节，实收 {len(head)} 字节")
                return {"kind": "short", "chunks": chunks[0], "stale_idx": stale_idx}
            tid_got = int.from_bytes(head[0:2], "big")
            pid = int.from_bytes(head[2:4], "big")
            length = int.from_bytes(head[4:6], "big")
            uid_got = head[6]
            if pid != 0 or not (1 <= length <= 254):
                log.emit("resp", uid_got or uid, fc_req, error="malformed",
                         frame_hex=head.hex(),
                         notes=f"MBAP 头非法（协议标识={pid}，长度={length}）"
                               "——布局解析失败且无短读证据")
                return {"kind": "malformed", "chunks": chunks[0], "stale_idx": stale_idx}
            want = length - 1
            body = tcp_read_body(sock, want, chunks)
            if len(body) < want:
                log.emit("resp", uid_got, fc_req, error="malformed",
                         expected_len=want, got_len=len(body),
                         frame_hex=(head + body).hex(),
                         notes=f"响应正文短读：MBAP 承诺 {want} 字节，"
                               f"实收 {len(body)} 字节")
                return {"kind": "short", "chunks": chunks[0], "stale_idx": stale_idx}
            if tid_got != tid:
                idx = log.emit("resp", uid_got, fc_req, error="other",
                               tid_expected=tid, tid_got=tid_got,
                               frame_hex=(head + body).hex(),
                               notes=f"事务标识不匹配：期待 TID={tid}，先读到 "
                                     f"TID={tid_got}（接收缓冲陈旧帧占管道）")
                stale_idx.append(idx)
                continue                    # 重同步：陈旧帧已消费，真实响应应紧随
            # uid 已随 7B 头消费，body 即响应 PDU
            resp_pdu = body
            fc = body[0]
            if fc & 0x80:
                exc_code = body[1] if len(body) > 1 else None
                log.emit("resp", uid_got, fc_req, exception_code=exc_code,
                         frame_hex=(head + body).hex(),
                         notes=f"异常响应（FC={fc_req}+0x80，异常码={exc_code}）")
                return {"kind": "exception", "exception_code": exc_code,
                        "chunks": chunks[0], "stale_idx": stale_idx}
            log.emit("resp", uid_got, fc, frame_hex=(head + body).hex())
            return {"kind": "ok", "resp_pdu": resp_pdu, "chunks": chunks[0],
                    "stale_idx": stale_idx}
    except socket.timeout:
        log.emit("req", uid, fc_req, error="timeout",
                 notes=f"等待响应超时（>{timeout_s:.1f}s）——从站停答注入")
        return {"kind": "timeout", "chunks": chunks[0], "stale_idx": stale_idx}
    except ConnectionResetError as exc:
        log.emit("req", uid, fc_req, error="reset",
                 notes=f"等待响应中连接被对端重置（{exc}）——RST 注入")
        return {"kind": "reset", "chunks": chunks[0], "stale_idx": stale_idx}


# ---------------------------------------------------------------- TCP 从站/桩
def child_env() -> dict:
    """子进程环境：钉死 UTF-8（从站 fixture 的中文 stdout 落文件才可标记匹配）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class SlaveProc:
    """子进程从站/桩：stdout/stderr 落日志文件，可等待标记、可停。"""

    def __init__(self, python_exe: str, argv: list, workdir: Path, name: str):
        self.dir = workdir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.out_log = self.dir / f"{name}_stdout.log"
        self.err_log = self.dir / f"{name}_stderr.log"
        self._fh = [open(str(self.out_log), "w", encoding="utf-8", newline="\n"),
                    open(str(self.err_log), "w", encoding="utf-8", newline="\n")]
        self.proc = subprocess.Popen([python_exe] + argv, cwd=str(REPO),
                                     stdout=self._fh[0], stderr=self._fh[1],
                                     env=child_env())

    def wait_marker(self, marker: str, seconds: float = 15.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                text = self.out_log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if marker in text:
                return True
            time.sleep(0.1)
        return False

    def wait_port(self, port: int, seconds: float = 10.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            if port_open("127.0.0.1", port):
                return True
            time.sleep(0.1)
        return False

    def stdout_text(self) -> str:
        try:
            return self.out_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def stop(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except OSError:
            pass
        finally:
            for fh in self._fh:
                try:
                    fh.close()
                except OSError:
                    pass


def start_tcp_slave(python_exe: str, port: int, workdir: Path,
                    extra_args: list) -> SlaveProc:
    return SlaveProc(python_exe,
                     [str(TCP_SLAVE), "--port", str(port), "--holding", SEEDS]
                     + list(extra_args), workdir, f"slave{port}")


# ---- 农场内置 TCP 桩（超时/重置/乱码场景的"从站侧"构造，独立端口） ----
def _stub_server(srv: socket.socket, handler, stop: threading.Event) -> None:
    conns: list[socket.socket] = []
    try:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            conns.append(conn)
            threading.Thread(target=handler, args=(conn, stop), daemon=True).start()
    except OSError:
        pass
    finally:
        for c in conns:
            try:
                c.close()
            except OSError:
                pass


def _mute_handler(conn: socket.socket, stop: threading.Event) -> None:
    """静默桩：收了请求不回（持有连接直到场景结束）——从站停答注入。"""
    try:
        while not stop.is_set():
            time.sleep(0.05)
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _rst_handler(conn: socket.socket, stop: threading.Event) -> None:
    """RST 桩：读完请求后以 SO_LINGER(1,0) 关闭——对端收到 RST（中途断连）。"""
    try:
        conn.settimeout(2.0)
        try:
            conn.recv(64)
        except OSError:
            pass
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _garbage_handler(conn: socket.socket, stop: threading.Event) -> None:
    """乱码桩：回一帧协议标识≠0 的垃圾字节——帧布局解析失败注入。"""
    try:
        conn.settimeout(2.0)
        try:
            conn.recv(64)
        except OSError:
            pass
        conn.sendall(GARBAGE_REPLY)
        time.sleep(0.2)
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


class TcpStub:
    """进程内 TCP 桩：主线程先 bind/listen（构造返回即就绪），线程只跑 accept 循环。"""

    def __init__(self, port: int, handler):
        self.stop = threading.Event()
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(4)
        self.srv.settimeout(0.2)
        self.thread = threading.Thread(target=_stub_server,
                                       args=(self.srv, handler, self.stop),
                                       daemon=True)
        self.thread.start()

    def stop_server(self) -> None:
        self.stop.set()
        self.thread.join(timeout=3)
        try:
            self.srv.close()
        except OSError:
            pass


# ---------------------------------------------------------------- RTU 路
_RTU_CACHE = {}


def _rtu_mod():
    """只读复用 fixture 的 kernel32 串口层与 CRC（Windows；导入失败返回 None）。"""
    if "mod" in _RTU_CACHE:
        return _RTU_CACHE["mod"]
    try:
        if str(FIXTURES) not in sys.path:
            sys.path.insert(0, str(FIXTURES))
        import modbus_rtu_slave as mod  # noqa: E402
        _RTU_CACHE["mod"] = mod
        return mod
    except Exception as exc:                     # 非 Windows / 缺依赖：RTU 路 SKIP
        emit(f"FARM\trtu-import\tSKIP\t{exc}")
        _RTU_CACHE["mod"] = None
        return None


def rtu_available() -> bool:
    """com0com 对探测：COM3/COM4 都能独占打开并关闭才算在场。"""
    mod = _rtu_mod()
    if mod is None:
        return False
    for name in ("COM3", "COM4"):
        port = mod.Win32SerialPort(name, 9600)
        try:
            port.open()
        except Exception:
            return False
        finally:
            port.close()
    return True


def rtu_expected_len(buf: bytes, req_fc: int):
    """由响应帧前缀静态定长：异常 5B；FC3/4 5+字节数；FC5/6 定长 8B；不足 None。"""
    if len(buf) < 3:
        return None
    fc = buf[1]
    if fc & 0x80:
        return 5
    if fc == req_fc:
        if req_fc in (FC_READ_HOLDING, 4):
            return 5 + buf[2]
        if req_fc in (5, 6):
            return 8
    return None


def rtu_transact(port, unit: int, req_pdu: bytes, log: CommLogger,
                 timeout_s: float, mod) -> dict:
    """一次 RTU 事务：组帧发送 → 轮询收满预期长度 → CRC 校验 → 落记。"""
    frame = mod.rtu_frame(unit, req_pdu)
    fc_req = req_pdu[0]
    log.emit("req", unit, fc_req, frame_hex=frame.hex())
    port.purge()
    port.write(frame)
    buf = bytearray()
    t0 = time.time()
    expected = None
    while time.time() - t0 < timeout_s:
        chunk = port.read(512)
        if chunk:
            buf.extend(chunk)
            expected = rtu_expected_len(bytes(buf), fc_req)
            if expected is not None and len(buf) >= expected:
                break
        time.sleep(0.002)
    if expected is None or len(buf) < expected:
        log.emit("req", unit, fc_req, error="timeout",
                 notes=f"RTU 等待响应超时（静默 {timeout_s:.1f}s，收 {len(buf)} 字节）"
                       "——从站无响应注入")
        return {"kind": "timeout", "crc_idx": None}
    rsp = bytes(buf[:expected])
    body, crc_lo, crc_hi = rsp[:-2], rsp[-2], rsp[-1]
    calc = mod.crc16(body)
    if calc != (crc_hi << 8) | crc_lo:
        idx = log.emit("resp", unit, fc_req, error="crc", frame_hex=rsp.hex(),
                       notes=f"RTU CRC 校验失败（收 {crc_lo:02X}{crc_hi:02X}，"
                             f"算 {calc:04X}）——corrupt-next 注入")
        return {"kind": "crc", "crc_idx": idx}
    addr, resp_pdu = rsp[0], rsp[1:-2]
    if addr != unit:
        log.emit("resp", addr, fc_req, error="other",
                 notes=f"响应地址 {addr} ≠ 本站 {unit}——词表外形态如实记 other")
        return {"kind": "other_addr", "crc_idx": None}
    fc = resp_pdu[0]
    if fc & 0x80:
        exc_code = resp_pdu[1] if len(resp_pdu) > 1 else None
        log.emit("resp", unit, fc_req, exception_code=exc_code, frame_hex=rsp.hex(),
                 notes=f"RTU 异常响应（异常码={exc_code}）")
        return {"kind": "exception", "exception_code": exc_code, "crc_idx": None}
    log.emit("resp", unit, fc, frame_hex=rsp.hex())
    return {"kind": "ok", "resp_pdu": resp_pdu, "crc_idx": None}


def make_no_respond_stub(path: Path) -> None:
    """生成 RTU no-respond 桩（复用只读 fixture 的串口层；同 G4 门禁做法）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "# -*- coding: utf-8 -*-\n"
        "# 由 scripts/fault_farm.py 生成（rtu_timeout 场景桩）：收帧不回——\n"
        "# 打开串口后只读不写，读到的字节全部丢弃、永不响应，主站必须超时。\n"
        "import sys, time\n"
        f"sys.path.insert(0, r\"{FIXTURES}\")\n"
        "from modbus_rtu_slave import Win32SerialPort  # noqa: E402\n"
        "\n"
        "\n"
        "def main():\n"
        "    p = Win32SerialPort(\"COM4\", 9600)\n"
        "    p.open()\n"
        "    print(\"RTU-NORESPOND-READY port=COM4\", flush=True)\n"
        "    try:\n"
        "        while True:\n"
        "            p.read(512)\n"
        "            time.sleep(0.002)\n"
        "    except KeyboardInterrupt:\n"
        "        pass\n"
        "    finally:\n"
        "        p.close()\n"
        "\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    main()\n")
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(code)


# ---------------------------------------------------------------- 场景结果
class ScenarioResult:
    def __init__(self, name: str, channel: str, injected_fault: str,
                 expected_detection: list):
        self.name = name
        self.channel = channel
        self.injected_fault = injected_fault
        self.expected_detection = expected_detection
        self.status = "PASS"
        self.detail = ""
        self.entries: list[dict] = []
        self.truth: list = []          # [(场景内条目下标, cause)]
        self.assertions: dict = {}

    def fail(self, detail: str) -> "ScenarioResult":
        self.status = "FAIL"
        self.detail = detail
        return self


# 构造==现实自检：cause → 该条目必须满足的结构化签名
def truth_signature_ok(rec: dict, cause: str) -> bool:
    """真值行指向的条目必须携带该 cause 的结构化签名（断言②：构造==现实）。"""
    if cause == "timeout":
        return rec.get("error") == "timeout"
    if cause == "conn_reset":
        return rec.get("error") == "reset"
    if cause == "crc_error":
        return rec.get("error") == "crc"
    if cause == "short_read":
        w, g = rec.get("expected_len"), rec.get("got_len")
        return (rec.get("error") == "malformed"
                and isinstance(w, int) and isinstance(g, int) and g < w)
    if cause == "malformed_frame":
        w, g = rec.get("expected_len"), rec.get("got_len")
        return rec.get("error") == "malformed" and not (
            isinstance(w, int) and isinstance(g, int) and g < w)
    if cause == "stale_frame_tid":
        return (rec.get("error") == "other"
                and rec.get("tid_expected") != rec.get("tid_got")
                and rec.get("tid_expected") is not None)
    if cause == "exception_storm":
        return isinstance(rec.get("exception_code"), int)
    return False


# ---------------------------------------------------------------- TCP 场景
def run_clean(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("clean", "tcp", "none", [])
    slave = start_tcp_slave(args.python_exe, port, workdir, [])
    try:
        if not slave.wait_port(port):
            return r.fail(f"从站 {port} 未就绪：{slave.stdout_text()[-200:]}")
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            plan = [(6, 0, 111), (3, 0, 2), (6, 1, 222), (3, 2, 2)]
            echo_ok = True
            for k, (fc, a, b) in enumerate(plan):
                pdu = pdu_write_reg(a, b) if fc == 6 else pdu_read_holding(a, b)
                out = tcp_transact(sock, tid=k + 1, uid=UNIT_ID, req_pdu=pdu,
                                   log=log, timeout_s=2.0)
                if out["kind"] != "ok":
                    return r.fail(f"事务 {k + 1} 非 ok：{out['kind']}")
                if fc == 6 and out["resp_pdu"] != pdu:
                    echo_ok = False
            r.assertions = {"txns_ok": len(plan), "fc6_echo_ok": echo_ok}
            if not echo_ok:
                return r.fail("FC6 回显不符")
        finally:
            sock.close()
        r.entries = log.entries
    finally:
        slave.stop()
    return r


def run_sticky_stale(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("sticky_stale", "tcp", "sticky_stale", ["stale_frame_tid"])
    n_txn = 4
    slave = start_tcp_slave(args.python_exe, port, workdir,
                            ["--sticky-stale", "1", "--verbose"])
    try:
        if not slave.wait_port(port):
            return r.fail(f"从站 {port} 未就绪：{slave.stdout_text()[-200:]}")
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            for k in range(n_txn):
                out = tcp_transact(sock, tid=k + 1, uid=UNIT_ID,
                                   req_pdu=pdu_read_holding(0, 2),
                                   log=log, timeout_s=2.0)
                # 构造推论：--sticky-stale 1 ⇒ 每响应附发旧 TID（=当前-1）陈旧帧，
                # 故事务 k≥2 必先读到上一响应的陈旧帧（恰好 1 条），事务 1 无。
                want_stale = 0 if k == 0 else 1
                if len(out["stale_idx"]) != want_stale:
                    return r.fail(f"事务 {k + 1} 陈旧帧数 {len(out['stale_idx'])}"
                                  f" ≠ 构造推论 {want_stale}")
                if out["kind"] != "ok":
                    return r.fail(f"事务 {k + 1} 未恢复 ok：{out['kind']}")
                for idx in out["stale_idx"]:
                    r.truth.append((idx, "stale_frame_tid"))
        finally:
            sock.close()
        r.entries = log.entries
        markers = slave.stdout_text().count("粘包注入")
        r.assertions = {"txns": n_txn, "stale_truth_rows": len(r.truth),
                        "slave_marker_粘包注入": markers}
        if markers != n_txn:
            return r.fail(f"从站粘包注入标记 {markers} ≠ {n_txn}（注入①未证实）")
    finally:
        slave.stop()
    return r


def run_fragment_byte1(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("fragment_byte1", "tcp", "fragment_byte1", [])
    n_txn = 3
    slave = start_tcp_slave(args.python_exe, port, workdir, ["--fragment", "byte1"])
    try:
        if not slave.wait_port(port):
            return r.fail(f"从站 {port} 未就绪：{slave.stdout_text()[-200:]}")
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            chunk_max = 0
            for k in range(n_txn):
                out = tcp_transact(sock, tid=k + 1, uid=UNIT_ID,
                                   req_pdu=pdu_read_holding(0, 2),
                                   log=log, timeout_s=3.0)
                if out["kind"] != "ok":
                    return r.fail(f"事务 {k + 1} 非 ok：{out['kind']}（时序容忍失守）")
                chunk_max = max(chunk_max, out["chunks"])
        finally:
            sock.close()
        r.entries = log.entries
        r.assertions = {"txns_ok": n_txn, "max_recv_chunks": chunk_max,
                        "drip_real": chunk_max >= 5}
        if chunk_max < 5:
            return r.fail(f"响应最大 recv 分段 {chunk_max} < 5——滴流注入①未证实")
    finally:
        slave.stop()
    return r


def _read_jsonl_list(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _probe_only_run(python_exe: str, script: Path, host: str, port: int,
                    seq_base: int, out_path: Path) -> tuple[int, int, int]:
    """跑一次 probe-only 探针（script 可为原件或沙盒副本）→ (退出码, 条目数, 短读数)。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [python_exe, str(script), "--probe-only", "--host", host,
         "--port", str(port), "--seq-base", str(seq_base), "--out", str(out_path)],
        cwd=str(REPO), capture_output=True, timeout=30, env=child_env())
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    entries = 0
    shorts = 0
    m = re.search(r"entries=(\d+)", out)
    if m:
        entries = int(m.group(1))
    m = re.search(r"short=(\d+)", out)
    if m:
        shorts = int(m.group(1))
    return proc.returncode, entries, shorts, err[-400:]


def run_short_read(args, workdir: Path, port: int) -> ScenarioResult:
    """short_read：客户端劣化注入（gate_negative 沙盒副本纪律）。

    阳性对照 = 原件同路径 probe-only（必须零短读）；负向 = 沙盒副本
    （tcp_read_body 被改写为只读 length-3，三重断言后运行）必须产生短读。
    """
    r = ScenarioResult("short_read", "tcp", "short_read", ["short_read"])
    slave = start_tcp_slave(args.python_exe, port, workdir, [])
    try:
        if not slave.wait_port(port):
            return r.fail(f"从站 {port} 未就绪：{slave.stdout_text()[-200:]}")
        sb_dir = workdir / "sandbox"
        sb_dir.mkdir(parents=True, exist_ok=True)
        copy_py = sb_dir / "fault_farm_shortread.py"
        # ---- 副本注入 + 三重断言（①替换计数≥1 ②内容变化 ③探针标记在场）----
        src_text = Path(__file__).read_text(encoding="utf-8")
        hits = re.findall(SHORT_READ_PATTERN, src_text)
        if len(hits) < 1:
            return r.fail("注入点未命中：tcp_read_body 的 return 行不存在")
        after = re.sub(SHORT_READ_PATTERN, SHORT_READ_REPLACEMENT, src_text, count=1)
        if after == src_text:
            return r.fail("注入后内容未变化")
        if SHORT_READ_MARKER not in after:
            return r.fail("注入后缺探针标记 " + SHORT_READ_MARKER)
        copy_py.write_text(after, encoding="utf-8", newline="\n")
        # ---- 阳性对照：原件同路径必须零短读 ----
        ctrl_path = workdir / "probe_control.jsonl"
        rc_c, n_c, short_c, err_c = _probe_only_run(args.python_exe, Path(__file__),
                                                    "127.0.0.1", port, 0, ctrl_path)
        if rc_c != 0 or short_c != 0:
            return r.fail(f"阳性对照失败（rc={rc_c}, short={short_c}）：{err_c}"
                          "——失败并非来自注入")
        # ---- 负向：沙盒副本必须产生构造性短读 ----
        deg_path = workdir / "probe_degraded.jsonl"
        rc_d, n_d, short_d, err_d = _probe_only_run(args.python_exe, copy_py,
                                                    "127.0.0.1", port, n_c, deg_path)
        if rc_d != 0:
            return r.fail(f"沙盒副本探针退出码 {rc_d}：{err_d}")
        if short_d != 1:
            return r.fail(f"沙盒副本短读条数 {short_d} ≠ 1（构造性短读未落地）：{err_d}")
        ctrl_entries = _read_jsonl_list(ctrl_path)
        deg_entries = _read_jsonl_list(deg_path)
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        log.entries = list(ctrl_entries) + list(deg_entries)
        log.seq = len(log.entries)
        r.entries = log.entries
        short_idx = None
        for i, rec in enumerate(r.entries):
            if rec.get("error") == "malformed":
                short_idx = i
        if short_idx is None:
            return r.fail("合并日志中找不到短读条目")
        r.truth.append((short_idx, "short_read"))
        w = r.entries[short_idx].get("expected_len")
        g = r.entries[short_idx].get("got_len")
        r.assertions = {"inject_hits": len(hits), "control_short": short_c,
                        "degraded_short": short_d, "expected_len": w, "got_len": g,
                        "marker": SHORT_READ_MARKER}
        if not (isinstance(w, int) and isinstance(g, int) and g < w):
            return r.fail("短读条目缺 expected_len/got_len 结构化证据")
    finally:
        slave.stop()
    return r


def run_timeout(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("timeout", "tcp", "timeout", ["timeout"])
    stub = TcpStub(port, _mute_handler)
    try:
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            t0 = time.time()
            out = tcp_transact(sock, tid=1, uid=UNIT_ID,
                               req_pdu=pdu_read_holding(0, 2),
                               log=log, timeout_s=1.2)
            elapsed = time.time() - t0
        finally:
            sock.close()
        if out["kind"] != "timeout":
            return r.fail(f"期望 timeout，实得 {out['kind']}")
        if elapsed < 1.1:
            return r.fail(f"静默时长 {elapsed:.2f}s < 1.1s——停答注入①未证实")
        r.entries = log.entries
        r.truth.append((1, "timeout"))
        r.assertions = {"kind": out["kind"], "silent_s": round(elapsed, 2)}
    finally:
        stub.stop_server()
    return r


def run_conn_reset(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("conn_reset", "tcp", "conn_reset", ["conn_reset"])
    stub = TcpStub(port, _rst_handler)
    try:
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            out = tcp_transact(sock, tid=1, uid=UNIT_ID,
                               req_pdu=pdu_read_holding(0, 2),
                               log=log, timeout_s=2.0)
        finally:
            sock.close()
        if out["kind"] != "reset":
            return r.fail(f"期望 reset，实得 {out['kind']}（RST 注入未达）")
        r.entries = log.entries
        r.truth.append((1, "conn_reset"))
        r.assertions = {"kind": out["kind"]}
    finally:
        stub.stop_server()
    return r


def run_malformed_reply(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("malformed_reply", "tcp", "malformed_reply",
                       ["malformed_frame"])
    stub = TcpStub(port, _garbage_handler)
    try:
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            out = tcp_transact(sock, tid=1, uid=UNIT_ID,
                               req_pdu=pdu_read_holding(0, 2),
                               log=log, timeout_s=2.0)
        finally:
            sock.close()
        if out["kind"] != "malformed":
            return r.fail(f"期望 malformed，实得 {out['kind']}")
        r.entries = log.entries
        r.truth.append((1, "malformed_frame"))
        r.assertions = {"kind": out["kind"], "garbage_head": GARBAGE_REPLY[:7].hex()}
    finally:
        stub.stop_server()
    return r


def run_exception_sweep(args, workdir: Path, port: int) -> ScenarioResult:
    r = ScenarioResult("exception_sweep", "tcp", "exception_sweep",
                       ["exception_storm"])
    n_txn = 4
    want_codes = [0x01, 0x02, 0x03, 0x05]     # 扫掠序列前 4 个（01,02,03,05,06,08,0A,0B）
    slave = start_tcp_slave(args.python_exe, port, workdir,
                            ["--exception-sweep", "--verbose"])
    try:
        if not slave.wait_port(port):
            return r.fail(f"从站 {port} 未就绪：{slave.stdout_text()[-200:]}")
        log = CommLogger("tcp", f"127.0.0.1:{port}")
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            codes = []
            first_exc_idx = None
            for k in range(n_txn):
                out = tcp_transact(sock, tid=k + 1, uid=UNIT_ID,
                                   req_pdu=pdu_read_holding(0, 2),
                                   log=log, timeout_s=2.0)
                if out["kind"] != "exception":
                    return r.fail(f"事务 {k + 1} 非异常响应：{out['kind']}")
                codes.append(out["exception_code"])
                if first_exc_idx is None:
                    first_exc_idx = 1 + 2 * k     # 构造推论：第 k 事务的 resp 下标
            r.entries = log.entries
            if codes != want_codes:
                return r.fail(f"异常码 {codes} ≠ 扫掠构造 {want_codes}")
            r.truth.append((first_exc_idx, "exception_storm"))
        finally:
            sock.close()
        markers = slave.stdout_text().count("异常码扫掠: 第")   # 逐请求行（不含启动回显）
        r.assertions = {"txns": n_txn, "codes": codes,
                        "slave_marker_异常码扫掠": markers}
        if markers != n_txn:
            return r.fail(f"从站扫掠标记 {markers} ≠ {n_txn}（注入①未证实）")
    finally:
        slave.stop()
    return r


# ---------------------------------------------------------------- RTU 场景
def run_crc_corrupt(args, workdir: Path, seq_base: int) -> ScenarioResult:
    r = ScenarioResult("crc_corrupt", "rtu", "crc_corrupt", ["crc_error"])
    mod = _rtu_mod()
    if mod is None:
        r.status = "SKIP"
        r.detail = "RTU 串口层不可用"
        return r
    slave = SlaveProc(args.python_exe,
                      [str(RTU_SLAVE), "--port", "COM4", "--corrupt-next"],
                      workdir, "rtu_slave")
    port = None
    try:
        if not slave.wait_marker("RTU-SLAVE-READY"):
            return r.fail(f"RTU 从站未就绪：{slave.stdout_text()[-200:]}")
        time.sleep(0.4)                       # 串口句柄/缓冲稳定（同 G4 门禁）
        port = mod.Win32SerialPort("COM3", 9600)
        port.open()
        log = CommLogger("rtu", "COM3", seq_base=seq_base)
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        # 事务 1：从站 --corrupt-next ⇒ 首响应 CRC 必坏（构造推论 → crc_error）
        out1 = rtu_transact(port, UNIT_ID, pdu_read_holding(0, 2), log, 1.5, mod)
        if out1["kind"] != "crc" or out1["crc_idx"] is None:
            return r.fail(f"事务 1 期望 crc，实得 {out1['kind']}")
        r.truth.append((out1["crc_idx"], "crc_error"))
        # 事务 2/3：注入仅一帧 ⇒ 之后必须恢复正常（恢复检查）
        out2 = rtu_transact(port, UNIT_ID, pdu_read_holding(0, 2), log, 1.5, mod)
        if out2["kind"] != "ok":
            return r.fail(f"事务 2 期望恢复正常，实得 {out2['kind']}")
        out3 = rtu_transact(port, UNIT_ID, pdu_write_reg(5, 777), log, 1.5, mod)
        if out3["kind"] != "ok" or out3["resp_pdu"] != pdu_write_reg(5, 777):
            return r.fail("事务 3 FC6 回显不符")
        r.entries = log.entries
        markers = slave.stdout_text().count("本响应 CRC 已故意破坏")  # 注入执行行（不含启动回显）
        r.assertions = {"slave_marker_corrupt": markers, "recovered": True}
        if markers != 1:
            return r.fail(f"从站坏 CRC 标记 {markers} ≠ 1（注入①未证实）")
    finally:
        if port is not None:
            port.close()
        slave.stop()
    return r


def run_rtu_timeout(args, workdir: Path, seq_base: int) -> ScenarioResult:
    r = ScenarioResult("rtu_timeout", "rtu", "rtu_timeout", ["timeout"])
    mod = _rtu_mod()
    if mod is None:
        r.status = "SKIP"
        r.detail = "RTU 串口层不可用"
        return r
    stub_py = workdir / "no_respond_stub.py"
    make_no_respond_stub(stub_py)
    stub = SlaveProc(args.python_exe, [str(stub_py)], workdir, "no_respond")
    port = None
    try:
        if not stub.wait_marker("RTU-NORESPOND-READY"):
            return r.fail(f"no-respond 桩未就绪：{stub.stdout_text()[-200:]}")
        time.sleep(0.4)
        port = mod.Win32SerialPort("COM3", 9600)
        port.open()
        log = CommLogger("rtu", "COM3", seq_base=seq_base)
        r.entries = log.entries      # 别名：失败路径也保留已落条目（现场可查）
        t0 = time.time()
        out = rtu_transact(port, UNIT_ID, pdu_read_holding(0, 2), log, 1.5, mod)
        elapsed = time.time() - t0
        if out["kind"] != "timeout":
            return r.fail(f"期望 timeout，实得 {out['kind']}")
        if elapsed < 1.4:
            return r.fail(f"静默时长 {elapsed:.2f}s < 1.4s——停答注入①未证实")
        r.entries = log.entries
        r.truth.append((1, "timeout"))
        r.assertions = {"kind": out["kind"], "silent_s": round(elapsed, 2)}
    finally:
        if port is not None:
            port.close()
        stub.stop()
    return r


# ---------------------------------------------------------------- probe-only 模式
def run_probe_only(args) -> int:
    """沙盒探针模式：一次 FC3 事务，comm_log 条目落盘（短读注入由副本文件承载）。"""
    log = CommLogger("tcp", f"{args.host}:{args.port}", seq_base=args.seq_base)
    sock = socket.create_connection((args.host, args.port), timeout=3)
    try:
        out = tcp_transact(sock, tid=1, uid=UNIT_ID, req_pdu=pdu_read_holding(0, 2),
                           log=log, timeout_s=2.0)
    finally:
        sock.close()
    write_jsonl(Path(args.out), log.entries)
    shorts = sum(1 for e in log.entries
                 if e.get("error") == "malformed" and isinstance(e.get("got_len"), int)
                 and isinstance(e.get("expected_len"), int)
                 and e["got_len"] < e["expected_len"])
    emit(f"PROBE-ONLY\tentries={len(log.entries)}\tshort={shorts}\tkind={out['kind']}")
    return 0


# ---------------------------------------------------------------- selftest
def run_selftest() -> int:
    """农场自检：帧构造黄金值 + 条目发射器过契约门（不拉网、不起从站）。"""
    ok = True
    f = mbap(7, 1, pdu_read_holding(0, 2))
    want = "000700000006010300000002"
    good = f.hex() == want
    ok &= good
    emit(f"  selftest 黄金帧: {f.hex()} [{'OK ' if good else 'BAD'}]（期望 {want}）")
    log = CommLogger("tcp", "127.0.0.1:15030")
    log.emit("req", 1, 3, frame_hex="000100000006010301000002")
    log.emit("resp", 1, 3, frame_hex="00010000000701030412345678")
    log.emit("req", 1, 3, error="timeout", notes="等待响应超时")
    vcl = _load_validator()
    if vcl is None:
        emit("  selftest 契约裁判不可载入 [BAD]")
        return 1
    contract = vcl.load_contract(None)
    v, _ = vcl.validate_records(log.entries, contract)
    clean = not v
    ok &= clean
    emit(f"  selftest 契约校验: {len(log.entries)} 条样例违规 {len(v)} "
         f"[{'OK ' if clean else 'BAD'}]")
    for s in v:
        emit("    " + s)
    emit(f"fault_farm --selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _load_validator():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import validate_comm_log as vcl  # noqa: E402
    return vcl


# ---------------------------------------------------------------- 农场主编排
TCP_SCENARIOS = ("clean", "sticky_stale", "fragment_byte1", "short_read",
                 "timeout", "conn_reset", "malformed_reply", "exception_sweep")


def run_farm(args) -> int:
    t0 = time.time()
    out_dir = Path(args.out).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for need in (TCP_SLAVE, RTU_SLAVE,
                 SCRIPTS / "validate_comm_log.py",
                 REPO / "scripts" / "eval_forensics.py"):
        if not need.is_file():
            emit(f"[farm-fail] 缺少必需文件：{need}")
            return EXIT_ENV

    results: list[ScenarioResult] = []
    port = find_free_port(PORT_BASE)

    # ---- TCP 路：每场景独立端口（独立流，seq 各自从 0 起）----
    runners = {"clean": run_clean, "sticky_stale": run_sticky_stale,
               "fragment_byte1": run_fragment_byte1, "short_read": run_short_read,
               "timeout": run_timeout, "conn_reset": run_conn_reset,
               "malformed_reply": run_malformed_reply,
               "exception_sweep": run_exception_sweep}
    for name in TCP_SCENARIOS:
        port = find_free_port(port + 1)
        workdir = out_dir / name
        emit(f"FARM\trun\t{name}\tport={port}")
        try:
            r = runners[name](args, workdir, port)
        except Exception as exc:              # 场景内未捕获异常=场景失败，不炸农场
            r = ScenarioResult(name, "tcp", name, [])
            r.fail(f"场景异常：{type(exc).__name__}: {exc}")
        results.append(r)

    # ---- RTU 路：先探测 com0com 对，缺失整路 SKIP（同 G4 门禁纪律）----
    rtu_ok = (not args.skip_rtu) and rtu_available()
    if rtu_ok:
        emit("FARM\trtu\tCOM3/COM4 在场（com0com）")
        seq_base = 0
        r1 = run_crc_corrupt(args, out_dir / "crc_corrupt", seq_base)
        results.append(r1)
        seq_base += len(r1.entries)           # 合并后同流 seq 必须续走（I1）
        r2 = run_rtu_timeout(args, out_dir / "rtu_timeout", seq_base)
        results.append(r2)
    else:
        emit("FARM\trtu\tCOM3/COM4 缺失 → crc_corrupt/rtu_timeout 记 SKIP")
        s1 = ScenarioResult("crc_corrupt", "rtu", "crc_corrupt", ["crc_error"])
        s1.status = "SKIP"
        s1.detail = "COM3/COM4 缺失（com0com 不在场），RTU 契约未实跑"
        s2 = ScenarioResult("rtu_timeout", "rtu", "rtu_timeout", ["timeout"])
        s2.status = "SKIP"
        s2.detail = s1.detail
        results.extend([s1, s2])

    # ---- 合并产物：行号 L<n> 是检出与判卷的统一坐标 ----
    vcl = _load_validator()
    contract = vcl.load_contract(None)
    all_entries: list[dict] = []
    all_truth: list[dict] = []
    index: list[dict] = []
    offset = 0
    for r in results:
        # 断言②：构造==现实（真值行指向的条目必须携带该 cause 的结构化签名）
        sig_bad = [f"#{i}:{c}" for i, c in r.truth
                   if i >= len(r.entries) or not truth_signature_ok(r.entries[i], c)]
        if r.status == "PASS" and sig_bad:
            r.fail(f"构造==现实断言失守：{sig_bad}")
        # 断言③：场景日志必须过契约门（绝不带病出农场）
        if r.status == "PASS" and r.entries:
            v, _ = vcl.validate_records(r.entries, contract)
            if v:
                r.fail(f"场景日志契约违规 {len(v)} 条（采集端缺陷就地暴露）：{v[:3]}")
        truth_rows = [{"id": f"L{offset + i + 1}", "cause": c} for i, c in r.truth]
        write_jsonl(out_dir / r.name / "comm_log.jsonl", r.entries)
        write_json(out_dir / r.name / "label.json", {
            "scenario": r.name, "channel": r.channel,
            "injected_fault": r.injected_fault,
            "expected_detection": r.expected_detection, "status": r.status,
            "detail": r.detail, "assertions": r.assertions,
            "entries": len(r.entries),
            "truth": [{"index": i, "cause": c} for i, c in r.truth]})
        index.append({"scenario": r.name, "channel": r.channel,
                      "injected_fault": r.injected_fault,
                      "expected_detection": r.expected_detection,
                      "status": r.status, "detail": r.detail,
                      "start_line": offset + 1, "end_line": offset + len(r.entries),
                      "truth_rows": len(truth_rows)})
        all_entries.extend(r.entries)
        all_truth.extend(truth_rows)
        offset += len(r.entries)

    write_jsonl(out_dir / "comm_log_all.jsonl", all_entries)
    write_jsonl(out_dir / "truth_all.jsonl", all_truth)
    write_json(out_dir / "scenario_index.json", index)
    write_json(out_dir / "farm_summary.json", {
        "generated_at": utc_iso(),
        "scenarios": [{k: i[k] for k in ("scenario", "injected_fault",
                                         "expected_detection", "status", "detail")}
                      for i in index],
        "entries_total": len(all_entries), "truth_rows": len(all_truth)})
    n1 = next((t for t in all_truth if t["cause"] == "timeout"), None)
    if n1 is None:
        emit("[farm-fail] N1 错标目标（cause=timeout 真值行）不存在——超时场景必须产出")
        return EXIT_ENV
    write_json(out_dir / "n1_target.json", n1)

    n_pass = sum(1 for r in results if r.status == "PASS")
    n_skip = sum(1 for r in results if r.status == "SKIP")
    n_fail = sum(1 for r in results if r.status == "FAIL")
    for r in results:
        emit(f"FARM\t{r.name}\t{r.status}\tinjected={r.injected_fault}"
             f"\texpect={','.join(r.expected_detection) or 'none'}"
             f"\tentries={len(r.entries)}\ttruth={len(r.truth)}"
             f"\t{r.detail[:120]}")
    emit(f"FARM-SUMMARY\tpass={n_pass}\tskip={n_skip}\tfail={n_fail}"
         f"\tentries={len(all_entries)}\ttruth_rows={len(all_truth)}"
         f"\telapsed={time.time() - t0:.1f}s")
    emit(f"构造性真值：{len(all_truth)} 行全部由注入参数推出并逐行过「构造==现实」"
         f"自检；农场不证明现场故障分布（Phase 2/3 边界）。")
    return EXIT_OK if n_fail == 0 else EXIT_SCENARIO


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="故障注入农场 Phase 1：构造性真值的带标签 comm_log 批产（零依赖）")
    ap.add_argument("--out", default=str(REPO / "out" / "farm"), help="产出目录")
    ap.add_argument("--python-exe", "--python", dest="python_exe",
                    default=sys.executable, help="从站/桩/沙盒探针用 python")
    ap.add_argument("--skip-rtu", action="store_true", help="强制跳过 RTU 路")
    ap.add_argument("--probe-only", action="store_true",
                    help="沙盒探针模式：对 --host/--port 打一枪 FC3 并落盘条目")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--seq-base", type=int, default=0)
    ap.add_argument("--selftest", action="store_true", help="帧黄金值+契约门自检")
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        if args.selftest:
            return run_selftest()
        if args.probe_only:
            if not args.port:
                emit("[farm-fail] --probe-only 需要 --port")
                return EXIT_ENV
            return run_probe_only(args)
        return run_farm(args)
    except EnvironmentError as exc:
        emit(f"[farm-fail] 环境错误：{exc}")
        return EXIT_ENV
    except Exception as exc:                  # 兜底：异常路径退出码 ≠ 0，绝不崩溃即过
        emit(f"[farm-broken] 未捕获异常：{type(exc).__name__}: {exc}")
        return EXIT_BROKEN


if __name__ == "__main__":
    sys.exit(main())
