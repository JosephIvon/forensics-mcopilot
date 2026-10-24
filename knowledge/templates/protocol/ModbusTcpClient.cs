// ============================================================================
//  Modbus TCP 客户端（零第三方依赖）
//  —— 由 mcopilot protocol 生成；C# 7.3，可在 .NET Framework 4.8 直接编译。
//
//  本文件同时承载 TCP / RTU 两路共用的「静态纯函数层」（不碰 IO，可单测）：
//    - ModbusFunctionCode  功能码常量
//    - ModbusConst         协议常量（每条常量旁留 spec_ref 占位，待与 modbus.json 对账）
//    - ModbusPdu           PDU 构造/解析（功能码级，与传输层无关）
//    - ModbusSlaveException 从机异常响应（功能码|0x80 + 异常码 → 带名称的消息）
//    - ModbusWordOrder / ModbusRegisters  双寄存器 UInt32 组合（字序 ABCD/CDAB 可配）
//    - ModbusTcpFrame      MBAP 帧构造/解析（TCP 专用）
//  CRC16 与 RTU 帧构造在 ModbusRtuClient.cs。
//
//  字节序约定：Modbus 网络序 = 大端（高字节在前）。
//  spec_ref(字节序): MODBUS Application Protocol V1.1b3 §4.2, 待与 modbus.json 对账。
// ============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;

namespace Mcopilot.Protocols.Modbus
{
    /// <summary>Modbus 功能码。spec_ref: MODBUS Application Protocol V1.1b3 §6 表格, 待与 modbus.json 对账。</summary>
    public static class ModbusFunctionCode
    {
        /// <summary>读线圈（1..2000 个）。spec_ref: V1.1b3 §6.1, 待对账。</summary>
        public const byte ReadCoils = 0x01;
        /// <summary>读离散输入（1..2000 个）。spec_ref: V1.1b3 §6.2, 待对账。</summary>
        public const byte ReadDiscreteInputs = 0x02;
        /// <summary>读保持寄存器（1..125 个）。spec_ref: V1.1b3 §6.3, 待对账。</summary>
        public const byte ReadHoldingRegisters = 0x03;
        /// <summary>读输入寄存器（1..125 个）。spec_ref: V1.1b3 §6.4, 待对账。</summary>
        public const byte ReadInputRegisters = 0x04;
        /// <summary>写单线圈。spec_ref: V1.1b3 §6.5, 待对账。</summary>
        public const byte WriteSingleCoil = 0x05;
        /// <summary>写单寄存器。spec_ref: V1.1b3 §6.6, 待对账。</summary>
        public const byte WriteSingleRegister = 0x06;
        /// <summary>写多线圈（1..1968 个）。spec_ref: V1.1b3 §6.11, 待对账。</summary>
        public const byte WriteMultipleCoils = 0x0F;
        /// <summary>写多寄存器（1..123 个）。spec_ref: V1.1b3 §6.12, 待对账。</summary>
        public const byte WriteMultipleRegisters = 0x10;
    }

    /// <summary>协议常量。每条常量旁的 spec_ref 是占位，后续与 knowledge/protocols 提取结果对账。</summary>
    public static class ModbusConst
    {
        /// <summary>MBAP 协议标识符：0 = Modbus 传输协议。spec_ref: MODBUS Messaging on TCP/IP V1.0b §3.1 MBAP 报文头, 待与 modbus.json 对账。</summary>
        public const ushort ProtocolId = 0x0000;
        /// <summary>Modbus TCP 默认端口。spec_ref: MODBUS Messaging on TCP/IP V1.0b §2.1（IANA 注册端口 502）, 待对账。</summary>
        public const int DefaultTcpPort = 502;
        /// <summary>PDU 最大 253 字节（不含 MBAP / 地址与 CRC）。spec_ref: V1.1b3 §4.1 "max size of a PDU is 253 bytes", 待对账。</summary>
        public const int MaxPduSize = 253;
        /// <summary>ADU 上限 = 地址(1) + PDU(253)（RTU 尺寸约束）。spec_ref: V1.1b3 §4.1, 待对账。</summary>
        public const int MaxRtuAduSize = 256;
        /// <summary>FC1/FC2 一次最多读 2000（0x07D0）个位。spec_ref: V1.1b3 §6.1/§6.2, 待对账。</summary>
        public const int MaxReadBits = 2000;
        /// <summary>FC1/FC2 响应 Byte Count 上限 = ceil(2000/8) = 250（0xFA）。
        /// spec_ref: V1.1b3 §6.1/§6.2（Byte count = N*，N 为 Quantity/8 向上取整，Quantity ≤ 2000）, 待对账。
        /// 2026-10-21 对齐修正：旧值 0xF5(245) 为笔误——1969..2000 个位的合法响应（247..250 字节）会被误拒。</summary>
        public const int MaxBitResponseBytes = 250;
        /// <summary>FC3/FC4 一次最多读 125（0x007D）个寄存器。spec_ref: V1.1b3 §6.3/§6.4, 待对账。</summary>
        public const int MaxReadRegisters = 125;
        /// <summary>FC15 一次最多写 1968（0x07B0）个线圈。spec_ref: V1.1b3 §6.11, 待对账。</summary>
        public const int MaxWriteBits = 1968;
        /// <summary>FC16 一次最多写 123（0x007B）个寄存器。spec_ref: V1.1b3 §6.12, 待对账。</summary>
        public const int MaxWriteRegisters = 123;
        /// <summary>FC5 写线圈"ON"的值必须是 0xFF00。spec_ref: V1.1b3 §6.5.1, 待对账。</summary>
        public const ushort CoilOn = 0xFF00;
        /// <summary>FC5 写线圈"OFF"的值必须是 0x0000。spec_ref: V1.1b3 §6.5.1, 待对账。</summary>
        public const ushort CoilOff = 0x0000;
        /// <summary>异常响应 = 功能码 | 0x80。spec_ref: V1.1b3 §7, 待对账。</summary>
        public const byte ExceptionFlag = 0x80;
        /// <summary>RTU 广播地址 = 0（所有从站必须识别；广播仅限写命令且无响应）。
        /// spec_ref: modbus.json limits_and_timeouts.broadcast_semantics（address=0）——
        /// MODBUS over Serial Line V1.02 §2.1 p7 "The address 0 is reserved to identify a
        /// broadcast exchange"。2026-10-21 已对账。</summary>
        public const byte BroadcastAddress = 0x00;
    }

    /// <summary>
    /// 从机异常响应（功能码 | 0x80 + 异常码）转成的托管异常。
    /// 消息文本包含异常码名称（如 "ILLEGAL FUNCTION"），可直接进日志。
    /// </summary>
    public class ModbusSlaveException : Exception
    {
        /// <summary>从机返回的原始功能码（已剥离 0x80 标志）。</summary>
        public byte FunctionCode { get; private set; }
        /// <summary>从机返回的异常码（0x01..0x0B）。spec_ref: V1.1b3 §7, 待对账。</summary>
        public byte ExceptionCode { get; private set; }

        /// <summary>用功能码与异常码构造；消息形如 "Modbus 从机异常 (FC=3): ILLEGAL FUNCTION (0x01)"。</summary>
        public ModbusSlaveException(byte functionCode, byte exceptionCode)
            : base(string.Format(
                CultureInfo.InvariantCulture,
                "Modbus 从机异常 (FC={0}): {1} (0x{2:X2})",
                functionCode, GetExceptionName(exceptionCode), exceptionCode))
        {
            FunctionCode = functionCode;
            ExceptionCode = exceptionCode;
        }

        /// <summary>异常码 → 标准名称（如 0x01 → "ILLEGAL FUNCTION"）。
        /// spec_ref: MODBUS Application Protocol V1.1b3 §7 异常码表, 待与 modbus.json 对账。
        /// 2026-10-21 对齐：0x04/0x06 按该表原文定为 "SERVER DEVICE FAILURE/BUSY"
        ///（旧措辞 "SLAVE DEVICE *" 为同义异名，已弃用；modbus.json exception_codes 同名）。</summary>
        public static string GetExceptionName(byte exceptionCode)
        {
            switch (exceptionCode)
            {
                case 0x01: return "ILLEGAL FUNCTION";
                case 0x02: return "ILLEGAL DATA ADDRESS";
                case 0x03: return "ILLEGAL DATA VALUE";
                case 0x04: return "SERVER DEVICE FAILURE";
                case 0x05: return "ACKNOWLEDGE";
                case 0x06: return "SERVER DEVICE BUSY";
                case 0x08: return "MEMORY PARITY ERROR";
                case 0x0A: return "GATEWAY PATH UNAVAILABLE";
                case 0x0B: return "GATEWAY TARGET DEVICE FAILED TO RESPOND";
                default: return "UNKNOWN EXCEPTION CODE";
            }
        }
    }

    /// <summary>
    /// 双寄存器（32 位值）的字序约定。PLC/变频器里 32 位量拆成两个 16 位寄存器时
    /// 字的先后顺序因品牌而异，必须可配。
    /// </summary>
    public enum ModbusWordOrder
    {
        /// <summary>大端字序：高位字（Most Significant Word）在低地址寄存器。例：0x12345678 → [0x1234, 0x5678]。</summary>
        ABCD,
        /// <summary>字交换：低位字在低地址寄存器。例：0x12345678 → [0x5678, 0x1234]。
        /// 注：本枚举只覆盖"字交换"最常见的 CDAB；BADC/DCBA 字节交换另在调用方处理，不进本层。</summary>
        CDAB
    }

    /// <summary>UInt32 与双寄存器互转（字序 ABCD/CDAB 可配，字节内永远大端）。static 纯函数，可单测。</summary>
    public static class ModbusRegisters
    {
        /// <summary>UInt32 → 两个寄存器。ABCD：[高字, 低字]；CDAB：[低字, 高字]。</summary>
        public static ushort[] ToRegisters(uint value, ModbusWordOrder wordOrder)
        {
            ushort hi = (ushort)(value >> 16);          // 高 16 位（大端机器序的高字）
            ushort lo = (ushort)(value & 0xFFFFu);      // 低 16 位
            return wordOrder == ModbusWordOrder.ABCD
                ? new ushort[] { hi, lo }
                : new ushort[] { lo, hi };
        }

        /// <summary>两个寄存器 → UInt32。ABCD：first=高字；CDAB：first=低字。</summary>
        public static uint ToUInt32(ushort firstRegister, ushort secondRegister, ModbusWordOrder wordOrder)
        {
            return wordOrder == ModbusWordOrder.ABCD
                ? ((uint)firstRegister << 16) | (uint)secondRegister
                : ((uint)secondRegister << 16) | (uint)firstRegister;
        }
    }

    /// <summary>
    /// PDU（协议数据单元）构造与解析：功能码 + 数据，不含 MBAP、地址与 CRC。
    /// 全部 static 纯函数，输入 byte[] 输出 byte[]，可独立单测。
    /// </summary>
    public static class ModbusPdu
    {
        // ---- 请求构造 ----------------------------------------------------

        /// <summary>构造读请求 PDU（FC1/2/3/4 共用）：[fc, 地址Hi, 地址Lo, 数量Hi, 数量Lo]。</summary>
        public static byte[] BuildReadRequest(byte functionCode, ushort startAddress, ushort quantity)
        {
            ValidateReadQuantity(functionCode, quantity);
            byte[] pdu = new byte[5];
            pdu[0] = functionCode;
            WriteU16(pdu, 1, startAddress);
            WriteU16(pdu, 3, quantity);
            return pdu;
        }

        /// <summary>构造 FC5 写单线圈请求 PDU：[0x05, 地址Hi, 地址Lo, 0xFF/0x00, 0x00]。</summary>
        public static byte[] BuildWriteSingleCoilRequest(ushort address, bool value)
        {
            byte[] pdu = new byte[5];
            pdu[0] = ModbusFunctionCode.WriteSingleCoil;
            WriteU16(pdu, 1, address);
            WriteU16(pdu, 3, value ? ModbusConst.CoilOn : ModbusConst.CoilOff);
            return pdu;
        }

        /// <summary>构造 FC6 写单寄存器请求 PDU：[0x06, 地址Hi, 地址Lo, 值Hi, 值Lo]。</summary>
        public static byte[] BuildWriteSingleRegisterRequest(ushort address, ushort value)
        {
            byte[] pdu = new byte[5];
            pdu[0] = ModbusFunctionCode.WriteSingleRegister;
            WriteU16(pdu, 1, address);
            WriteU16(pdu, 3, value);
            return pdu;
        }

        /// <summary>构造 FC15 写多线圈请求 PDU：[0x0F, 地址, 数量, 字节数, 位数据(LSB 在前)]。</summary>
        public static byte[] BuildWriteMultipleCoilsRequest(ushort address, bool[] values)
        {
            if (values == null) throw new ArgumentNullException("values");
            if (values.Length < 1 || values.Length > ModbusConst.MaxWriteBits)
                throw new ArgumentOutOfRangeException("values", "FC15 线圈数量必须在 1.." + ModbusConst.MaxWriteBits);
            byte[] packed = PackBits(values);
            byte[] pdu = new byte[6 + packed.Length];
            pdu[0] = ModbusFunctionCode.WriteMultipleCoils;
            WriteU16(pdu, 1, address);
            WriteU16(pdu, 3, (ushort)values.Length);
            pdu[5] = (byte)packed.Length;
            Buffer.BlockCopy(packed, 0, pdu, 6, packed.Length);
            return pdu;
        }

        /// <summary>构造 FC16 写多寄存器请求 PDU：[0x10, 地址, 数量, 字节数, 寄存器数据(大端)]。</summary>
        public static byte[] BuildWriteMultipleRegistersRequest(ushort address, ushort[] values)
        {
            if (values == null) throw new ArgumentNullException("values");
            if (values.Length < 1 || values.Length > ModbusConst.MaxWriteRegisters)
                throw new ArgumentOutOfRangeException("values", "FC16 寄存器数量必须在 1.." + ModbusConst.MaxWriteRegisters);
            byte[] pdu = new byte[6 + values.Length * 2];
            pdu[0] = ModbusFunctionCode.WriteMultipleRegisters;
            WriteU16(pdu, 1, address);
            WriteU16(pdu, 3, (ushort)values.Length);
            pdu[5] = (byte)(values.Length * 2);
            for (int i = 0; i < values.Length; i++)
                WriteU16(pdu, 6 + i * 2, values[i]);
            return pdu;
        }

        // ---- 响应解析 ----------------------------------------------------

        /// <summary>若 PDU 是异常响应（功能码|0x80），抛 ModbusSlaveException；否则原样返回。</summary>
        public static void EnsureNotException(byte[] pdu)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length < 2) throw new IOException("Modbus 响应 PDU 过短：" + pdu.Length + " 字节");
            if ((pdu[0] & ModbusConst.ExceptionFlag) != 0)
                throw new ModbusSlaveException((byte)(pdu[0] & 0x7F), pdu[1]);
        }

        /// <summary>解析 FC1/FC2 位响应 PDU：[fc, 字节数, 位数据...] → bool[]（LSB 在前）。</summary>
        public static bool[] ParseBitResponse(byte[] pdu, byte expectedFunctionCode)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length < 3) throw new IOException("FC" + expectedFunctionCode + " 响应过短");
            if (pdu[0] != expectedFunctionCode)
                throw new IOException(string.Format(CultureInfo.InvariantCulture,
                    "响应功能码不匹配：期望 0x{0:X2}，实际 0x{1:X2}", expectedFunctionCode, pdu[0]));
            int byteCount = pdu[1];
            // P1-1 修正：上限 = ceil(MaxReadBits/8) = 250（旧值 0xF5=245 会误拒 1969..2000 位的合法响应）
            if (byteCount < 1 || byteCount > ModbusConst.MaxBitResponseBytes || byteCount != pdu.Length - 2)
                throw new IOException("FC" + expectedFunctionCode + " 响应字节数字段与帧长不符：" + byteCount);
            int bitCount = byteCount * 8;   // 尾部填充位解析时自然丢弃，数量由调用方已知
            bool[] bits = new bool[bitCount];
            for (int i = 0; i < bitCount; i++)
                bits[i] = (pdu[2 + i / 8] >> (i % 8) & 1) != 0;
            return bits;
        }

        /// <summary>解析 FC3/FC4 寄存器响应 PDU：[fc, 字节数, 寄存器数据(大端)...] → ushort[]。</summary>
        public static ushort[] ParseRegisterResponse(byte[] pdu, byte expectedFunctionCode)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length < 3) throw new IOException("FC" + expectedFunctionCode + " 响应过短");
            if (pdu[0] != expectedFunctionCode)
                throw new IOException(string.Format(CultureInfo.InvariantCulture,
                    "响应功能码不匹配：期望 0x{0:X2}，实际 0x{1:X2}", expectedFunctionCode, pdu[0]));
            int byteCount = pdu[1];
            if (byteCount < 1 || byteCount > ModbusConst.MaxPduSize - 2 || byteCount != pdu.Length - 2)
                throw new IOException("FC" + expectedFunctionCode + " 响应字节数字段与帧长不符：" + byteCount);
            if ((byteCount & 1) != 0)
                throw new IOException("FC" + expectedFunctionCode + " 响应字节数必须是偶数：" + byteCount);
            ushort[] regs = new ushort[byteCount / 2];
            for (int i = 0; i < regs.Length; i++)
                regs[i] = (ushort)((pdu[2 + i * 2] << 8) | pdu[3 + i * 2]);
            return regs;
        }

        /// <summary>校验 FC5/6/15/16 回显响应 PDU（响应即请求头 5 字节 / 6 字节的镜像）。</summary>
        public static void VerifyEchoResponse(byte[] pdu, byte expectedFunctionCode, ushort address, ushort valueOrQuantity)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length != 5) throw new IOException("FC" + expectedFunctionCode + " 回显响应长度必须为 5，实际 " + pdu.Length);
            if (pdu[0] != expectedFunctionCode)
                throw new IOException(string.Format(CultureInfo.InvariantCulture,
                    "响应功能码不匹配：期望 0x{0:X2}，实际 0x{1:X2}", expectedFunctionCode, pdu[0]));
            ushort rxAddress = (ushort)((pdu[1] << 8) | pdu[2]);
            ushort rxValue = (ushort)((pdu[3] << 8) | pdu[4]);
            if (rxAddress != address || rxValue != valueOrQuantity)
                throw new IOException(string.Format(CultureInfo.InvariantCulture,
                    "回显响应不匹配：期望 地址=0x{0:X4} 值=0x{1:X4}，实际 地址=0x{2:X4} 值=0x{3:X4}",
                    address, valueOrQuantity, rxAddress, rxValue));
        }

        // ---- 位/字节工具 -------------------------------------------------

        /// <summary>bool[] → 位打包字节（每个字节 LSB 是最低位线圈）。FC1/2/15 共用此打包规则。
        /// spec_ref: V1.1b3 §6.1 响应与 §6.11 请求 "LSB of the first data byte", 待对账。</summary>
        public static byte[] PackBits(bool[] values)
        {
            if (values == null) throw new ArgumentNullException("values");
            byte[] data = new byte[(values.Length + 7) / 8];
            for (int i = 0; i < values.Length; i++)
                if (values[i]) data[i / 8] |= (byte)(1 << (i % 8));
            return data;
        }

        /// <summary>按功能码校验读数量范围（FC1/2: 1..2000；FC3/4: 1..125）。</summary>
        public static void ValidateReadQuantity(byte functionCode, ushort quantity)
        {
            bool isBit = functionCode == ModbusFunctionCode.ReadCoils || functionCode == ModbusFunctionCode.ReadDiscreteInputs;
            bool isReg = functionCode == ModbusFunctionCode.ReadHoldingRegisters || functionCode == ModbusFunctionCode.ReadInputRegisters;
            if (!isBit && !isReg)
                throw new ArgumentOutOfRangeException("functionCode", "读请求功能码必须是 FC1/2/3/4");
            int max = isBit ? ModbusConst.MaxReadBits : ModbusConst.MaxReadRegisters;
            if (quantity < 1 || quantity > max)
                throw new ArgumentOutOfRangeException("quantity", "FC" + functionCode + " 读数量必须在 1.." + max);
        }

        /// <summary>
        /// 读响应数量交叉校验（P1-2）：实收 < 请求 → IOException，信息含请求量与实收量。
        /// 防护「劣化从站短读」：帧本身合法（MBAP 长度/CRC 自洽），但数据量不足请求量——
        /// 静默返回短数组会让上层把缺失数据当真值。注意：此处帧流仍处于同步状态，不置毒化
        /// （毒化语义见 ModbusTcpClient.ExecuteTransaction——仅传输/帧级错误触发）。
        /// </summary>
        public static void EnsureReadCount(int returned, int requested, byte functionCode)
        {
            if (returned < requested)
                throw new IOException(string.Format(CultureInfo.InvariantCulture,
                    "FC{0} 从站短读：请求 {1}，实收 {2}（响应数量不足，疑似劣化从站或链路丢数据）",
                    functionCode, requested, returned));
        }

        /// <summary>大端写入 ushort。Modbus 网络序。spec_ref: V1.1b3 §4.2, 待对账。</summary>
        public static void WriteU16(byte[] buffer, int offset, ushort value)
        {
            buffer[offset] = (byte)(value >> 8);
            buffer[offset + 1] = (byte)(value & 0xFF);
        }
    }

    /// <summary>
    /// MBAP 帧构造与解析（TCP 专用）。static 纯函数，可单测。
    /// 帧格式：[事务标识Hi,Lo][协议标识Hi,Lo=0][长度Hi,Lo][单元标识符][PDU...]，
    /// 长度字段 = 单元标识符(1) + PDU 字节数。
    /// spec_ref: MODBUS Messaging on TCP/IP V1.0b §3.1, 待与 modbus.json 对账。
    /// </summary>
    public static class ModbusTcpFrame
    {
        /// <summary>MBAP 报文头固定 7 字节。</summary>
        public const int HeaderSize = 7;

        /// <summary>构造完整 TCP 请求帧（MBAP + PDU）。协议标识固定 0，长度 = pdu.Length + 1。</summary>
        public static byte[] BuildRequestFrame(ushort transactionId, byte unitId, byte[] pdu)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length < 1 || pdu.Length > ModbusConst.MaxPduSize)
                throw new ArgumentOutOfRangeException("pdu", "PDU 长度必须在 1.." + ModbusConst.MaxPduSize);
            byte[] frame = new byte[HeaderSize + pdu.Length];
            frame[0] = (byte)(transactionId >> 8);              // 事务标识符（大端）
            frame[1] = (byte)(transactionId & 0xFF);
            frame[2] = (byte)(ModbusConst.ProtocolId >> 8);     // 协议标识符 = 0x0000
            frame[3] = (byte)(ModbusConst.ProtocolId & 0xFF);
            int length = pdu.Length + 1;                        // 长度 = PDU + 单元标识符
            frame[4] = (byte)(length >> 8);
            frame[5] = (byte)(length & 0xFF);
            frame[6] = unitId;                                  // 单元标识符
            Buffer.BlockCopy(pdu, 0, frame, HeaderSize, pdu.Length);
            return frame;
        }

        /// <summary>解析 MBAP 报文头（恰好 7 字节）。失败返回 false（协议标识非 0 / 长度非法）。</summary>
        public static bool TryParseHeader(byte[] header, out ushort transactionId, out ushort protocolId,
            out ushort length, out byte unitId)
        {
            transactionId = 0; protocolId = 0; length = 0; unitId = 0;
            if (header == null || header.Length != HeaderSize) return false;
            transactionId = (ushort)((header[0] << 8) | header[1]);
            protocolId = (ushort)((header[2] << 8) | header[3]);
            length = (ushort)((header[4] << 8) | header[5]);
            unitId = header[6];
            if (protocolId != ModbusConst.ProtocolId) return false;          // 协议标识必须为 0
            if (length < 2 || length > ModbusConst.MaxPduSize + 1) return false; // 长度至少含 FC+异常码
            return true;
        }
    }

    /// <summary>
    /// Modbus TCP 客户端（零第三方依赖，基于 System.Net.Sockets.TcpClient）。
    /// 单连接串行事务：同一时刻只允许一个请求在途（内部加锁），事务标识符自动递增。
    /// 线程安全：方法级串行化；不支持的用法是多连接复用（需每连接一个实例）。
    /// </summary>
    public sealed class ModbusTcpClient : IDisposable
    {
        private readonly string _host;
        private readonly int _port;
        private readonly int _connectTimeoutMs;
        private readonly object _ioLock = new object();
        private TcpClient _tcp;
        private NetworkStream _stream;
        private ushort _transactionId;
        private int _receiveTimeoutMs;
        private int _sendTimeoutMs;
        /// <summary>
        /// 毒化标志（P1-3）：一次事务中出现任何 IOException / InvalidDataException / TimeoutException
        /// （含 MBAP 头解析失败、事务/单元标识校验失败）即置位并 Close()。置位后所有公开方法入口
        /// 拒绝服务——出错后的字节流位置已不可信（可能残留半帧），继续复用只会得到错位/TID 错乱等
        /// 诡异错误。恢复路径 = 重连：Connect() 用全新 socket 复活实例（见其 _poison = false）。
        /// </summary>
        private bool _poison;

        /// <summary>构造。host 可以是 IP 或主机名；端口默认 502；三个超时均可配。</summary>
        public ModbusTcpClient(string host, int port = ModbusConst.DefaultTcpPort,
            int connectTimeoutMs = 3000, int receiveTimeoutMs = 1000, int sendTimeoutMs = 1000)
        {
            if (string.IsNullOrEmpty(host)) throw new ArgumentNullException("host");
            if (port < 1 || port > 65535) throw new ArgumentOutOfRangeException("port");
            _host = host;
            _port = port;
            _connectTimeoutMs = connectTimeoutMs;
            _receiveTimeoutMs = receiveTimeoutMs;
            _sendTimeoutMs = sendTimeoutMs;
        }

        /// <summary>是否已连接（TcpClient 层面）。</summary>
        public bool IsConnected
        {
            get { return _tcp != null && _tcp.Connected; }
        }

        /// <summary>最近一次使用的事务标识符（调试用；发送前自增）。</summary>
        public ushort LastTransactionId
        {
            get { lock (_ioLock) { return _transactionId; } }
        }

        /// <summary>事务标识符自增（0xFFFF 后回绕）。spec_ref: MODBUS Messaging on TCP/IP V1.0b §3.1（事务标识符由客户端生成）, 待对账。</summary>
        private ushort NextTransactionId()
        {
            _transactionId++;   // lock 内调用；ushort 溢出自然回绕
            return _transactionId;
        }

        /// <summary>
        /// 建立 TCP 连接（带可配超时；连接后流超时按构造参数设置）。
        /// P1-3「出错即重连」：毒化后的实例可用本方法以全新连接复活（成功后清除 _poison）；
        /// P3：旧 _tcp/_stream 先 Close 再覆盖，避免半开 socket 泄漏。
        /// </summary>
        public void Connect()
        {
            lock (_ioLock)
            {
                if (IsConnected && !_poison) return;
                if (_tcp != null || _stream != null) Close();   // P3：旧连接先关（幂等），再建新连接
                var tcp = new TcpClient();
                try
                {
                    IAsyncResult ar = tcp.BeginConnect(_host, _port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(_connectTimeoutMs, false))
                        throw new TimeoutException(string.Format(CultureInfo.InvariantCulture,
                            "连接 {0}:{1} 超时（{2} ms）", _host, _port, _connectTimeoutMs));
                    tcp.EndConnect(ar);
                    tcp.NoDelay = true;   // P3：禁 Nagle，单事务小帧立即发出（Modbus 一问一答模式受益）
                }
                catch
                {
                    tcp.Close();    // 连接失败必须释放半开 socket
                    throw;
                }
                _tcp = tcp;
                _stream = _tcp.GetStream();
                _stream.ReadTimeout = _receiveTimeoutMs;
                _stream.WriteTimeout = _sendTimeoutMs;
                _poison = false;    // 全新连接建立成功，毒化状态解除
            }
        }

        /// <summary>关闭连接（幂等，可重复调用）。</summary>
        public void Close()
        {
            lock (_ioLock)
            {
                if (_stream != null) { try { _stream.Close(); } catch { } _stream = null; }
                if (_tcp != null) { try { _tcp.Close(); } catch { } _tcp = null; }
            }
        }

        /// <summary>释放资源（等价 Close）。</summary>
        public void Dispose() { Close(); }

        /// <summary>
        /// 低层事务（P2 契约测试用）：requestPdu 为完整 PDU（功能码 + 参数）。
        /// 业务代码请用类型化方法。spec_ref: MODBUS Application Protocol V1.1b3 §5（PDU = 功能码 + 数据）。
        /// </summary>
        public byte[] TransactRaw(byte unitId, byte[] requestPdu)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            return ExecuteTransaction(unitId, requestPdu);
        }

        /// <summary>执行一次完整事务：MBAP 封帧 → 发送 → 收响应 → 事务标识/单元标识校验 → 返回响应 PDU。异常响应在此抛 ModbusSlaveException。
        /// P1-3：任何 IOException / InvalidDataException / TimeoutException（含头解析、TID/单元标识校验失败）
        /// 都会置 _poison 并 Close()——出错即重连，后续调用在公开方法入口被拒绝。</summary>
        private byte[] ExecuteTransaction(byte unitId, byte[] requestPdu)
        {
            lock (_ioLock)
            {
                if (_poison)
                    throw new InvalidOperationException("连接已因协议/网络错误失效，请重连");
                if (!IsConnected)
                    throw new InvalidOperationException("Modbus TCP 未连接，请先调用 Connect()。");
                ushort tid = NextTransactionId();
                byte[] frame = ModbusTcpFrame.BuildRequestFrame(tid, unitId, requestPdu);
                try
                {
                    _stream.Write(frame, 0, frame.Length);
                }
                catch (Exception ex)
                {
                    PoisonAndClose();   // 发送失败同为传输级错误：毒化 + 断开
                    throw new IOException("Modbus TCP 发送失败：" + ex.Message, ex);
                }

                try
                {
                    byte[] header = ReadExact(ModbusTcpFrame.HeaderSize);
                    ushort rxTid, rxPid, rxLen; byte rxUnit;
                    if (!ModbusTcpFrame.TryParseHeader(header, out rxTid, out rxPid, out rxLen, out rxUnit))
                        throw new InvalidDataException("MBAP 报文头非法（协议标识非 0 或长度字段越界）");
                    if (rxTid != tid)
                        throw new InvalidDataException(string.Format(CultureInfo.InvariantCulture,
                            "事务标识不匹配：发送 0x{0:X4}，收到 0x{1:X4}", tid, rxTid));
                    if (rxUnit != unitId)
                        throw new InvalidDataException(string.Format(CultureInfo.InvariantCulture,
                            "单元标识不匹配：发送 {0}，收到 {1}", unitId, rxUnit));
                    return ReadExact(rxLen - 1);    // 长度字段含单元标识符，已在头部消耗 1
                }
                catch (IOException) { PoisonAndClose(); throw; }
                catch (InvalidDataException) { PoisonAndClose(); throw; }
                catch (TimeoutException) { PoisonAndClose(); throw; }
            }
        }

        /// <summary>P1-3：传输/帧级错误 → 置毒化并断开（锁内调用，Monitor 可重入故 Close 安全）。</summary>
        private void PoisonAndClose()
        {
            _poison = true;
            try { Close(); } catch { }
        }

        /// <summary>P1-3：公开方法入口毒化检查。置位后抛 InvalidOperationException（信息注明「请重连」）。</summary>
        private void EnsureNotPoisoned()
        {
            if (_poison)
                throw new InvalidOperationException("连接已因协议/网络错误失效，请重连");
        }

        /// <summary>精确读取 n 字节（流式 Read 可能短读，必须补齐）。</summary>
        private byte[] ReadExact(int count)
        {
            byte[] buf = new byte[count];
            int got = 0;
            while (got < count)
            {
                int n;
                try { n = _stream.Read(buf, got, count - got); }
                catch (Exception ex) { throw new IOException("Modbus TCP 接收失败：" + ex.Message, ex); }
                if (n <= 0) throw new IOException("连接在对帧过程中被远端关闭");
                got += n;
            }
            return buf;
        }

        // ---- 公开读写方法（TCP 每个请求显式携带单元标识符，便于经网关访问多从机）----

        /// <summary>FC1 读线圈：1..2000 个，返回按位展开的 bool[]（数量恒等于 quantity，尾部填充位已裁剪）。</summary>
        public bool[] ReadCoils(byte unitId, ushort startAddress, ushort quantity)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadCoils, startAddress, quantity));
            ModbusPdu.EnsureNotException(pdu);
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils);
            ModbusPdu.EnsureReadCount(bits.Length, quantity, ModbusFunctionCode.ReadCoils);   // P1-2：短读防护
            if (bits.Length > quantity) Array.Resize(ref bits, quantity);   // 契约：要多少给多少，填充位不外泄
            return bits;
        }

        /// <summary>FC2 读离散输入：1..2000 个（数量恒等于 quantity）。</summary>
        public bool[] ReadDiscreteInputs(byte unitId, ushort startAddress, ushort quantity)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadDiscreteInputs, startAddress, quantity));
            ModbusPdu.EnsureNotException(pdu);
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadDiscreteInputs);
            ModbusPdu.EnsureReadCount(bits.Length, quantity, ModbusFunctionCode.ReadDiscreteInputs);   // P1-2：短读防护
            if (bits.Length > quantity) Array.Resize(ref bits, quantity);
            return bits;
        }

        /// <summary>FC3 读保持寄存器：1..125 个，返回 ushort[]（大端已解出）。</summary>
        public ushort[] ReadHoldingRegisters(byte unitId, ushort startAddress, ushort quantity)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadHoldingRegisters, startAddress, quantity));
            ModbusPdu.EnsureNotException(pdu);
            ushort[] regs = ModbusPdu.ParseRegisterResponse(pdu, ModbusFunctionCode.ReadHoldingRegisters);
            ModbusPdu.EnsureReadCount(regs.Length, quantity, ModbusFunctionCode.ReadHoldingRegisters);   // P1-2：短读防护
            return regs;
        }

        /// <summary>FC4 读输入寄存器：1..125 个。</summary>
        public ushort[] ReadInputRegisters(byte unitId, ushort startAddress, ushort quantity)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadInputRegisters, startAddress, quantity));
            ModbusPdu.EnsureNotException(pdu);
            ushort[] regs = ModbusPdu.ParseRegisterResponse(pdu, ModbusFunctionCode.ReadInputRegisters);
            ModbusPdu.EnsureReadCount(regs.Length, quantity, ModbusFunctionCode.ReadInputRegisters);   // P1-2：短读防护
            return regs;
        }

        /// <summary>FC5 写单线圈（false→0x0000，true→0xFF00）。校验从机回显。</summary>
        public void WriteSingleCoil(byte unitId, ushort address, bool value)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            ushort coil = value ? ModbusConst.CoilOn : ModbusConst.CoilOff;
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildWriteSingleCoilRequest(address, value));
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteSingleCoil, address, coil);
        }

        /// <summary>FC6 写单寄存器。校验从机回显。</summary>
        public void WriteSingleRegister(byte unitId, ushort address, ushort value)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildWriteSingleRegisterRequest(address, value));
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteSingleRegister, address, value);
        }

        /// <summary>FC15 写多线圈：1..1968 个，LSB 在前打包。</summary>
        public void WriteMultipleCoils(byte unitId, ushort address, bool[] values)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildWriteMultipleCoilsRequest(address, values));
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteMultipleCoils, address, (ushort)values.Length);
        }

        /// <summary>FC16 写多寄存器：1..123 个，大端上送。</summary>
        public void WriteMultipleRegisters(byte unitId, ushort address, ushort[] values)
        {
            EnsureNotPoisoned();    // P1-3：毒化后拒绝服务
            byte[] pdu = ExecuteTransaction(unitId, ModbusPdu.BuildWriteMultipleRegistersRequest(address, values));
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteMultipleRegisters, address, (ushort)values.Length);
        }
    }
}
