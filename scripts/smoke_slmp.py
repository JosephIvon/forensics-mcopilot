# -*- coding: utf-8 -*-
"""SLMP（3E 帧·二进制码）契约桩 + csc 编译 + 契约测试（scripts 同构 smoke_modbus.py）。

桩 = 最小 3E 对端（自建契约桩，非第三方模拟器——TODO[需实测] T1 同源纪律）：
- 指令 0401H/0000H 读字软元件、1401H/0000H 写字软元件；D 区预置 D100=0x1234、D101=0x5678、D102=0x9ABC
- 编号越界（D>=2000）回结束代码 C059H 类非 0 值（桩自定义码，语义核对留真机）
- 未知指令回非 0 结束代码（0xC0C0 桩标记）
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
HOST, PORT = "127.0.0.1", 10270

REGS: dict[int, int] = {100: 0x1234, 101: 0x5678, 102: 0x9ABC}
LOG: list[str] = []


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


def handle(conn: socket.socket) -> None:
    try:
        while True:
            head = recv_exact(conn, 9)
            sub, net, pc, io, multi, length = struct.unpack("<HBBHBH", head)
            print(f"[stub ] head={head.hex()} len={length}，再收 {length} 字节 body……")
            body = recv_exact(conn, length)
            print(f"[stub ] body={body.hex()}")
            cmd, subcmd = struct.unpack("<HH", body[2:6])
            resp_pdu = dispatch(cmd, subcmd, body[6:])
            # 响应头：副头部改 D000（正常响应），net/PC/IO/多站 回显，长度=EndCode+数据
            resp = struct.pack("<HBBHBH", 0xD000, net, pc, io, multi, len(resp_pdu) + 2) + resp_pdu
            out = f"  -> end={resp_pdu[:2].hex()} datalen={len(resp_pdu)}"
            LOG.append(out)
            print("[stub ]", out)
            conn.sendall(resp)
    except (ConnectionResetError, OSError):
        pass
    except Exception:
        import traceback
        LOG.append("EXC:\n" + traceback.format_exc())
    finally:
        conn.close()


def dispatch(cmd: int, subcmd: int, access: bytes) -> bytes:
    if cmd == 0x0401 and subcmd == 0x0000:      # 批量读字
        code = access[0]
        dev = access[1] | (access[2] << 8) | (access[3] << 16)
        count = struct.unpack("<H", access[4:6])[0]
        if code != 0xA8 or dev + count > 2000 or count > 960:
            return struct.pack("<H", 0xC059)    # 非法参数类（桩自定义码，语义待真机核对）
        data = b"".join(struct.pack("<H", REGS.get(dev + i, 0)) for i in range(count))
        return struct.pack("<H", 0x0000) + data
    if cmd == 0x1401 and subcmd == 0x0000:      # 批量写字
        code = access[0]
        dev = access[1] | (access[2] << 8) | (access[3] << 16)
        count = struct.unpack("<H", access[4:6])[0]
        if code != 0xA8 or dev + count > 2000 or count > 960:
            return struct.pack("<H", 0xC059)
        for i in range(count):
            REGS[dev + i] = struct.unpack("<H", access[6 + i * 2:8 + i * 2])[0]
        return struct.pack("<H", 0x0000)
    return struct.pack("<H", 0xC0C0)            # 未知指令（桩标记）


def find_csc() -> Path:
    for base in (r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319",
                 r"C:\Windows\Microsoft.NET\Framework\v4.0.30319"):
        p = Path(base) / "csc.exe"
        if p.exists():
            return p
    raise SystemExit("未找到 csc.exe")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(2)
    threading.Thread(target=accept_loop, args=(srv,), daemon=True).start()
    print(f"[stub] SLMP 契约桩就绪 {HOST}:{PORT}")

    csc = find_csc()
    exe = OUT / "SlmpContracts.exe"
    srcs = [str(TPL / "SlmpTcpClient.cs"), str(TPL / "SlmpContracts.cs")]
    print("[csc ]", csc.name, "编译 SLMP 客户端 + 契约测试……")
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
    (OUT / "slmp_stub_log.txt").write_text("\n".join(LOG), encoding="utf-8")
    srv.close()
    if rc == 0:
        print("[PASS] P2 SLMP：编译 + 契约桩 + 契约断言（C1-C9）通过；C10 位单位/真机 TODO[需实测]")
        return 0
    print("[FAIL] SLMP 契约未过")
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
