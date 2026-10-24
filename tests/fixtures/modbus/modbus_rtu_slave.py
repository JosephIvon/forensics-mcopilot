#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
================================================================================
modbus_rtu_slave.py —— 零依赖 Modbus RTU 从站模拟器(仅用 Python 标准库)
================================================================================

目的
  在 com0com 虚拟串口对上为 Modbus RTU 主站(C# ModbusRtuClient)提供**行为级**
  从站:真实走"字节流 + 帧间隔 + CRC16"链路,零真机即可打通信令闭环。
  (虚拟对不仿真波特率/电气层;真机波特率时序仍需现场验证。)

功能码(与 modbus_tcp_slave 完全一致的执行语义,直接复用其实现)
  FC01 读线圈  FC02 读离散输入  FC03 读保持寄存器  FC04 读输入寄存器
  FC05 写单线圈 FC06 写单寄存器 FC15 写多线圈     FC16 写多寄存器
  异常响应 = (功能码 | 0x80) + 异常码(01/02/03),由 modbus_tcp_slave.ModbusSlave
  统一构造,本文件只做 RTU 帧封装/拆封。

RTU 帧格式
  [从站地址 1B][PDU ≤253B][CRC16 低字节][CRC16 高字节]
  CRC16: 多项式 0xA001(即 0x8005 反射),初值 0xFFFF,数据字节低位在前;
  帧内低前高后。

广播(unitId = 0)
  收到地址 0 的写请求:正常执行写操作但**不回任何帧**,并在 stdout 打印一条
  广播日志(RTU 规范:广播只允许写,读请求直接忽略不执行)。
  主站据此验证"广播闭环":发送后无响应快速返回,稍后用单播读回写值。

命令行(与 TCP 版对齐 + RTU 专属)
  --port COM4          本从站占用的串口端(虚拟对的 B 端)
  --baud 9600          标称波特率(com0com 忽略,但仍配置进 DCB 保持形式正确)
  --unit 1             本从站单播地址
  --holding 0=1234,1=5678 等种子参数,语义与 TCP 版一致
  --corrupt-next       劣化注入:下一个响应帧故意破坏 CRC(仅一帧,注入后自动解除),
                        用于验证主站"坏 CRC 拒收 + 下一事务恢复正常"

收帧策略(实现选择:"收到 n≥4 后按预期长度"为主,"帧间隔判定"兜底)
  RTU 请求帧长度可由功能码静态确定:
    FC1..FC6        -> 地址+功能码+4B 参数+CRC = 8 字节
    FC15/FC16       -> 地址+功能码+4B+字节数域+CRC = 9 + nbytes 字节
  主循环攒字节:一旦 ≥4 字节且能算出预期总长,凑满即刻处理(不等静默,时延最低);
  功能码不认识/半帧异常时,退回"静默 GAP_IDLE 无新字节即视为一帧结束"的帧间隔
  判定收尾(9600 波特下 3.5 字符 ≈ 4ms,虚拟对字节瞬时可达,取 20ms 保守值)。
  任何 CRC 校验失败:整段缓冲丢弃(重新同步)并打印日志。

串口访问(Windows,零依赖)
  用 ctypes 调 kernel32:CreateFileW / GetCommState / SetCommState /
  SetCommTimeouts / ReadFile / WriteFile / PurgeComm / CloseHandle。
  关键点:
    * 路径必须用 \\.\COM4 形式(COM 号 ≥10 时 open('COM4') 会失败);
    * ReadFile 用"非阻塞组合"(ReadIntervalTimeout=MAXDWORD, 另两读超时=0):
      立即返回当前可得字节(0 个也立即回),轮询节奏由本程序掌控;
    * WriteFile 设 1s 总超时兜底,防止异常时永久阻塞;
    * com0com 虚拟对忽略波特率,但 DCB 仍按 9600 8N1 显式配置(形式正确、
      与真机代码路径一致),并关掉流控位。
================================================================================
"""

import argparse
import ctypes
import os
import signal
import sys
import time
from ctypes import wintypes

# 复用 TCP 从站的 FC 执行逻辑(同目录导入;直接从别的工作目录运行也成立)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from modbus_tcp_slave import (          # noqa: E402
    FC_READ_COILS, FC_READ_DISCRETE, FC_READ_HOLDING, FC_READ_INPUT,
    FC_WRITE_COIL, FC_WRITE_REG, FC_WRITE_COILS, FC_WRITE_REGS,
    ModbusMemory, ModbusSlave, log, parse_seed,
)

# ---------------- RTU 层常量 ----------------
BROADCAST_ADDRESS = 0            # 广播地址:执行写、不回帧
MAX_ADU_LEN       = 256          # 1B 地址 + 253B PDU + 2B CRC
WRITE_FCS = frozenset({FC_WRITE_COIL, FC_WRITE_REG, FC_WRITE_COILS, FC_WRITE_REGS})

GAP_IDLE = 0.020                 # 静默判定帧结束的间隔(秒):9600 下 3.5 字符≈4ms,取保守 20ms
POLL_IDLE = 0.002                # 无数据时的轮询间隔(秒)

# ---------------- ctypes / kernel32 ----------------
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ  = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PURGE_TXCLEAR = 0x0004
PURGE_RXCLEAR = 0x0008

# DCB 标志位(仅用到这几个)
_fBinary       = 0x0001
_fOutxCtsFlow  = 0x0004
_fOutxDsrFlow  = 0x0008
_fOutX         = 0x0100
_fInX          = 0x0200

DTR_CONTROL_ENABLE = 0x10        # flags 位 4-5 的 DTR_CONTROL 字段取值 01b
RTS_CONTROL_ENABLE = 0x10        # flags 位 12-13 的 RTS_CONTROL 字段取值 01b
_dtr_mask = 0x30
_rts_mask = 0x3000


class DCB(ctypes.Structure):
    """Win32 DCB 结构(serial-config),字段顺序须与 winbase.h 一致。"""
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate",  wintypes.DWORD),
        ("flags",     wintypes.DWORD),   # 位域合集:整段按原始 DWORD 操作
        ("wReserved", wintypes.WORD),
        ("XonLim",    wintypes.WORD),
        ("XoffLim",   wintypes.WORD),
        ("ByteSize",  wintypes.BYTE),
        ("Parity",    wintypes.BYTE),
        ("StopBits",  wintypes.BYTE),
        ("XonChar",   ctypes.c_char),
        ("XoffChar",  ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar",   ctypes.c_char),
        ("EvtChar",   ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    """Win32 COMMTIMEOUTS 结构,ReadFile/WriteFile 超时行为全由它定义。"""
    _fields_ = [
        ("ReadIntervalTimeout",         wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier",  wintypes.DWORD),
        ("ReadTotalTimeoutConstant",    wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant",   wintypes.DWORD),
    ]


_k32.CreateFileW.restype  = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p]
_k32.ReadFile.restype  = wintypes.BOOL
_k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.WriteFile.restype  = wintypes.BOOL
_k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.CloseHandle.restype  = wintypes.BOOL
_k32.CloseHandle.argtypes = [ctypes.c_void_p]


class Win32SerialPort:
    """kernel32 串口薄封装:打开/配置/非阻塞读/写/清缓冲/关。"""

    def __init__(self, name, baud=9600):
        self.name = name
        self.baud = baud
        self._h = None

    # -- 打开并配置(9600 8N1、无流控、读非阻塞) --
    def open(self):
        path = r"\\.\{}".format(self.name)          # \\.\ 前缀对 >=COM10 与虚拟口都安全
        h = _k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, None,
                             OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise SystemExit("[从站] 打开串口 {} 失败: CreateFileW 错误码 {}".format(self.name, err))
        self._h = ctypes.c_void_p(h)

        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not _k32.GetCommState(self._h, ctypes.byref(dcb)):
            raise SystemExit("[从站] GetCommState 失败(错误码 {})".format(ctypes.get_last_error()))
        dcb.BaudRate = self.baud
        dcb.ByteSize = 8
        dcb.Parity   = 0                              # NOPARITY
        dcb.StopBits = 0                              # ONESTOPBIT
        # 关流控、开二进制模式,DTR/RTS 置为启用(虚拟对忽略,真机路径形式正确)
        dcb.flags &= ~(_fOutxCtsFlow | _fOutxDsrFlow | _fOutX | _fInX | _dtr_mask | _rts_mask)
        dcb.flags |= _fBinary | DTR_CONTROL_ENABLE | RTS_CONTROL_ENABLE
        if not _k32.SetCommState(self._h, ctypes.byref(dcb)):
            raise SystemExit("[从站] SetCommState 失败(错误码 {})".format(ctypes.get_last_error()))

        touts = COMMTIMEOUTS()
        # 读:Interval=MAXDWORD 且 Total 两项=0 -> ReadFile 立即返回现有字节(0 个也立即回)
        touts.ReadIntervalTimeout        = 0xFFFFFFFF
        touts.ReadTotalTimeoutMultiplier = 0
        touts.ReadTotalTimeoutConstant   = 0
        # 写:1 秒总超时兜底,异常时不会永久阻塞
        touts.WriteTotalTimeoutMultiplier = 0
        touts.WriteTotalTimeoutConstant   = 1000
        if not _k32.SetCommTimeouts(self._h, ctypes.byref(touts)):
            raise SystemExit("[从站] SetCommTimeouts 失败(错误码 {})".format(ctypes.get_last_error()))

    # -- 非阻塞读:立即返回当前可得字节(可能为空) --
    def read(self, max_bytes=512):
        buf = ctypes.create_string_buffer(max_bytes)
        got = wintypes.DWORD(0)
        if not _k32.ReadFile(self._h, buf, max_bytes, ctypes.byref(got), None):
            err = ctypes.get_last_error()
            _k32.PurgeComm(self._h, PURGE_RXCLEAR | PURGE_TXCLEAR)   # 出错清缓冲再同步
            log("[从站] ReadFile 失败(错误码 {}),已清缓冲".format(err))
            return b""
        return buf.raw[:got.value]

    def write(self, data):
        sent = wintypes.DWORD(0)
        if not _k32.WriteFile(self._h, data, len(data), ctypes.byref(sent), None):
            log("[从站] WriteFile 失败(错误码 {})".format(ctypes.get_last_error()))
            return False
        if sent.value != len(data):
            log("[从站] WriteFile 不完整: {}/{}".format(sent.value, len(data)))
            return False
        return True

    def purge(self):
        if self._h:
            _k32.PurgeComm(self._h, PURGE_RXCLEAR | PURGE_TXCLEAR)

    def close(self):
        if self._h:
            _k32.CloseHandle(self._h)
            self._h = None


# ---------------- CRC16(Modbus RTU: poly 0xA001, 低前高后) ----------------
def crc16(data):
    """Modbus RTU CRC16:初值 0xFFFF,多项式 0xA001(反射 0x8005)。

    返回 16 位整数;入帧时低字节在前、高字节在后(低前高后)。
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def rtu_frame(addr, pdu):
    """组响应帧:地址 + PDU + CRC(低前高后)。"""
    body = bytes([addr]) + pdu
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def request_frame_len(buf):
    """由功能码静态确定完整请求帧总长;信息不足返回 None。

    FC1..FC6  -> 8 字节(地址+FC+4 参数+CRC)
    FC15/16   -> 9 + nbytes 字节(第 7 字节是数据字节数域)
    其他 FC   -> None(交给帧间隔判定兜底)
    """
    if len(buf) < 2:
        return None
    fc = buf[1]
    if fc in (FC_READ_COILS, FC_READ_DISCRETE, FC_READ_HOLDING, FC_READ_INPUT,
              FC_WRITE_COIL, FC_WRITE_REG):
        return 8
    if fc in (FC_WRITE_COILS, FC_WRITE_REGS):
        if len(buf) < 7:
            return None
        return 9 + buf[6]
    return None


class RtuSlaveApp:
    """串口从站应用:收帧 -> CRC -> 分发(广播/单播/他址) -> 组帧回写。"""

    def __init__(self, port_name, baud, unit, mem, corrupt_next, verbose):
        self.port = Win32SerialPort(port_name, baud)
        self.unit = unit
        self.slave = ModbusSlave(mem, verbose=False)     # PDU 执行复用 TCP 版,帧级日志自己打
        self.corrupt_next = corrupt_next
        self.verbose = verbose
        self._running = True

    # -- 单帧处理:CRC 校验 -> 广播/单播/忽略 --
    def process_frame(self, frame):
        if len(frame) < 4:
            log("[从站] 帧过短({}B),丢弃: {}".format(len(frame), frame.hex(" ")))
            return
        body, crc_lo, crc_hi = frame[:-2], frame[-2], frame[-1]
        calc = crc16(body)
        if calc != (crc_hi << 8) | crc_lo:
            log("[从站] CRC 错误(收 {:02X}{:02X}, 算 {:04X}),整段丢弃重新同步: {}"
                .format(crc_lo, crc_hi, calc, frame.hex(" ")))
            return
        addr, pdu = frame[0], frame[1:-2]
        if addr == BROADCAST_ADDRESS:
            # 广播:只执行写操作,不回帧;读请求按规范忽略
            if pdu and pdu[0] in WRITE_FCS:
                self.slave.handle(pdu)                   # 执行写(PDU 丢弃,不回帧)
                log("[从站] 收到广播(unitId=0) FC{} -> 已执行写操作,不回帧".format(pdu[0]))
            else:
                log("[从站] 收到广播(unitId=0) FC{} -> 广播不允许读,忽略".format(pdu[0] if pdu else -1))
            return
        if addr != self.unit:
            return                                       # RTU 多点总线上的他站地址:静默忽略
        resp_pdu = self.slave.handle(pdu)
        frame_out = rtu_frame(addr, resp_pdu)
        if self.corrupt_next:
            # 劣化注入:破坏本帧 CRC 低字节(仅一帧),用于验证主站拒收与恢复
            bad = bytearray(frame_out)
            bad[-2] ^= 0xFF
            frame_out = bytes(bad)
            self.corrupt_next = False
            log("[从站] 劣化注入 --corrupt-next: 本响应 CRC 已故意破坏({}B)".format(len(frame_out)))
        elif self.verbose:
            log("[从站] 响应 -> 地址 {} PDU {}B 帧 {}B".format(addr, len(resp_pdu), len(frame_out)))
        self.port.write(frame_out)

    # -- 主循环:预期长度快路 + 帧间隔兜底 --
    def run(self):
        self.port.open()
        print("RTU-SLAVE-READY port={} unit={} corrupt_next={}"
              .format(self.port.name, self.unit, int(self.corrupt_next)), flush=True)
        buf = bytearray()
        last_rx = time.time()
        while self._running:
            chunk = self.port.read(512)
            if chunk:
                buf.extend(chunk)
                if len(buf) > MAX_ADU_LEN * 2:
                    # 异常防护:积压远超最大合法帧,视为线垃圾直接重同步
                    log("[从站] 接收缓冲异常积压({}B),清空重新同步".format(len(buf)))
                    buf.clear()
                last_rx = time.time()
                while buf:
                    expected = request_frame_len(buf)
                    if expected is not None and len(buf) >= expected:
                        frame = bytes(buf[:expected])
                        del buf[:expected]
                        self.process_frame(frame)
                        continue
                    break                              # 长度未定或未凑满,回到读循环
                continue
            if buf and time.time() - last_rx > GAP_IDLE:
                # 帧间隔判定兜底:静默超时仍凑不齐预期长度(未知 FC/半帧),按整段处理
                frame = bytes(buf)
                buf.clear()
                log("[从站] 帧间隔收尾(未匹配预期长度,{}B)".format(len(frame)))
                self.process_frame(frame)
            else:
                time.sleep(POLL_IDLE)

    def stop(self, *_args):
        self._running = False


# ---------------- 命令行 ----------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="零依赖 Modbus RTU 从站模拟器(FC 1,2,3,4,5,6,15,16,com0com 虚拟对用)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--port", default="COM4", help="本从站占用串口(虚拟对 B 端)")
    parser.add_argument("--baud", type=int, default=9600,
                        help="标称波特率(com0com 虚拟对忽略,仅配置 DCB)")
    parser.add_argument("--unit", type=int, default=1, help="单播从站地址(1-247)")
    parser.add_argument("--size", type=int, default=10000,
                        help="每个内存区元素个数(有效地址 0..size-1)")
    parser.add_argument("--coils", default="", help="线圈种子, 如 0=1,3=0")
    parser.add_argument("--discrete-inputs", default="", help="离散输入种子, 如 2=1")
    parser.add_argument("--holding", default="", help="保持寄存器种子, 如 0=1234,1=5678")
    parser.add_argument("--input-registers", default="", help="输入寄存器种子, 如 0=42")
    parser.add_argument("--corrupt-next", action="store_true",
                        help="劣化注入:下一个响应帧故意坏 CRC(仅一帧,之后自动恢复正常)")
    parser.add_argument("--verbose", action="store_true", help="打印每帧收发日志")
    return parser


def main():
    args = build_parser().parse_args()
    if not (1 <= args.unit <= 247):
        raise SystemExit("[参数错误] --unit 必须在 1..247")
    if args.size <= 0:
        raise SystemExit("[参数错误] --size 必须为正整数")

    mem = ModbusMemory(args.size)
    mem.seed(mem.coils,    parse_seed(args.coils, "coils"),                     True,  "coils")
    mem.seed(mem.discrete, parse_seed(args.discrete_inputs, "discrete-inputs"), True,  "discrete-inputs")
    mem.seed(mem.holding,  parse_seed(args.holding, "holding"),                 False, "holding")
    mem.seed(mem.input,    parse_seed(args.input_registers, "input-registers"), False, "input-registers")

    app = RtuSlaveApp(args.port, args.baud, args.unit, mem, args.corrupt_next, args.verbose)
    try:
        signal.signal(signal.SIGINT, app.stop)
        signal.signal(signal.SIGTERM, app.stop)
    except (ValueError, OSError, AttributeError):
        pass

    log("[从站] Modbus RTU 从站启动: 串口 {} @ {} 8N1(虚拟对忽略波特率) | unitId={} "
        "| FC 1,2,3,4,5,6,15,16 | 广播(unitId=0)写执行不回帧".format(
            args.port, args.baud, args.unit))
    for flag, text in (("--coils", args.coils),
                       ("--discrete-inputs", args.discrete_inputs),
                       ("--holding", args.holding),
                       ("--input-registers", args.input_registers)):
        if text.strip():
            log("[从站] 种子 {} {}".format(flag, text.strip()))
    if args.corrupt_next:
        log("[从站] 劣化注入 --corrupt-next: 下一个响应帧将故意携带坏 CRC(仅一帧)")
    log("[从站] Ctrl+C 停止")

    try:
        app.run()
    finally:
        app.port.close()
        log("[从站] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
