// ============================================================================
//  Modbus 帧级黄金测试（零第三方依赖，可编译为库也可驱动运行）
//  —— 由 mcopilot protocol 生成；C# 7.3，可在 .NET Framework 4.8 直接编译。
//
//  测试策略：**不依赖真机/仿真器**，只做「已知请求字节序列 ↔ 预期字节序列」的
//  帧级黄金测试。所有 CRC 黄金值由参考实现生成，参考实现本身已用两个独立公认
//  校验值验证：
//    1) CRC16/MODBUS 目录标准校验值："123456789" → 0x4B37
//    2) MODBUS over Serial Line V1.02 规范示例：11 03 00 6B 00 03 → 帧尾 76 87
//
//  运行方式：编译成 exe 或用外部驱动调用 ModbusFrameTests.RunAll()，
//  返回 TestReport（Total/Passed/Failed + 失败明细），退出语义由驱动决定。
// ============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Mcopilot.Protocols.Modbus
{
    /// <summary>断言失败异常（仅测试内部使用）。</summary>
    internal class TestFailureException : Exception
    {
        public TestFailureException(string message) : base(message) { }
    }

    /// <summary>测试汇总：总数 / 通过 / 失败 + 失败明细。</summary>
    public sealed class ModbusTestReport
    {
        /// <summary>用例总数。</summary>
        public int Total;
        /// <summary>通过数。</summary>
        public int Passed;
        /// <summary>失败数。</summary>
        public int Failed;
        /// <summary>失败用例明细（"名称：原因"）。</summary>
        public readonly List<string> Failures = new List<string>();

        /// <summary>一行式汇总文本（进日志友好）。</summary>
        public string Summary()
        {
            return string.Format(CultureInfo.InvariantCulture,
                "Modbus 黄金测试：{0}/{1} 通过，{2} 失败{3}",
                Passed, Total, Failed, Failures.Count > 0 ? "｜" + string.Join("；", Failures.ToArray()) : "");
        }
    }

    /// <summary>帧级黄金测试集。static 纯函数集合 + RunAll 汇总运行。</summary>
    public static class ModbusFrameTests
    {
        /// <summary>运行全部黄金测试，返回汇总报告（不抛异常，失败进报告）。</summary>
        public static ModbusTestReport RunAll()
        {
            var report = new ModbusTestReport();
            // 名称 + 用例本体，逐条登记（保持 C# 7.3 兼容，不玩反射）
            var cases = new List<KeyValuePair<string, Action>>
            {
                new KeyValuePair<string, Action>("CRC16_目录标准校验值", TestCrc16CatalogCheckValue),
                new KeyValuePair<string, Action>("CRC16_规范示例_从机11读保持寄存器", TestCrc16SpecExample),
                new KeyValuePair<string, Action>("TCP_MBAP构造黄金_FC3读保持寄存器", TestTcpBuildFc3),
                new KeyValuePair<string, Action>("TCP_MBAP构造黄金_规范从机11", TestTcpBuildFc3SpecUnit),
                new KeyValuePair<string, Action>("TCP_MBAP构造黄金_FC5写单线圈", TestTcpBuildFc5),
                new KeyValuePair<string, Action>("TCP_MBAP头解析黄金", TestTcpParseHeader),
                new KeyValuePair<string, Action>("TCP_MBAP拒绝非法帧", TestTcpRejectsBadHeader),
                new KeyValuePair<string, Action>("RTU黄金_FC3请求加CRC", TestRtuBuildFc3),
                new KeyValuePair<string, Action>("RTU黄金_FC5写单线圈加CRC", TestRtuBuildFc5),
                new KeyValuePair<string, Action>("RTU黄金_FC6写单寄存器加CRC", TestRtuBuildFc6),
                new KeyValuePair<string, Action>("RTU黄金_FC15写多线圈加CRC", TestRtuBuildFc15),
                new KeyValuePair<string, Action>("RTU黄金_FC16写多寄存器加CRC", TestRtuBuildFc16),
                new KeyValuePair<string, Action>("RTU黄金_广播FC6写单寄存器_unit0加CRC", TestRtuBuildBroadcastFc6),
                new KeyValuePair<string, Action>("RTU黄金_广播FC16写多寄存器_unit0全帧", TestRtuBuildBroadcastFc16),
                new KeyValuePair<string, Action>("RTU广播_turnaround延迟常量_对齐modbusjson", TestBroadcastTurnaroundConstants),
                new KeyValuePair<string, Action>("RTU广播_非广播地址或读命令_参数拒绝", TestBroadcastRejectsInvalid),
                new KeyValuePair<string, Action>("RTU黄金_FC3响应解析规范示例", TestRtuParseFc3Response),
                new KeyValuePair<string, Action>("RTU黄金_FC1位响应解析", TestRtuParseFc1Response),
                new KeyValuePair<string, Action>("RTU_CRC损坏拒绝解析", TestRtuRejectsBadCrc),
                new KeyValuePair<string, Action>("RTU_过短帧拒绝解析", TestRtuRejectsShortFrame),
                new KeyValuePair<string, Action>("异常响应解析_ILLEGAL FUNCTION", TestExceptionIllegalFunction),
                new KeyValuePair<string, Action>("异常RTU帧级黄金_ILLEGAL DATA ADDRESS", TestExceptionIllegalDataAddress),
                new KeyValuePair<string, Action>("UInt32双寄存器组合_ABCD字序", TestUInt32WordOrderAbcd),
                new KeyValuePair<string, Action>("UInt32双寄存器组合_CDAB字序", TestUInt32WordOrderCdab),
                new KeyValuePair<string, Action>("t3.5帧间隔_按波特率计算", TestT35Timing),
                new KeyValuePair<string, Action>("RTU响应剩余长度推算", TestRemainingResponseLength),
                new KeyValuePair<string, Action>("TCP_FC1位响应_250字节上限_2000位解析通过", TestBitResponseMaxBytesAccepted),
                new KeyValuePair<string, Action>("TCP_FC1位响应_251字节_越界拒绝", TestBitResponseOverMaxRejected),
                new KeyValuePair<string, Action>("TCP_FC1位响应_1969位_247字节解析通过", TestBitResponse1969Bits),
                new KeyValuePair<string, Action>("RTU响应剩余长度推算_FC1大批量_1969与2000", TestRemainingLengthLargeBitQuantities)
            };

            foreach (var c in cases)
            {
                report.Total++;
                try
                {
                    c.Value();
                    report.Passed++;
                }
                catch (TestFailureException ex)
                {
                    report.Failed++;
                    report.Failures.Add(c.Key + "：" + ex.Message);
                }
                catch (Exception ex)
                {
                    report.Failed++;
                    report.Failures.Add(c.Key + "：意外异常 " + ex.GetType().Name + " " + ex.Message);
                }
            }
            return report;
        }

        // ---- 断言工具 ----------------------------------------------------

        private static void AssertBytes(byte[] expected, byte[] actual, string context)
        {
            if (expected == null || actual == null)
                throw new TestFailureException(context + "：存在 null 数组");
            if (expected.Length != actual.Length)
                throw new TestFailureException(string.Format(CultureInfo.InvariantCulture,
                    "{0}：长度不符（期望 {1}，实际 {2}）", context, expected.Length, actual.Length));
            for (int i = 0; i < expected.Length; i++)
                if (expected[i] != actual[i])
                    throw new TestFailureException(string.Format(CultureInfo.InvariantCulture,
                        "{0}：第 {1} 字节不符（期望 0x{2:X2}，实际 0x{3:X2}）",
                        context, i, expected[i], actual[i]));
        }

        private static void AssertTrue(bool condition, string message)
        {
            if (!condition) throw new TestFailureException(message);
        }

        private static byte[] Hex(params byte[] bytes) { return bytes; }

        // ---- CRC16 黄金 --------------------------------------------------

        /// <summary>锚点一：CRC16/MODBUS 目录标准校验值，"123456789"（ASCII）→ 0x4B37。</summary>
        private static void TestCrc16CatalogCheckValue()
        {
            byte[] ascii = Encoding.ASCII.GetBytes("123456789");
            ushort crc = ModbusCrc16.Compute(ascii);
            AssertTrue(crc == 0x4B37,
                string.Format(CultureInfo.InvariantCulture, "\"123456789\" 的 CRC 应为 0x4B37，实际 0x{0:X4}", crc));
        }

        /// <summary>锚点二：MODBUS over Serial Line V1.02 规范示例 11 03 00 6B 00 03 → 帧尾 76 87（低前高后）。</summary>
        private static void TestCrc16SpecExample()
        {
            // 注意：BuildFrame 会自行加从机地址，PDU 只含功能码+数据
            byte[] pdu = Hex(0x03, 0x00, 0x6B, 0x00, 0x03);
            ushort crc = ModbusCrc16.Compute(Hex(0x11, 0x03, 0x00, 0x6B, 0x00, 0x03));
            AssertTrue(crc == 0x8776,
                string.Format(CultureInfo.InvariantCulture, "规范示例请求的 CRC 应为 0x8776，实际 0x{0:X4}", crc));
            byte[] frame = ModbusRtuFrame.BuildFrame(0x11, pdu);
            AssertBytes(Hex(0x11, 0x03, 0x00, 0x6B, 0x00, 0x03, 0x76, 0x87), frame, "规范示例 RTU 帧");
        }

        // ---- TCP / MBAP 黄金 ---------------------------------------------

        /// <summary>FC3 请求黄金帧：tid=0x1234、unit=1、读 0x006B 起 3 个保持寄存器。</summary>
        private static void TestTcpBuildFc3()
        {
            byte[] pdu = ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadHoldingRegisters, 0x006B, 3);
            AssertBytes(Hex(0x03, 0x00, 0x6B, 0x00, 0x03), pdu, "FC3 请求 PDU");
            byte[] frame = ModbusTcpFrame.BuildRequestFrame(0x1234, 0x01, pdu);
            AssertBytes(Hex(0x12, 0x34, 0x00, 0x00, 0x00, 0x06, 0x01, 0x03, 0x00, 0x6B, 0x00, 0x03),
                frame, "TCP FC3 完整帧");
        }

        /// <summary>规范从机 0x11 的同请求：tid=0x0001。</summary>
        private static void TestTcpBuildFc3SpecUnit()
        {
            byte[] pdu = ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadHoldingRegisters, 0x006B, 3);
            byte[] frame = ModbusTcpFrame.BuildRequestFrame(0x0001, 0x11, pdu);
            AssertBytes(Hex(0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x11, 0x03, 0x00, 0x6B, 0x00, 0x03),
                frame, "TCP FC3 帧（从机 0x11）");
        }

        /// <summary>FC5 写单线圈黄金帧：tid=0x0005、unit=1、写 0x0063 = ON。</summary>
        private static void TestTcpBuildFc5()
        {
            byte[] pdu = ModbusPdu.BuildWriteSingleCoilRequest(0x0063, true);
            AssertBytes(Hex(0x05, 0x00, 0x63, 0xFF, 0x00), pdu, "FC5 请求 PDU");
            byte[] frame = ModbusTcpFrame.BuildRequestFrame(0x0005, 0x01, pdu);
            AssertBytes(Hex(0x00, 0x05, 0x00, 0x00, 0x00, 0x06, 0x01, 0x05, 0x00, 0x63, 0xFF, 0x00),
                frame, "TCP FC5 完整帧");
        }

        /// <summary>MBAP 头解析：tid/pid/长度/单元标识逐字段校验。</summary>
        private static void TestTcpParseHeader()
        {
            ushort tid, pid, len; byte unit;
            bool ok = ModbusTcpFrame.TryParseHeader(
                Hex(0x12, 0x34, 0x00, 0x00, 0x00, 0x06, 0x01), out tid, out pid, out len, out unit);
            AssertTrue(ok, "合法 MBAP 头应解析成功");
            AssertTrue(tid == 0x1234 && pid == 0 && len == 6 && unit == 0x01,
                string.Format(CultureInfo.InvariantCulture,
                    "MBAP 字段不符：tid=0x{0:X4} pid={1} len={2} unit={3}", tid, pid, len, unit));
        }

        /// <summary>协议标识非 0 / 长度越界的头必须拒绝。</summary>
        private static void TestTcpRejectsBadHeader()
        {
            ushort tid, pid, len; byte unit;
            // 协议标识 0x0001 ≠ 0
            AssertTrue(!ModbusTcpFrame.TryParseHeader(
                Hex(0x00, 0x01, 0x00, 0x01, 0x00, 0x06, 0x01), out tid, out pid, out len, out unit),
                "协议标识非 0 必须拒绝");
            // 长度 < 2（装不下 功能码+异常码）
            AssertTrue(!ModbusTcpFrame.TryParseHeader(
                Hex(0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x01), out tid, out pid, out len, out unit),
                "长度字段 <2 必须拒绝");
        }

        // ---- RTU 黄金 ----------------------------------------------------

        /// <summary>任务指定黄金向量：01 03 00 6B 00 03 + CRC = 01 03 00 6B 00 03 74 17。</summary>
        private static void TestRtuBuildFc3()
        {
            byte[] pdu = ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadHoldingRegisters, 0x006B, 3);
            byte[] frame = ModbusRtuFrame.BuildFrame(0x01, pdu);
            AssertBytes(Hex(0x01, 0x03, 0x00, 0x6B, 0x00, 0x03, 0x74, 0x17), frame, "RTU FC3 请求帧");
        }

        /// <summary>FC5 黄金：01 05 00 00 FF 00 + CRC = 8C 3A（低前高后）。</summary>
        private static void TestRtuBuildFc5()
        {
            byte[] pdu = ModbusPdu.BuildWriteSingleCoilRequest(0x0000, true);
            byte[] frame = ModbusRtuFrame.BuildFrame(0x01, pdu);
            AssertBytes(Hex(0x01, 0x05, 0x00, 0x00, 0xFF, 0x00, 0x8C, 0x3A), frame, "RTU FC5 请求帧");
        }

        /// <summary>FC6 黄金：01 06 00 01 00 03 + CRC = 98 0B。</summary>
        private static void TestRtuBuildFc6()
        {
            byte[] pdu = ModbusPdu.BuildWriteSingleRegisterRequest(0x0001, 0x0003);
            byte[] frame = ModbusRtuFrame.BuildFrame(0x01, pdu);
            AssertBytes(Hex(0x01, 0x06, 0x00, 0x01, 0x00, 0x03, 0x98, 0x0B), frame, "RTU FC6 请求帧");
        }

        /// <summary>FC15 黄金：写 0x00 起的 10 个线圈（CD 01 的 LSB-first 展开）→ 数据 CD 01，帧尾 CRC 70 68。</summary>
        private static void TestRtuBuildFc15()
        {
            // 0xCD = 1100 1101，LSB 在前 → 线圈0..7 = {1,0,1,1,0,0,1,1}；0x01 → 线圈8=1, 线圈9=0
            var coils = new bool[] { true, false, true, true, false, false, true, true, true, false };
            byte[] pdu = ModbusPdu.BuildWriteMultipleCoilsRequest(0x0000, coils);
            AssertBytes(Hex(0x0F, 0x00, 0x00, 0x00, 0x0A, 0x02, 0xCD, 0x01), pdu, "FC15 请求 PDU（位打包）");
            byte[] frame = ModbusRtuFrame.BuildFrame(0x01, pdu);
            AssertBytes(Hex(0x01, 0x0F, 0x00, 0x00, 0x00, 0x0A, 0x02, 0xCD, 0x01, 0x70, 0x68),
                frame, "RTU FC15 请求帧");
        }

        /// <summary>FC16 黄金：写 0x0001 起两个寄存器 {0x000A, 0x0102}（V1.1b3 §6.12 示例数据），帧尾 CRC 92 30。</summary>
        private static void TestRtuBuildFc16()
        {
            var regs = new ushort[] { 0x000A, 0x0102 };
            byte[] pdu = ModbusPdu.BuildWriteMultipleRegistersRequest(0x0001, regs);
            AssertBytes(Hex(0x10, 0x00, 0x01, 0x00, 0x02, 0x04, 0x00, 0x0A, 0x01, 0x02), pdu, "FC16 请求 PDU");
            byte[] frame = ModbusRtuFrame.BuildFrame(0x01, pdu);
            AssertBytes(Hex(0x01, 0x10, 0x00, 0x01, 0x00, 0x02, 0x04, 0x00, 0x0A, 0x01, 0x02, 0x92, 0x30),
                frame, "RTU FC16 请求帧");
        }

        // ---- RTU 广播黄金（unitId=0；2026-10-21 对齐 modbus.json broadcast_semantics）----

        /// <summary>广播 FC6 黄金（字节级）：00 06 00 01 00 03 + CRC=0xDA99（低前高后 → 99 DA）。
        /// 与单播 FC6 黄金（地址 0x01、CRC 0x0B98）仅地址字节之差。黄金向量由与两个已验证
        /// 锚点（目录校验值 0x4B37、规范示例 0x8776）同算法的参考实现生成。</summary>
        private static void TestRtuBuildBroadcastFc6()
        {
            byte[] pdu = ModbusPdu.BuildWriteSingleRegisterRequest(0x0001, 0x0003);
            byte[] frame = ModbusRtuFrame.BuildFrame(ModbusConst.BroadcastAddress, pdu);
            AssertBytes(Hex(0x00, 0x06, 0x00, 0x01, 0x00, 0x03, 0x99, 0xDA), frame, "RTU 广播 FC6 请求帧");
        }

        /// <summary>广播 FC16 黄金（全帧）：00 10 00 01 00 02 04 00 0A 01 02 + CRC=0xCC96（96 CC）。
        /// 广播地址 0 + FC16 写 0x0001 起两个寄存器 {0x000A, 0x0102}。</summary>
        private static void TestRtuBuildBroadcastFc16()
        {
            var regs = new ushort[] { 0x000A, 0x0102 };
            byte[] pdu = ModbusPdu.BuildWriteMultipleRegistersRequest(0x0001, regs);
            byte[] frame = ModbusRtuFrame.BuildFrame(ModbusConst.BroadcastAddress, pdu);
            AssertBytes(Hex(0x00, 0x10, 0x00, 0x01, 0x00, 0x02, 0x04, 0x00, 0x0A, 0x01, 0x02, 0x96, 0xCC),
                frame, "RTU 广播 FC16 请求帧");
        }

        /// <summary>广播 turnaround delay 常量必须 = modbus.json
        /// limits_and_timeouts.serial_turnaround_delay_after_broadcast 条目值：
        /// 典型区间 100-200ms（下界 100 / 上界 200），实现取中值 150ms。
        /// spec_ref: MODBUS over Serial Line V1.02 §2.4.1 p10。广播地址常量一并钉值。</summary>
        private static void TestBroadcastTurnaroundConstants()
        {
            AssertTrue(ModbusConst.BroadcastAddress == 0x00,
                "广播地址应为 0（Serial Line V1.02 §2.1：地址 0 保留为广播）");
            AssertTrue(ModbusRtuClient.BroadcastTurnaroundDelayMinMs == 100,
                "BroadcastTurnaroundDelayMinMs 应为 100（modbus.json：典型 100-200ms 下界）");
            AssertTrue(ModbusRtuClient.BroadcastTurnaroundDelayMaxMs == 200,
                "BroadcastTurnaroundDelayMaxMs 应为 200（modbus.json：典型 100-200ms 上界）");
            AssertTrue(ModbusRtuClient.BroadcastTurnaroundDelayMs == 150,
                "BroadcastTurnaroundDelayMs 应为 150（modbus.json 区间 100-200ms 的中值）");
        }

        /// <summary>广播参数护栏（纯参数校验，先于串口访问，无需真机）：非 0 地址、
        /// 读命令（FC3）广播必须被 ArgumentException 拒绝——把 modbus.json
        /// broadcast_semantics 的「地址 0 + 仅写命令」钉成行为。</summary>
        private static void TestBroadcastRejectsInvalid()
        {
            var client = new ModbusRtuClient("COMGOLDENTEST", 9600);   // 仅构造，不 Open()
            Exception wrongAddr = null;
            try { client.SendBroadcast(0x01, Hex(0x06, 0x00, 0x01, 0x00, 0x03)); }
            catch (Exception ex) { wrongAddr = ex; }
            AssertTrue(wrongAddr is ArgumentException,
                "非广播地址（0x01）必须被 ArgumentException 拒绝，实际 " +
                (wrongAddr == null ? "<未抛>" : wrongAddr.GetType().Name));
            Exception readBroadcast = null;
            try { client.SendBroadcast(ModbusConst.BroadcastAddress, Hex(0x03, 0x00, 0x6B, 0x00, 0x03)); }
            catch (Exception ex) { readBroadcast = ex; }
            AssertTrue(readBroadcast is ArgumentException,
                "读命令（FC3）广播必须被 ArgumentException 拒绝，实际 " +
                (readBroadcast == null ? "<未抛>" : readBroadcast.GetType().Name));
        }

        /// <summary>FC3 响应黄金（V1.1b3 §6.3 示例数据 0x022B/0x0106/0x0000）：01 03 06 02 2B 01 06 00 00 E5 6C。</summary>
        private static void TestRtuParseFc3Response()
        {
            byte[] frame = Hex(0x01, 0x03, 0x06, 0x02, 0x2B, 0x01, 0x06, 0x00, 0x00, 0xE5, 0x6C);
            byte addr; byte[] pdu;
            AssertTrue(ModbusRtuFrame.TryParseFrame(frame, frame.Length, out addr, out pdu), "FC3 响应帧 CRC 应通过");
            AssertTrue(addr == 0x01, "从机地址应为 1");
            ushort[] regs = ModbusPdu.ParseRegisterResponse(pdu, ModbusFunctionCode.ReadHoldingRegisters);
            AssertTrue(regs.Length == 3 && regs[0] == 0x022B && regs[1] == 0x0106 && regs[2] == 0x0000,
                "FC3 响应寄存器值应为 {0x022B, 0x0106, 0x0000}");
        }

        /// <summary>FC1 位响应黄金：01 01 01 CD 90 1D → 0xCD 按位展开 {T,F,T,T,F,T,T,F}。</summary>
        private static void TestRtuParseFc1Response()
        {
            byte[] frame = Hex(0x01, 0x01, 0x01, 0xCD, 0x90, 0x1D);
            byte addr; byte[] pdu;
            AssertTrue(ModbusRtuFrame.TryParseFrame(frame, frame.Length, out addr, out pdu), "FC1 响应帧 CRC 应通过");
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils);
            // 0xCD = 1100 1101，LSB 在前 → 第一个线圈对应 bit0
            var expected = new bool[] { true, false, true, true, false, false, true, true };
            AssertTrue(bits.Length == expected.Length, "位数量应为 8");
            for (int i = 0; i < expected.Length; i++)
                AssertTrue(bits[i] == expected[i], "第 " + i + " 位不符（0xCD 展开）");
        }

        /// <summary>CRC 损坏（翻转一位）必须拒绝解析。</summary>
        private static void TestRtuRejectsBadCrc()
        {
            byte[] frame = Hex(0x01, 0x03, 0x00, 0x6B, 0x00, 0x03, 0x74, 0x17);
            frame[2] ^= 0x01;   // 破坏数据，CRC 随之失配
            byte addr; byte[] pdu;
            AssertTrue(!ModbusRtuFrame.TryParseFrame(frame, frame.Length, out addr, out pdu),
                "CRC 失配的帧必须拒绝");
        }

        /// <summary>短于最小帧（地址+功能码+CRC=4）的输入必须拒绝。</summary>
        private static void TestRtuRejectsShortFrame()
        {
            byte addr; byte[] pdu;
            AssertTrue(!ModbusRtuFrame.TryParseFrame(Hex(0x01, 0x83), 2, out addr, out pdu), "2 字节输入必须拒绝");
        }

        // ---- 异常响应黄金 -------------------------------------------------

        /// <summary>PDU 83 01 → FC3 异常、ILLEGAL FUNCTION，消息含名称。</summary>
        private static void TestExceptionIllegalFunction()
        {
            // PDU 层：EnsureNotException 必须抛出且信息含名称
            Exception thrown = null;
            try { ModbusPdu.EnsureNotException(Hex(0x83, 0x01)); }
            catch (Exception ex) { thrown = ex; }
            AssertTrue(thrown is ModbusSlaveException, "83 01 必须抛 ModbusSlaveException");
            var slave = (ModbusSlaveException)thrown;
            AssertTrue(slave.FunctionCode == 0x03 && slave.ExceptionCode == 0x01, "异常帧字段应为 FC=3, 码=0x01");
            AssertTrue(slave.Message.Contains("ILLEGAL FUNCTION"), "异常消息应包含 ILLEGAL FUNCTION：" + slave.Message);

            // 名称表抽查
            AssertTrue(ModbusSlaveException.GetExceptionName(0x02) == "ILLEGAL DATA ADDRESS", "0x02 名称表不符");
            AssertTrue(ModbusSlaveException.GetExceptionName(0x04) == "SERVER DEVICE FAILURE",
                "0x04 名称表不符（应对齐 V1.1b3 §7 表：SERVER DEVICE FAILURE）");
            AssertTrue(ModbusSlaveException.GetExceptionName(0x06) == "SERVER DEVICE BUSY",
                "0x06 名称表不符（应对齐 V1.1b3 §7 表：SERVER DEVICE BUSY）");
            AssertTrue(ModbusSlaveException.GetExceptionName(0xFF) == "UNKNOWN EXCEPTION CODE", "未知码应给 UNKNOWN");
        }

        /// <summary>异常 RTU 帧级黄金：01 83 02 C0 F1（CRC=0xF1C0，低前高后）→ 解析出 ILLEGAL DATA ADDRESS。</summary>
        private static void TestExceptionIllegalDataAddress()
        {
            byte[] frame = Hex(0x01, 0x83, 0x02, 0xC0, 0xF1);
            byte addr; byte[] pdu;
            AssertTrue(ModbusRtuFrame.TryParseFrame(frame, frame.Length, out addr, out pdu), "异常帧 CRC 应通过");
            Exception thrown = null;
            try { ModbusPdu.EnsureNotException(pdu); }
            catch (Exception ex) { thrown = ex; }
            AssertTrue(thrown is ModbusSlaveException, "异常 PDU 必须抛 ModbusSlaveException");
            AssertTrue(((ModbusSlaveException)thrown).ExceptionCode == 0x02, "异常码应为 0x02");
            AssertTrue(thrown.Message.Contains("ILLEGAL DATA ADDRESS"), "消息应含 ILLEGAL DATA ADDRESS：" + thrown.Message);
        }

        // ---- UInt32 双寄存器字序黄金 ---------------------------------------

        /// <summary>ABCD：0x12345678 → [0x1234, 0x5678]（高字在前），往返一致。</summary>
        private static void TestUInt32WordOrderAbcd()
        {
            ushort[] regs = ModbusRegisters.ToRegisters(0x12345678u, ModbusWordOrder.ABCD);
            AssertTrue(regs.Length == 2 && regs[0] == 0x1234 && regs[1] == 0x5678,
                string.Format(CultureInfo.InvariantCulture, "ABCD 应为 [0x1234,0x5678]，实际 [0x{0:X4},0x{1:X4}]", regs[0], regs[1]));
            AssertTrue(ModbusRegisters.ToUInt32(regs[0], regs[1], ModbusWordOrder.ABCD) == 0x12345678u, "ABCD 往返不一致");
        }

        /// <summary>CDAB：0x12345678 → [0x5678, 0x1234]（低字在前），往返一致。</summary>
        private static void TestUInt32WordOrderCdab()
        {
            ushort[] regs = ModbusRegisters.ToRegisters(0x12345678u, ModbusWordOrder.CDAB);
            AssertTrue(regs.Length == 2 && regs[0] == 0x5678 && regs[1] == 0x1234,
                string.Format(CultureInfo.InvariantCulture, "CDAB 应为 [0x5678,0x1234]，实际 [0x{0:X4},0x{1:X4}]", regs[0], regs[1]));
            AssertTrue(ModbusRegisters.ToUInt32(regs[0], regs[1], ModbusWordOrder.CDAB) == 0x12345678u, "CDAB 往返不一致");
        }

        // ---- RTU 时序黄金 --------------------------------------------------

        /// <summary>t3.5：9600bps ≈ 4.0104ms（≈4ms），19200 ≈ 2.0104，38400（>19200）固定 1.75ms。</summary>
        private static void TestT35Timing()
        {
            double t9600 = ModbusRtuClient.CalcT35Milliseconds(9600);
            AssertTrue(Math.Abs(t9600 - 4.0104) < 0.001,
                string.Format(CultureInfo.InvariantCulture, "9600bps 的 t3.5 应≈4.0104ms，实际 {0:F4}ms", t9600));
            double t19200 = ModbusRtuClient.CalcT35Milliseconds(19200);
            AssertTrue(Math.Abs(t19200 - 2.0052) < 0.001,
                string.Format(CultureInfo.InvariantCulture, "19200bps 的 t3.5 应≈2.0052ms，实际 {0:F4}ms", t19200));
            double t38400 = ModbusRtuClient.CalcT35Milliseconds(38400);
            AssertTrue(Math.Abs(t38400 - 1.75) < 0.0001,
                string.Format(CultureInfo.InvariantCulture, "38400bps 的 t3.5 应为固定 1.75ms，实际 {0:F4}ms", t38400));
        }

        /// <summary>响应剩余长度推算（收帧依据）：FC3 数量 3 → 1+6+2=9；FC1 数量 20 → 1+3+2=6；FC16 → 6。</summary>
        private static void TestRemainingResponseLength()
        {
            AssertTrue(ModbusRtuClient.GetRemainingResponseLength(ModbusFunctionCode.ReadHoldingRegisters, 3) == 9,
                "FC3 数量 3 的剩余长度应为 9");
            AssertTrue(ModbusRtuClient.GetRemainingResponseLength(ModbusFunctionCode.ReadCoils, 20) == 6,
                "FC1 数量 20 的剩余长度应为 6");
            AssertTrue(ModbusRtuClient.GetRemainingResponseLength(ModbusFunctionCode.WriteMultipleRegisters, 2) == 6,
                "FC16 回显剩余长度应为 6");
        }

        // ---- P1-1：位响应 Byte Count 上限 250 黄金（旧值 0xF5=245 会误拒 1969..2000 位）----

        /// <summary>构造 FC1 位响应 PDU：[fc, byteCount, data...]。</summary>
        private static byte[] BuildBitResponsePdu(byte functionCode, int byteCount, byte fill)
        {
            byte[] pdu = new byte[2 + byteCount];
            pdu[0] = functionCode;
            pdu[1] = (byte)byteCount;
            for (int i = 0; i < byteCount; i++) pdu[2 + i] = fill;
            return pdu;
        }

        /// <summary>上限黄金：byteCount=250（=ceil(2000/8)，ModbusConst.MaxBitResponseBytes）必须被接受，展开 2000 位。</summary>
        private static void TestBitResponseMaxBytesAccepted()
        {
            AssertTrue(ModbusConst.MaxBitResponseBytes == 250, "MaxBitResponseBytes 常量应为 250（ceil(2000/8)）");
            // 全 0xFF 数据：250 字节 → 2000 位全 ON
            byte[] pdu = BuildBitResponsePdu(ModbusFunctionCode.ReadCoils, ModbusConst.MaxBitResponseBytes, 0xFF);
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils);
            AssertTrue(bits.Length == 2000, "250 字节位响应应展开为 2000 位，实际 " + bits.Length);
            for (int i = 0; i < bits.Length; i++)
                if (!bits[i]) throw new TestFailureException("全 0xFF 位响应第 " + i + " 位应为 true");
        }

        /// <summary>越界拒绝：byteCount=251（> ceil(2000/8)=250）必须抛 IOException——上限恰好 250，不多不少。</summary>
        private static void TestBitResponseOverMaxRejected()
        {
            byte[] pdu = BuildBitResponsePdu(ModbusFunctionCode.ReadCoils, ModbusConst.MaxBitResponseBytes + 1, 0x00);
            Exception thrown = null;
            try { ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils); }
            catch (Exception ex) { thrown = ex; }
            AssertTrue(thrown is System.IO.IOException, "byteCount=251 必须抛 IOException，实际 " +
                (thrown == null ? "<未抛>" : thrown.GetType().Name));
        }

        /// <summary>1969 位黄金：byteCount=247（=ceil(1969/8)，> 旧错误上限 245）必须被接受；
        /// PDU 层保留填充位（247×8=1976 位），类型化层负责裁剪到 1969。</summary>
        private static void TestBitResponse1969Bits()
        {
            int quantity = 1969;
            int byteCount = (quantity + 7) / 8;     // 247 > 0xF5(245)：旧实现会在此误拒
            byte[] pdu = BuildBitResponsePdu(ModbusFunctionCode.ReadCoils, byteCount, 0xA5); // 1010 0101
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils);
            AssertTrue(bits.Length == byteCount * 8, "247 字节位响应应展开为 " + byteCount * 8 + " 位，实际 " + bits.Length);
            // 0xA5 = 1010 0101（LSB 在前）：bit0=true, bit1=false, bit2=true, bit3=false, bit4=false, bit5=true, bit6=false, bit7=true
            var expectedBits = new bool[] { true, false, true, false, false, true, false, true };
            for (int b = 0; b < 8; b++)
                AssertTrue(bits[b] == expectedBits[b],
                    "0xA5 展开第 " + b + " 位应为 " + expectedBits[b]);
            AssertTrue(bits[quantity - 1] == expectedBits[(quantity - 1) % 8],
                "第 1969 位（索引 1968）应与 0xA5 位型一致");
        }

        /// <summary>RTU 收帧长度推算黄金（P1-1 配套）：FC1 数量 1969 → 1+247+2=250；数量 2000 → 1+250+2=253（≤ ADU 上限 256）。</summary>
        private static void TestRemainingLengthLargeBitQuantities()
        {
            AssertTrue(ModbusRtuClient.GetRemainingResponseLength(ModbusFunctionCode.ReadCoils, 1969) == 250,
                "FC1 数量 1969 的剩余长度应为 250（1+247+2）");
            AssertTrue(ModbusRtuClient.GetRemainingResponseLength(ModbusFunctionCode.ReadCoils, 2000) == 253,
                "FC1 数量 2000 的剩余长度应为 253（1+250+2）");
        }
    }
}
