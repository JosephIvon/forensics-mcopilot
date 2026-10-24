#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
modbus_tcp_slave.py —— 零依赖 Modbus TCP 从站模拟器(仅用 Python 标准库)
================================================================================

功能
  1. 监听 TCP 端口(默认 127.0.0.1:15020),支持多客户端并发连接;
  2. 内部维护四个内存区(默认每区 10000 个元素):
       线圈(Coils)        : FC01 读 / FC05 写单 / FC15 写多
       离散输入(Discrete) : FC02 读
       保持寄存器(Holding): FC03 读 / FC06 写单 / FC16 写多
       输入寄存器(Input)  : FC04 读
  3. 正确解析 MBAP 报文头(事务标识/协议标识/长度/单元标识),
     响应原样回显事务标识与单元标识;
  4. 异常响应 = (功能码 | 0x80) + 异常码:
       01 ILLEGAL FUNCTION     不支持的功能码
       02 ILLEGAL DATA ADDRESS 地址越界(超出内存区范围)
       03 ILLEGAL DATA VALUE   参数非法(数量 0/超上限、字节数不符、
                               线圈值非 0x0000/0xFF00 等)
  5. 命令行种子预置内存初值,格式 "地址=值,地址=值"(支持十进制 / 0x 十六进制):
       python modbus_tcp_slave.py --holding 0=1234,1=5678
   6. 劣化注入(可选,默认全部关闭,完全向后兼容)——模拟现实网络/从站的三类故障,
      用于验证主站接收侧的帧重组与毒化恢复逻辑(各模式的现实对应见下方注释):
        --fragment split3   每个响应拆 3 段发送(先 3 字节/再 5 字节/其余),段间随机 20-50ms
        --fragment byte1    响应逐字节发送,字节间随机 1-3ms
        --sticky-stale N    每第 N 个响应额外附发一个"伪造旧 TID 的完整陈旧帧"(与真实响应
                            一次性 send,制造粘包;陈旧帧残留在主站接收缓冲占住管道)
        --exception-sweep   异常码扫掠(2026-10-21 门禁轮新增):每个请求**按序**回异常码
                            01,02,03,05,06,08,0A,0B 循环(收到请求即回异常帧,不执行任何
                            读/写),用于钉住客户端异常码→ModbusSlaveException 名称表的
                            逐码精确映射(V1.1b3 §7 表;0x04 不入扫掠序列,由名称表单独断言)

MBAP 报文头(7 字节,大端):
  [0:2] 事务标识  请求方生成,响应回显
  [2:4] 协议标识  恒为 0(Modbus TCP)
  [4:6] 长度      其后字节数 = 单元标识(1 字节) + PDU
  [6]   单元标识  从站地址,TCP 下常用 1 / 0xFF
================================================================================
"""

import argparse
import random
import signal
import socket
import sys
import threading
import time

# ---------------- 协议常量 ----------------
FC_READ_COILS    = 1     # 读线圈
FC_READ_DISCRETE = 2     # 读离散输入
FC_READ_HOLDING  = 3     # 读保持寄存器
FC_READ_INPUT    = 4     # 读输入寄存器
FC_WRITE_COIL    = 5     # 写单线圈
FC_WRITE_REG     = 6     # 写单寄存器
FC_WRITE_COILS   = 15    # 写多线圈
FC_WRITE_REGS    = 16    # 写多寄存器

EXC_ILLEGAL_FUNCTION = 0x01   # 异常码:非法功能
EXC_ILLEGAL_ADDRESS  = 0x02   # 异常码:非法数据地址
EXC_ILLEGAL_VALUE    = 0x03   # 异常码:非法数据值

MBAP_HEADER_LEN = 7        # MBAP 头长度
MAX_PDU_LEN     = 253      # PDU 最大长度(含功能码字节)
DEFAULT_HOST    = "127.0.0.1"
DEFAULT_PORT    = 15020
DEFAULT_SIZE    = 10000    # 每个内存区默认元素个数(有效地址 0..size-1)

# ---------------- 劣化注入模式常量(默认 none/0 = 不注入,行为与旧版完全一致) ----------------
FRAGMENT_NONE   = "none"    # 不劣化:整帧一次 send(默认,向后兼容)
FRAGMENT_SPLIT3 = "split3"  # 每个响应拆 3 段发送(3B/5B/其余,段间 20-50ms)
FRAGMENT_BYTE1  = "byte1"   # 每个响应逐字节发送(字节间 1-3ms)

# ---------------- 异常码扫掠序列(--exception-sweep,按请求循环) ----------------
# V1.1b3 §7 表中 mechanical 在册的异常码,按序循环;0x04 不入序列(契约侧用
# GetExceptionName(0x04)=="SERVER DEVICE FAILURE" 单独钉住改名)。
EXCEPTION_SWEEP_CODES = (0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0A, 0x0B)

_print_lock = threading.Lock()


def log(msg):
    """线程安全打印(带时间戳)。"""
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def to_int(text):
    """字符串 -> 整数:先按 0x/0b/0o 前缀解析,失败则按十进制(兼容前导零)。"""
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 10)


def u16(data, pos):
    """取 data[pos] 起的大端 16 位无符号整数。"""
    return (data[pos] << 8) | data[pos + 1]


class ModbusError(Exception):
    """协议处理错误,携带异常码;由 handle() 统一转成异常响应。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ModbusMemory:
    """四个内存区 + 一把互斥锁,保证多客户端并发访问的一致性。"""

    def __init__(self, size):
        self.size = size
        self.coils    = [False] * size   # 线圈       FC01/05/15
        self.discrete = [False] * size   # 离散输入   FC02(只读区)
        self.holding  = [0] * size       # 保持寄存器 FC03/06/16
        self.input    = [0] * size       # 输入寄存器 FC04(只读区)
        self.lock = threading.RLock()

    def seed(self, area, mapping, as_bool, label):
        """把 {地址: 值} 种子写入指定内存区,越界/超范围直接退出报错。"""
        for addr, val in mapping.items():
            if not (0 <= addr < self.size):
                raise SystemExit(f"[参数错误] --{label} 地址越界: {addr}(有效 0..{self.size - 1})")
            if as_bool:
                area[addr] = bool(val)
            elif not (0 <= val <= 0xFFFF):
                raise SystemExit(f"[参数错误] --{label} 值超 16 位: {addr}={val}")
            else:
                area[addr] = val


def parse_seed(text, label):
    """解析 "地址=值,地址=值" 种子串 -> {地址: 值}。"""
    result = {}
    text = (text or "").strip()
    if not text:
        return result
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(f"[参数错误] --{label} 片段 '{item}' 缺少 '=',正确格式: 地址=值")
        key, _, val = item.partition("=")
        try:
            result[to_int(key)] = to_int(val)
        except ValueError:
            raise SystemExit(f"[参数错误] --{label} 片段 '{item}' 不是有效整数")
    return result


class ModbusSlave:
    """Modbus TCP 从站协议核心:解析请求 PDU -> 读写内存 -> 构造响应 PDU。"""

    def __init__(self, mem, verbose=False):
        self.mem = mem
        self.verbose = verbose
        self._handlers = {
            FC_READ_COILS:    self._read_bits,          # 01
            FC_READ_DISCRETE: self._read_bits,          # 02
            FC_READ_HOLDING:  self._read_regs,          # 03
            FC_READ_INPUT:    self._read_regs,          # 04
            FC_WRITE_COIL:    self._write_single_coil,  # 05
            FC_WRITE_REG:     self._write_single_reg,   # 06
            FC_WRITE_COILS:   self._write_coils,        # 15
            FC_WRITE_REGS:    self._write_regs,         # 16
        }

    # ---------- 对外入口 ----------
    def handle(self, req_pdu):
        """处理一个请求 PDU,返回响应 PDU;出错时返回 (功能码|0x80)+异常码。"""
        fc = req_pdu[0]
        try:
            handler = self._handlers.get(fc)
            if handler is None:
                raise ModbusError(EXC_ILLEGAL_FUNCTION)    # 不支持的功能码 -> 01
            with self.mem.lock:                            # 整个请求期间锁内存
                resp = handler(fc, req_pdu[1:])
        except ModbusError as exc:
            resp = bytes([fc | 0x80, exc.code])
        if self.verbose:
            kind = "响应" if resp[0] == fc else f"异常 0x{resp[1]:02X}"
            log(f"[从站] FC{fc:<2d} 请求 {len(req_pdu)}B -> {kind} {len(resp)}B")
        return resp

    # ---------- FC01 / FC02:读线圈 / 读离散输入 ----------
    def _read_bits(self, fc, data):
        if len(data) != 4:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        start, qty = u16(data, 0), u16(data, 2)
        if not (1 <= qty <= 2000):                 # 规范:一次最多读 2000 个位
            raise ModbusError(EXC_ILLEGAL_VALUE)
        mem = self.mem
        if start + qty > mem.size:                 # 地址越界 -> 02
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        area = mem.coils if fc == FC_READ_COILS else mem.discrete
        nbytes = (qty + 7) // 8
        out = bytearray(nbytes)
        for i in range(qty):
            if area[start + i]:
                out[i >> 3] |= 1 << (i & 7)        # 首个线圈 -> 首字节最低位(LSB)
        return bytes([fc, nbytes]) + bytes(out)

    # ---------- FC03 / FC04:读保持 / 读输入寄存器 ----------
    def _read_regs(self, fc, data):
        if len(data) != 4:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        start, qty = u16(data, 0), u16(data, 2)
        if not (1 <= qty <= 125):                  # 规范:一次最多读 125 个寄存器
            raise ModbusError(EXC_ILLEGAL_VALUE)
        mem = self.mem
        if start + qty > mem.size:
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        area = mem.holding if fc == FC_READ_HOLDING else mem.input
        body = bytearray()
        for val in area[start:start + qty]:
            body += val.to_bytes(2, "big")
        return bytes([fc, len(body)]) + bytes(body)

    # ---------- FC05:写单线圈 ----------
    def _write_single_coil(self, fc, data):
        if len(data) != 4:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        addr, val = u16(data, 0), u16(data, 2)
        if val not in (0x0000, 0xFF00):            # 规范:仅允许这两个值
            raise ModbusError(EXC_ILLEGAL_VALUE)
        if addr >= self.mem.size:
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        self.mem.coils[addr] = (val == 0xFF00)
        return bytes([fc]) + data                  # 规范要求原样回显请求

    # ---------- FC06:写单寄存器 ----------
    def _write_single_reg(self, fc, data):
        if len(data) != 4:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        addr, val = u16(data, 0), u16(data, 2)
        if addr >= self.mem.size:
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        self.mem.holding[addr] = val
        return bytes([fc]) + data                  # 原样回显

    # ---------- FC15:写多线圈 ----------
    def _write_coils(self, fc, data):
        if len(data) < 5:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        addr, qty, nbytes = u16(data, 0), u16(data, 2), data[4]
        if not (1 <= qty <= 1968):                 # 规范:一次最多写 1968 个线圈
            raise ModbusError(EXC_ILLEGAL_VALUE)
        if nbytes != (qty + 7) // 8 or len(data) != 5 + nbytes:
            raise ModbusError(EXC_ILLEGAL_VALUE)   # 字节数与数量不符 -> 03
        if addr + qty > self.mem.size:
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        for i in range(qty):
            self.mem.coils[addr + i] = bool((data[5 + (i >> 3)] >> (i & 7)) & 1)
        return bytes([fc]) + data[0:4]             # 响应 = 地址 + 数量

    # ---------- FC16:写多寄存器 ----------
    def _write_regs(self, fc, data):
        if len(data) < 5:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        addr, qty, nbytes = u16(data, 0), u16(data, 2), data[4]
        if not (1 <= qty <= 123):                  # 规范:一次最多写 123 个寄存器
            raise ModbusError(EXC_ILLEGAL_VALUE)
        if nbytes != qty * 2 or len(data) != 5 + nbytes:
            raise ModbusError(EXC_ILLEGAL_VALUE)
        if addr + qty > self.mem.size:
            raise ModbusError(EXC_ILLEGAL_ADDRESS)
        for i in range(qty):
            self.mem.holding[addr + i] = u16(data, 5 + i * 2)
        return bytes([fc]) + data[0:4]


def build_stale_frame(real_frame):
    """伪造一个"过期陈旧帧":完整合法的 MBAP 响应帧,但事务标识是伪造的旧 TID。

    现实对应(为什么要造这种帧):
      - 上联网关/透明代理/抓包重放设备把缓存的"上一事务旧响应"与当前响应背靠背发回;
      - 从站异常复位后发送缓冲里残留一条没发完/重发的旧完整帧。
    陈旧帧的 TID 取真实 TID-1(保证与主站当前期待值必不相等),PDU 伪装成一帧
    "很久以前"的 FC3 响应(1 个寄存器,值 0x0000),单元标识沿用真实帧。
    主站按 MBAP 长度恰好读完真实响应后,该帧会残留在主站接收缓冲占住管道——
    下一事务将先撞上它,典型表现为"诡异的事务标识不匹配"。
    """
    real_tid = int.from_bytes(real_frame[0:2], "big")
    stale_tid = (real_tid - 1) & 0xFFFF
    stale_pdu = bytes([FC_READ_HOLDING, 0x02, 0x00, 0x00])   # 旧 FC3 响应:1 个寄存器,值 0
    return (stale_tid.to_bytes(2, "big")
            + (0).to_bytes(2, "big")                         # 协议标识恒 0
            + (1 + len(stale_pdu)).to_bytes(2, "big")        # 长度 = 单元标识 + PDU
            + real_frame[6:7]                                # 单元标识沿用真实响应
            + stale_pdu)


def send_degraded(conn, payload, fragment_mode):
    """按劣化模式把 payload 发上网络;fragment_mode = none / split3 / byte1。

    split3 —— 模拟"响应被网络拆成多个 TCP 段先后到达":
        现实对应:MTU 分片、NAT/VPN 隧道、串口联网服务器(serial-to-ethernet 网桥)
        把一整帧按自身缓冲切成几段转发,段间隔几十毫秒且抖动。主站若把"一次 recv"
        当"一整帧"就会把半帧当全帧用;正确姿势是按 MBAP 长度循环补齐(ReadExact)。
        切法:先 3 字节(MBAP 事务/协议标识)、再 5 字节、余下最后一段,段间随机 20-50ms。

    byte1 —— 极端劣化链路,模拟"字节级滴流到达":
        现实对应:GPRS/卫星回传、低功耗串口网桥逐字节转发,字节间隔毫秒级抖动。
        比分片更狠:任何"读了 7 字节头就假设正文也整段在缓冲里"的偷懒实现都会翻车,
        专门用来验证主站接收循环真的逐字节重组(ReadExact 循环必须真循环)。
        字节间随机 1-3ms。

    none —— 不劣化,整帧一次 send(默认,向后兼容)。
    """
    if fragment_mode == FRAGMENT_BYTE1:
        for i in range(len(payload)):
            if i:
                time.sleep(random.uniform(0.001, 0.003))     # 字节间 1-3ms 抖动
            conn.sendall(payload[i:i + 1])
        return
    if fragment_mode == FRAGMENT_SPLIT3:
        segments = (payload[:3], payload[3:8], payload[8:])  # 3 字节 / 5 字节 / 其余
        for i, seg in enumerate(segments):
            if not seg:
                continue
            if i:
                time.sleep(random.uniform(0.020, 0.050))     # 段间 20-50ms 抖动
            conn.sendall(seg)
        return
    conn.sendall(payload)                                    # none:原行为


def recv_exact(sock, n):
    """循环 recv 直到凑满 n 字节;对端关闭返回 None。"""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def serve_connection(conn, peer, slave, fragment_mode=FRAGMENT_NONE, sticky_stale=0,
                     exception_sweep=False):
    """单客户端会话:收 MBAP -> 处理 PDU -> 回响应,直到断开或报文非法。

    fragment_mode / sticky_stale / exception_sweep 为劣化/扫掠注入参数(默认关闭,
    行为与旧版完全一致):
      - fragment_mode: "split3"/"byte1",见 send_degraded() 注释;
      - sticky_stale: N>0 时每第 N 个响应额外附发一个陈旧帧(见 build_stale_frame());
      - exception_sweep: True 时每个请求按 EXCEPTION_SWEEP_CODES 序回异常码(循环),
        不执行任何读/写——契约侧断言客户端逐码抛 ModbusSlaveException 且名称精确匹配。
    """
    # 关键:accept() 出来的 socket 会继承监听 socket 的 0.5s 超时,
    # 若不恢复阻塞模式,空闲 0.5s 后 recv 抛 socket.timeout 会杀死会话线程。
    conn.settimeout(None)
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 关 Nagle,响应更跟手
    except OSError:
        pass
    with conn:
        resp_count = 0                            # 本连接已发出的响应数(劣化注入计数用)
        sweep_index = 0                           # 异常码扫掠游标(按连接计数,确定性递增)
        while True:
            head = recv_exact(conn, MBAP_HEADER_LEN)
            if head is None:                       # 对端正常关闭
                return
            tid = int.from_bytes(head[0:2], "big")     # 事务标识
            pid = int.from_bytes(head[2:4], "big")     # 协议标识
            length = int.from_bytes(head[4:6], "big")  # 长度(单元标识+PDU)
            uid = head[6]                              # 单元标识
            # 协议标识必须为 0;长度至少要装下单元标识,且不超过 PDU 上限
            if pid != 0 or not (1 <= length <= 1 + MAX_PDU_LEN):
                log(f"[从站] {peer[0]}:{peer[1]} MBAP 非法(协议={pid}, 长度={length}),断开连接")
                return
            # 头部 7 字节已包含单元标识,故这里只取 length-1 字节 = 请求 PDU
            body = recv_exact(conn, length - 1)
            if body is None:
                return
            req_pdu = body
            if not req_pdu:                        # 空 PDU:忽略
                continue
            if exception_sweep:
                # —— 异常码扫掠注入:按序回 (FC|0x80)+异常码,不执行任何读/写 ——
                code = EXCEPTION_SWEEP_CODES[sweep_index % len(EXCEPTION_SWEEP_CODES)]
                sweep_index += 1
                resp_pdu = bytes([req_pdu[0] | 0x80, code])
                if slave.verbose:
                    log(f"[从站] {peer[0]}:{peer[1]} 异常码扫掠: 第 {sweep_index} 请求 "
                        f"FC{req_pdu[0]:02X} -> 异常码 0x{code:02X}")
            else:
                resp_pdu = slave.handle(req_pdu)
            frame = (tid.to_bytes(2, "big")
                     + (0).to_bytes(2, "big")                   # 协议标识恒 0
                     + (1 + len(resp_pdu)).to_bytes(2, "big")   # 长度 = 单元标识 + PDU
                     + bytes([uid])                             # 回显单元标识
                     + resp_pdu)
            resp_count += 1
            payload = frame
            if sticky_stale > 0 and resp_count % sticky_stale == 0:
                # —— 粘包/残帧占管道注入(见 build_stale_frame 注释)——
                # 陈旧帧与真实响应一次性 send(背靠背字节流),模拟网关重发旧帧/从站缓冲残留;
                # 主站读完真实响应后,陈旧帧残留在主站接收缓冲,下一事务必然先撞上它——
                # 用于端到端验证主站"出错即毒化、重连复活"的恢复闭环(P1-3)。
                stale = build_stale_frame(frame)
                if slave.verbose:
                    log(f"[从站] {peer[0]}:{peer[1]} 粘包注入: 附发陈旧帧 "
                        f"TID={int.from_bytes(stale[0:2], 'big')} (真实 TID={tid})")
                payload = frame + stale
            send_degraded(conn, payload, fragment_mode)


def build_parser():
    parser = argparse.ArgumentParser(
        description="零依赖 Modbus TCP 从站模拟器(FC 1,2,3,4,5,6,15,16)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE,
                        help="每个内存区元素个数(有效地址 0..size-1)")
    parser.add_argument("--coils", default="", help="线圈种子, 如 0=1,3=0")
    parser.add_argument("--discrete-inputs", default="", help="离散输入种子, 如 2=1")
    parser.add_argument("--holding", default="", help="保持寄存器种子, 如 0=1234,1=5678")
    parser.add_argument("--input-registers", default="", help="输入寄存器种子, 如 0=42")
    parser.add_argument("--fragment", choices=[FRAGMENT_NONE, FRAGMENT_SPLIT3, FRAGMENT_BYTE1],
                        default=FRAGMENT_NONE,
                        help="响应发送劣化模式(默认 none 不劣化,向后兼容)。"
                             "split3=模拟网络 MTU 分片/网桥缓冲把响应拆成 3 段(3B/5B/其余)"
                             "先后到达,段间 20-50ms;byte1=模拟 GPRS/串口网桥等极端慢链路"
                             "逐字节滴流到达,字节间 1-3ms;均用于验证主站 ReadExact 重组")
    parser.add_argument("--sticky-stale", type=int, default=0, metavar="N",
                        help="粘包/残帧注入:每第 N 个响应额外附发一个伪造旧 TID 的完整陈旧帧"
                             "(与真实响应背靠背一次性 send),模拟网关重发旧帧/从站缓冲残留,"
                             "陈旧帧残留主站接收缓冲占住管道;0=关闭(默认,向后兼容)")
    parser.add_argument("--exception-sweep", action="store_true",
                        help="异常码扫掠:每个请求按序回异常码 01,02,03,05,06,08,0A,0B 循环"
                             "(收到即回异常帧,不执行读写),用于钉住客户端异常码->"
                             "ModbusSlaveException 名称表的逐码精确映射;默认关闭(向后兼容)")
    parser.add_argument("--verbose", action="store_true", help="打印每帧收发日志")
    return parser


def main():
    args = build_parser().parse_args()
    if args.size <= 0:
        raise SystemExit("[参数错误] --size 必须为正整数")

    if args.sticky_stale < 0:
        raise SystemExit("[参数错误] --sticky-stale N 必须为非负整数(0=关闭)")

    mem = ModbusMemory(args.size)
    # 依次写入四个区的种子(位区按布尔处理,寄存器区校验 16 位范围)
    mem.seed(mem.coils,    parse_seed(args.coils, "coils"),                     True,  "coils")
    mem.seed(mem.discrete, parse_seed(args.discrete_inputs, "discrete-inputs"), True,  "discrete-inputs")
    mem.seed(mem.holding,  parse_seed(args.holding, "holding"),                 False, "holding")
    mem.seed(mem.input,    parse_seed(args.input_registers, "input-registers"), False, "input-registers")

    slave = ModbusSlave(mem, verbose=args.verbose)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":                # Windows 下 SO_REUSEADDR 语义不同,不设置
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((args.host, args.port))
    except OSError as exc:
        raise SystemExit(f"[从站] 绑定失败 {args.host}:{args.port} - {exc}")
    srv.listen(16)
    srv.settimeout(0.5)                        # 周期醒来检查停止标志,便于 Ctrl+C 干净退出

    stop = threading.Event()

    def _request_stop(_signum, _frame):
        stop.set()

    try:                                       # 个别平台可能没有对应信号,忽略即可
        signal.signal(signal.SIGINT, _request_stop)
        signal.signal(signal.SIGTERM, _request_stop)
    except (ValueError, OSError, AttributeError):
        pass

    log(f"[从站] 监听 {args.host}:{args.port} | 每区 {args.size} 元素"
        f" | 支持功能码 {sorted({1, 2, 3, 4, 5, 6, 15, 16})}")
    for flag, text in (("--coils", args.coils),
                       ("--discrete-inputs", args.discrete_inputs),
                       ("--holding", args.holding),
                       ("--input-registers", args.input_registers)):
        if text.strip():
            log(f"[从站] 种子 {flag} {text.strip()}")
    # 劣化注入配置回显(默认两项都不开启,与旧版行为一致)
    if args.fragment == FRAGMENT_SPLIT3:
        log("[从站] 劣化注入 --fragment split3: 每个响应拆 3 段(3B/5B/其余)发送,段间 20-50ms"
            " —— 模拟 MTU 分片/网桥缓冲导致的 TCP 段先后到达")
    elif args.fragment == FRAGMENT_BYTE1:
        log("[从站] 劣化注入 --fragment byte1: 响应逐字节发送,字节间 1-3ms"
            " —— 模拟 GPRS/串口网桥等极端慢链路的字节滴流")
    if args.sticky_stale > 0:
        log(f"[从站] 劣化注入 --sticky-stale {args.sticky_stale}: 每第 {args.sticky_stale} 个响应"
            f" 附发一个伪造旧 TID 的完整陈旧帧 —— 模拟网关重发旧帧/从站缓冲残留(粘包占管道)")
    if args.exception_sweep:
        log("[从站] 异常码扫掠 --exception-sweep: 每个请求按序回异常码 "
            + ",".join(f"{c:02X}" for c in EXCEPTION_SWEEP_CODES)
            + " 循环(不执行读写) —— 钉住客户端异常码名称表逐码映射")
    log("[从站] 等待主站连接... (Ctrl+C 停止)")

    try:
        while not stop.is_set():
            try:
                conn, peer = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=serve_connection,
                             args=(conn, peer, slave, args.fragment, args.sticky_stale,
                                   args.exception_sweep),
                             daemon=True).start()
    finally:
        srv.close()
        log("[从站] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
