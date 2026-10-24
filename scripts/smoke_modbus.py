# -*- coding: utf-8 -*-
"""P1 验收门「对模拟器冒烟」：起 Modbus TCP 测试桩 → csc 编译客户端 → 跑冒烟断言。

桩 = 最小 TCP slave（P2 换 diagslave 正式模拟器）：FC01/02/03/04/05/06/0F/10，
寄存器地址 >=100 回异常 02（ILLEGAL DATA ADDRESS）——供客户端验证异常翻译链。
"""
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "knowledge" / "templates" / "protocol"
OUT = ROOT / "out" / "protocol_smoke"
HOST, PORT = "127.0.0.1", 15020

REGS: dict[int, int] = {0: 0x1234, 1: 0x5678, 2: 0x9ABC, 3: 0xFF00}
COILS: dict[int, bool] = {}
LOG: list[str] = []


def handle(conn: socket.socket) -> None:
    try:
        while True:
            head = recv_exact(conn, 7)
            txn, pid, length, unit = struct.unpack(">HHHB", head)
            body = recv_exact(conn, length - 1)
            func, pdu = body[0], body[1:]
            line = f"txn={txn} len={length} func=0x{func:02X} pdu={pdu.hex()}"
            LOG.append(line)
            print("[stub ]", line)
            resp_pdu = dispatch(func, pdu)
            resp = struct.pack(">HHHB", txn, 0, len(resp_pdu) + 1, unit) + resp_pdu
            line = f"  -> resp func=0x{resp_pdu[0]:02X} pdu={resp_pdu.hex()}"
            LOG.append(line)
            print("[stub ]", line)
            conn.sendall(resp)
    except (ConnectionResetError, OSError):
        pass
    except Exception:
        import traceback
        LOG.append("EXC:\n" + traceback.format_exc())
    finally:
        conn.close()


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


def dispatch(func: int, pdu: bytes) -> bytes:
    if func == 0x03 or func == 0x04:
        addr, count = struct.unpack(">HH", pdu)
        if count < 1 or count > 125:
            return exception(func, 0x03)      # 数量非法 → ILLEGAL DATA VALUE（规范 FC03: 1 to 125）
        if addr + count > 100:
            return exception(func, 0x02)      # 地址越界 → ILLEGAL DATA ADDRESS
        vals = bytes()
        for i in range(count):
            vals += struct.pack(">H", REGS.get(addr + i, 0))
        return bytes([func, len(vals)]) + vals
    if func == 0x01 or func == 0x02:
        addr, count = struct.unpack(">HH", pdu)
        if count < 1 or count > 2000:
            return exception(func, 0x03)
        if addr + count > 100:
            return exception(func, 0x02)
        nb = (count + 7) // 8
        data = bytearray(nb)
        for i in range(count):
            if COILS.get(addr + i, False):
                data[i // 8] |= 1 << (i % 8)
        return bytes([func, nb]) + bytes(data)
    if func == 0x06:
        addr, val = struct.unpack(">HH", pdu)
        if addr >= 100:
            return exception(func, 0x02)
        REGS[addr] = val
        return bytes([func]) + pdu          # 响应 = func + echo（桩此前丢 func 字节的 bug）
    if func == 0x10:
        addr, count, nbytes = struct.unpack(">HHB", pdu[:5])
        if addr + count > 100 or count < 1 or nbytes != count * 2:
            return exception(func, 0x02)
        for i in range(count):
            REGS[addr + i] = struct.unpack(">H", pdu[5 + i * 2:7 + i * 2])[0]
        return bytes([func]) + pdu[:4]
    if func == 0x0F:
        addr, count, nbytes = struct.unpack(">HHB", pdu[:5])
        if addr + count > 100:
            return exception(func, 0x02)
        for i in range(count):
            COILS[addr + i] = bool(pdu[5 + i // 8] >> (i % 8) & 1)
        return bytes([func]) + pdu[:4]
    if func == 0x05:
        addr, val = struct.unpack(">HH", pdu)
        if addr >= 100:
            return exception(func, 0x02)
        COILS[addr] = (val == 0xFF00)
        return bytes([func]) + pdu
    return exception(func, 0x01)  # ILLEGAL FUNCTION


def exception(func: int, code: int) -> bytes:
    return bytes([func | 0x80, code])


def find_csc() -> Path:
    for base in (r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319",
                 r"C:\Windows\Microsoft.NET\Framework\v4.0.30319"):
        p = Path(base) / "csc.exe"
        if p.exists():
            return p
    raise SystemExit("未找到 csc.exe（.NET Framework 编译器）")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(2)
    threading.Thread(target=accept_loop, args=(srv,), daemon=True).start()
    print(f"[stub] 测试桩就绪 {HOST}:{PORT}")

    csc = find_csc()
    exe = OUT / "ModbusContracts.exe"
    srcs = [str(TPL / "ModbusTcpClient.cs"), str(TPL / "ModbusRtuClient.cs"),
            str(TPL / "ModbusFrameTests.cs"), str(TPL / "ModbusContracts.cs")]
    print("[csc ]", csc.name, "编译客户端 + 帧测试 + 契约测试……")
    r = subprocess.run([str(csc), "/nologo", "/t:exe", f"/out:{exe}"] + srcs,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return 1
    print("[csc ] 编译通过")

    run = subprocess.run([str(exe)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=60)
    print(run.stdout)
    if run.stderr.strip():
        print("[exe stderr]", run.stderr[:500])
    rc = run.returncode
    (OUT / "stub_log.txt").write_text("\n".join(LOG), encoding="utf-8")
    print("[stub] 事务日志 → out/protocol_smoke/stub_log.txt")
    srv.close()
    if rc == 0:
        print("[PASS] P2 契约：编译 + 契约桩 + 全部契约断言（C1-C10）通过")
        return 0
    print("[FAIL] 契约未过")
    return 1


def accept_loop(srv: socket.socket) -> None:
    while True:
        try:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
        except OSError:
            return


if __name__ == "__main__":
    sys.exit(main())
