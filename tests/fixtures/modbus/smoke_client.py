#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
smoke_client.py —— 零依赖 Modbus TCP 主站冒烟测试(仅用 Python 标准库)
================================================================================

配套 modbus_tcp_slave.py 使用:
  1. 启动从站(FC03 用例校验种子,必须带 --holding):
       python modbus_tcp_slave.py --holding 0=1234,1=5678
  2. 运行冒烟:
       python smoke_client.py [--host 127.0.0.1] [--port 15020]

内容
  * 对 8 个功能码(1/2/3/4/5/6/15/16)各发起请求并逐项校验:
    MBAP 事务/协议/单元标识回显 + 响应结构与数据回读一致性;
  * 异常场景:读不存在的地址(20000 >= 默认区大小 10000)-> 期望
    功能码|0x80 + 异常码 02;另附参数非法 -> 异常码 03 的附加用例;
  * 打印 PASS/FAIL 矩阵;全部通过退出码 0,否则 1。
================================================================================
"""

import argparse
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 15020


class SmokeClient:
    """极简 Modbus TCP 主站:只负责 组帧/收帧 + MBAP 回显校验。"""

    def __init__(self, host, port, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.tid = 0                      # 事务标识,每发一帧自增

    def close(self):
        self.sock.close()

    @staticmethod
    def _recv_exact(sock, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("连接被对端关闭")
            buf += chunk
        return bytes(buf)

    def transact(self, pdu, unit=1):
        """发送一帧请求并收取响应;校验 MBAP 回显后返回响应 PDU(bytes)。"""
        self.tid = (self.tid + 1) & 0xFFFF
        frame = (self.tid.to_bytes(2, "big")
                 + (0).to_bytes(2, "big")                    # 协议标识 0
                 + (1 + len(pdu)).to_bytes(2, "big")         # 长度 = 单元标识 + PDU
                 + bytes([unit]) + pdu)
        self.sock.sendall(frame)
        head = self._recv_exact(self.sock, 7)                # MBAP 头
        rid = int.from_bytes(head[0:2], "big")
        pid = int.from_bytes(head[2:4], "big")
        length = int.from_bytes(head[4:6], "big")
        uid = head[6]
        if rid != self.tid:
            raise AssertionError(f"事务标识不回显: 发 {self.tid} 收 {rid}")
        if pid != 0:
            raise AssertionError(f"协议标识非 0: {pid}")
        if uid != unit:
            raise AssertionError(f"单元标识不回显: 发 {unit} 收 {uid}")
        if not (2 <= length <= 254):
            raise AssertionError(f"长度字段非法: {length}")
        return self._recv_exact(self.sock, length - 1)       # 响应 PDU


# ---------------- 响应解码辅助 ----------------
def decode_bits(pdu):
    """FC01/02 响应 -> [bool](8 位/字节,LSB 在前)。"""
    nbytes = pdu[1]
    payload = pdu[2:2 + nbytes]
    return [bool((payload[i >> 3] >> (i & 7)) & 1) for i in range(nbytes * 8)]


def decode_regs(pdu):
    """FC03/04 响应 -> [int](大端 16 位)。"""
    body = pdu[2:]
    return [int.from_bytes(body[i:i + 2], "big") for i in range(0, len(body), 2)]


def pack_bits(values):
    """[bool] -> 紧凑位字节串(LSB 在前),用于 FC15 请求。"""
    out = bytearray((len(values) + 7) // 8)
    for i, v in enumerate(values):
        if v:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


# ---------------- 中文对齐辅助(终端等宽近似) ----------------
def _w(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def _pad(s, width):
    return s + " " * max(0, width - _w(s))


def main():
    parser = argparse.ArgumentParser(description="零依赖 Modbus TCP 主站冒烟测试")
    parser.add_argument("--host", default=DEFAULT_HOST, help="从站地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="从站端口")
    parser.add_argument("--timeout", type=float, default=5.0, help="单帧超时(秒)")
    args = parser.parse_args()

    print(f"[主站] 连接 {args.host}:{args.port} ...")
    try:
        cli = SmokeClient(args.host, args.port, args.timeout)
    except OSError as exc:
        print(f"[主站] 连接失败: {exc}")
        print("提示: 请先启动从站: python modbus_tcp_slave.py --holding 0=1234,1=5678")
        return 2
    print("[主站] 已连接, 开始冒烟测试\n")

    function_cases = []      # (标签, 功能码, 说明, 是否通过, 详情)
    exception_cases = []

    def case(store, label, fc, name, fn):
        """执行单个用例,捕获一切异常记为 FAIL。"""
        try:
            detail = fn()
            ok = True
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
        store.append((label, fc, name, ok, detail))

    def rd_req(fc, start, qty):
        """构造读请求 PDU:功能码 + 起始地址 + 数量。"""
        return bytes([fc]) + start.to_bytes(2, "big") + qty.to_bytes(2, "big")

    # ============ 8 个功能码各一单 ============
    def fc01():
        pdu = cli.transact(rd_req(1, 0, 8))            # 读线圈 0-7
        assert pdu[0] == 1, f"功能码回显错 0x{pdu[0]:02X}"
        assert pdu[1] == 1, f"字节数 {pdu[1]} != 1"
        bits = decode_bits(pdu)[:8]
        assert bits == [False] * 8, f"初值应全 0, 实际 {bits}"
        return "读线圈0-7 -> 8 位全 0"

    def fc02():
        pdu = cli.transact(rd_req(2, 0, 8))            # 读离散输入 0-7
        assert pdu[0] == 2, f"功能码回显错 0x{pdu[0]:02X}"
        assert pdu[1] == 1, f"字节数 {pdu[1]} != 1"
        bits = decode_bits(pdu)[:8]
        assert bits == [False] * 8, f"初值应全 0, 实际 {bits}"
        return "读离散输入0-7 -> 8 位全 0"

    def fc03():
        pdu = cli.transact(rd_req(3, 0, 2))            # 读保持寄存器 0-1(种子)
        assert pdu[0] == 3, f"功能码回显错 0x{pdu[0]:02X}"
        assert pdu[1] == 4, f"字节数 {pdu[1]} != 4"
        regs = decode_regs(pdu)
        assert regs == [1234, 5678], f"应等于种子 [1234,5678], 实际 {regs}"
        return "读保持0-1 -> [1234, 5678](命中 --holding 种子)"

    def fc04():
        pdu = cli.transact(rd_req(4, 0, 2))            # 读输入寄存器 0-1
        assert pdu[0] == 4, f"功能码回显错 0x{pdu[0]:02X}"
        assert pdu[1] == 4, f"字节数 {pdu[1]} != 4"
        regs = decode_regs(pdu)
        assert regs == [0, 0], f"初值应 [0,0], 实际 {regs}"
        return "读输入寄存器0-1 -> [0, 0]"

    def fc05():
        req = (5).to_bytes(2, "big") + (0xFF00).to_bytes(2, "big")   # 线圈5 置 ON
        pdu = cli.transact(bytes([5]) + req)
        assert pdu == bytes([5]) + req, f"未原样回显: {pdu.hex()}"
        back = cli.transact(rd_req(1, 5, 1))                        # FC1 回读验证
        assert decode_bits(back)[0] is True, "回读线圈 5 应为 ON"
        return "写线圈5=ON -> 回显一致, 回读=ON"

    def fc06():
        req = (10).to_bytes(2, "big") + (4660).to_bytes(2, "big")    # 寄存器10=0x1234
        pdu = cli.transact(bytes([6]) + req)
        assert pdu == bytes([6]) + req, f"未原样回显: {pdu.hex()}"
        back = cli.transact(rd_req(3, 10, 1))                       # FC3 回读验证
        got = decode_regs(back)
        assert got == [4660], f"回读 {got} != [4660]"
        return "写寄存器10=4660 -> 回显一致, 回读=4660"

    def fc15():
        vals = [True, False, True, True]                            # 线圈20-23
        payload = pack_bits(vals)
        req = ((20).to_bytes(2, "big") + (4).to_bytes(2, "big")
               + bytes([len(payload)]) + payload)
        pdu = cli.transact(bytes([15]) + req)
        assert pdu == bytes([15]) + req[:4], f"响应应为地址+数量: {pdu.hex()}"
        back = cli.transact(rd_req(1, 20, 4))                       # FC1 回读验证
        got = decode_bits(back)[:4]
        assert got == vals, f"回读 {got} != {vals}"
        return "写线圈20-23=[1,0,1,1] -> 回显一致, 回读一致"

    def fc16():
        vals = [1000, 2000, 3000]                                   # 寄存器30-32
        req = ((30).to_bytes(2, "big") + (3).to_bytes(2, "big") + bytes([6])
               + b"".join(v.to_bytes(2, "big") for v in vals))
        pdu = cli.transact(bytes([16]) + req)
        assert pdu == bytes([16]) + req[:4], f"响应应为地址+数量: {pdu.hex()}"
        back = cli.transact(rd_req(3, 30, 3))                       # FC3 回读验证
        got = decode_regs(back)
        assert got == vals, f"回读 {got} != {vals}"
        return "写寄存器30-32=[1000,2000,3000] -> 回显一致, 回读一致"

    case(function_cases, "FC01", 1,  "读线圈",       fc01)
    case(function_cases, "FC02", 2,  "读离散输入",   fc02)
    case(function_cases, "FC03", 3,  "读保持寄存器", fc03)
    case(function_cases, "FC04", 4,  "读输入寄存器", fc04)
    case(function_cases, "FC05", 5,  "写单线圈",     fc05)
    case(function_cases, "FC06", 6,  "写单寄存器",   fc06)
    case(function_cases, "FC15", 15, "写多线圈",     fc15)
    case(function_cases, "FC16", 16, "写多寄存器",   fc16)

    # ============ 异常场景 ============
    def exc_case(label, fc, name, req_data, want_code):
        def fn():
            resp = cli.transact(bytes([fc]) + req_data)
            assert resp[0] == fc | 0x80, \
                f"响应功能码 0x{resp[0]:02X} != 0x{fc | 0x80:02X}"
            assert resp[1] == want_code, f"异常码 {resp[1]} != {want_code}"
            return f"响应 0x{resp[0]:02X}, 异常码 {resp[1]:02X}"
        case(exception_cases, label, fc, name, fn)

    beyond = (20000).to_bytes(2, "big")   # 20000 >= 默认区大小 10000 -> 不存在地址
    exc_case("EXC-A", 1, "读不存在线圈→02", beyond + (1).to_bytes(2, "big"), 2)
    exc_case("EXC-B", 3, "读不存在保持→02", beyond + (1).to_bytes(2, "big"), 2)
    exc_case("EXC-C", 3, "数量0→03(附加)", (0).to_bytes(2, "big") + (0).to_bytes(2, "big"), 3)

    # ============ 输出矩阵 ============
    def show(title, rows):
        print("=" * 72)
        print(title)
        print("-" * 72)
        for label, fc, name, ok, detail in rows:
            print(f"{label:<6} FC{fc:<3} {_pad(name, 18)} "
                  f"{'PASS' if ok else 'FAIL':<5} {detail}")
        print("-" * 72)

    show("功能码冒烟矩阵(8 个功能码各一单)", function_cases)
    show("异常场景矩阵(功能码|0x80 + 异常码)", exception_cases)

    ok_f = sum(1 for r in function_cases if r[3])
    ok_e = sum(1 for r in exception_cases if r[3])
    total_ok = ok_f == len(function_cases) and ok_e == len(exception_cases)
    print(f"功能码: {ok_f}/{len(function_cases)} PASS | "
          f"异常场景: {ok_e}/{len(exception_cases)} PASS")
    print("总体结果:", "PASS" if total_ok else "FAIL")

    cli.close()
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(main())
