// ============================================================================
//  ModbusContractTests.cs —— Modbus TCP 行为契约测试集
//
//  与帧级黄金测试（ModbusFrameTests，验证字节级帧构造/解析）的区别：
//  本套件把 C# 客户端接到真实从站模拟器（tests/fixtures/modbus/modbus_tcp_slave.py，
//  监听 127.0.0.1:15020，须以 --holding 0=1234,1=5678 预置种子）上，验证运行时行为契约：
//    1. FC3 读种子寄存器（0=1234, 1=5678）值正确
//    2. FC6 写后 FC3 回读一致；FC16 批量写后逐个回读一致；FC5/FC15 线圈写读一致
//    3. FC3 数量 0 → 从站异常码 03；FC3 地址越界 → 02；不支持 FC（0x07）→ 01
//    4. 事务标识符回显校验（线缆层 + 客户端关联层）
//    5. 连续 50 次读写无错（小型压力）；断线重连后仍可用
//    6. FC1 大批量 1969/2000 位往返（P1-1：位响应 Byte Count 上限 250 的回归）
//    7. 劣化从站短读 → IOException（P1-2，本地劣化桩伪造短响应）
//    8. 坏帧 → 连接毒化 → 后续调用 InvalidOperationException，重连恢复（P1-3）
//    9. 分片压测（--fragment split3 实例@15021）：响应拆 3 段先后到达，FC3 种子读 +
//       FC6 写读回全对——验证主站按 MBAP 长度补齐重组
//   10. 极端分片（--fragment byte1 实例@15022）：逐字节滴流，FC16 批量写 + FC3 回读
//       全对——验证 ReadExact 循环真重组而非"一次 Read 当整帧"的运气
//   11. 粘包/残帧→毒化闭环（--sticky-stale 1 实例@15023）：每响应附发旧 TID 陈旧帧占住
//       管道，第二事务必毒化——断言拿到 InvalidOperationException("…失效…请重连") 而非
//       诡异 TID 错；Connect() 复活后读/写路径正常（P1-3 端到端验证）
//   14. 异常码扫掠（--exception-sweep 实例@15024，2026-10-21 门禁轮新增）：连发 8 请求，
//       从站按序回异常码 01,02,03,05,06,08,0A,0B——逐请求断言 ModbusSlaveException 且
//       名称逐一精确匹配（含 0x06=SERVER DEVICE BUSY；0x04=SERVER DEVICE FAILURE 由
//       名称表单独钉住），把 V1.1b3 §7 表改名钉成契约
//
//  阶段编排（与 run_contract.ps1 三阶段 + 门禁 sweep 阶段一一对应，各实例独立端口）：
//    RunPhase("normal")   → 15020 正常从站（上面 1-8，15 条）
//    RunPhase("fragment") → 15021(split3) + 15022(byte1)（9-10，2 条）
//    RunPhase("sticky")   → 15023(sticky-stale)（11，1 条）
//    RunPhase("sweep")    → 15024(exception-sweep)（14，1 条；scripts/gate_protocol.ps1 G3 驱动）
//    RunAll() 保持向后兼容 = RunPhase("normal")。
//
//  C# 5 兼容写法（.NET Framework 4 自带 csc.exe 可直接编译），零第三方依赖。
//  每条用例独立建连，写操作只落在 >=100 的高地址段，绝不触碰 0/1 号种子寄存器，
//  因此用例顺序无关、互不污染。RunAll() 汇总执行并返回逐条结果。
// ============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using Mcopilot.Protocols.Modbus;

namespace Mcopilot.Protocols.Modbus.ContractTests
{
    /// <summary>单条契约用例的执行结果。</summary>
    public sealed class ContractCaseResult
    {
        /// <summary>用例名（如 "FC3_ReadSeededRegisters"）。</summary>
        public string Name { get; private set; }
        /// <summary>true = PASS。</summary>
        public bool Passed { get; private set; }
        /// <summary>失败原因；通过时为空。</summary>
        public string Detail { get; private set; }

        public ContractCaseResult(string name, bool passed, string detail)
        {
            Name = name;
            Passed = passed;
            Detail = detail == null ? "" : detail;
        }
    }

    /// <summary>契约断言失败（区别于 IO/协议异常：这是"行为不符合契约"）。</summary>
    public sealed class ContractFailureException : Exception
    {
        public ContractFailureException(string message) : base(message) { }
    }

    /// <summary>Modbus TCP 行为契约测试集：static 用例集合 + RunAll() 汇总运行。</summary>
    public static class ModbusContractTests
    {
        /// <summary>从站模拟器地址（modbus_tcp_slave.py 默认监听 127.0.0.1:15020）。</summary>
        public const string SlaveHost = "127.0.0.1";
        public const int SlavePort = 15020;
        /// <summary>分片劣化实例（--fragment split3：每响应拆 3 段发送）独立端口。</summary>
        public const int FragmentSplit3Port = 15021;
        /// <summary>极端分片实例（--fragment byte1：逐字节滴流）独立端口。</summary>
        public const int FragmentByte1Port = 15022;
        /// <summary>粘包/残帧实例（--sticky-stale 1：每响应附发旧 TID 陈旧帧）独立端口。</summary>
        public const int StickyStalePort = 15023;
        /// <summary>异常码扫掠实例（--exception-sweep：每请求按序回异常码 01,02,03,05,06,08,0A,0B 循环）独立端口。</summary>
        public const int ExceptionSweepPort = 15024;
        /// <summary>从站单元标识符（模拟器原样回显任意值，统一用 1）。</summary>
        public const byte UnitId = 1;

        // 写操作安全区：全部 >=100，避开种子寄存器 0/1。
        private const ushort AddrFc6 = 100;
        private const ushort AddrFc16 = 200;
        private const ushort AddrFc5 = 300;
        private const ushort AddrFc15 = 400;
        private const ushort AddrStress = 900;
        /// <summary>FC1 大批量往返用例的线圈区基址（1000+2000 ≤ 从站每区 10000）。</summary>
        private const ushort AddrBulkCoils = 1000;

        private sealed class CaseDef
        {
            public readonly string Name;
            public readonly Action<ModbusTcpClient> Body;
            /// <summary>本用例连接的从站实例端口（三阶段编排：各劣化实例独立端口）。</summary>
            public readonly int Port;
            public CaseDef(string name, Action<ModbusTcpClient> body, int port)
            {
                Name = name; Body = body; Port = port;
            }
        }

        /// <summary>「正常」阶段（15020）全部契约用例——向后兼容入口（原 RunAll 行为不变）。</summary>
        public static List<ContractCaseResult> RunAll()
        {
            return RunPhase("normal");
        }

        /// <summary>
        /// 按阶段执行契约用例（run_contract.ps1 三阶段编排 + 门禁 sweep 阶段的 C# 侧入口）：
        ///   "normal"   —— 15020 正常从站，15 条基础契约（原 RunAll 全集）；
        ///   "fragment" —— 15021(--fragment split3) + 15022(--fragment byte1)，2 条分片重组契约；
        ///   "sticky"   —— 15023(--sticky-stale 1)，1 条粘包→毒化→复活闭环契约（P1-3 端到端）；
        ///   "sweep"    —— 15024(--exception-sweep)，1 条异常码扫掠契约（8 请求逐码断言
        ///                 ModbusSlaveException 名称精确匹配，2026-10-21 门禁轮新增）；
        ///   "all"      —— 以上全部（需五个实例同时在场）。
        /// 劣化/扫掠从站由 run_contract.ps1（三阶段）或 scripts/gate_protocol.ps1（sweep 阶段）
        /// 以 modbus_tcp_slave.py 的注入参数按端口拉起。
        /// </summary>
        public static List<ContractCaseResult> RunPhase(string phase)
        {
            List<CaseDef> defs = BuildDefs((phase ?? "normal").Trim().ToLowerInvariant());
            List<ContractCaseResult> results = new List<ContractCaseResult>();
            foreach (CaseDef def in defs)
            {
                ModbusTcpClient client = OpenClient(def.Port);
                try
                {
                    def.Body(client);
                    results.Add(new ContractCaseResult(def.Name, true, ""));
                }
                catch (ContractFailureException ex)
                {
                    results.Add(new ContractCaseResult(def.Name, false, ex.Message));
                }
                catch (Exception ex)
                {
                    results.Add(new ContractCaseResult(def.Name, false,
                        ex.GetType().Name + ": " + ex.Message));
                }
                finally
                {
                    client.Close();     // Close() 幂等，用例内部自行断开过也没关系
                }
                ContractCaseResult r = results[results.Count - 1];
                Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "[{0}] {1}{2}",
                    r.Passed ? "PASS" : "FAIL", r.Name,
                    r.Passed ? "" : "  -- " + r.Detail));
            }
            return results;
        }

        /// <summary>按阶段装配用例表（名称 / 端口 / 用例体）。未知阶段显式报错（防编排脚本拼错参数被静默当 0 条通过）。</summary>
        private static List<CaseDef> BuildDefs(string phase)
        {
            bool wantNormal = (phase == "normal" || phase == "all");
            bool wantFragment = (phase == "fragment" || phase == "all");
            bool wantSticky = (phase == "sticky" || phase == "all");
            bool wantSweep = (phase == "sweep" || phase == "all");
            if (!wantNormal && !wantFragment && !wantSticky && !wantSweep)
                throw new ArgumentException("阶段必须是 normal / fragment / sticky / sweep / all 之一，收到 '" + phase + "'", "phase");
            List<CaseDef> defs = new List<CaseDef>();
            if (wantNormal)
            {
                defs.Add(new CaseDef("FC3_ReadSeededRegisters", CaseFc3ReadSeeds, SlavePort));
                defs.Add(new CaseDef("FC6_WriteSingleRegister_ReadBack", CaseFc6WriteReadBack, SlavePort));
                defs.Add(new CaseDef("FC16_WriteMultipleRegisters_ReadEachBack", CaseFc16BatchWriteRead, SlavePort));
                defs.Add(new CaseDef("FC5_WriteSingleCoil_ReadBack", CaseFc5CoilWriteRead, SlavePort));
                defs.Add(new CaseDef("FC15_WriteMultipleCoils_ReadBack", CaseFc15CoilsWriteRead, SlavePort));
                defs.Add(new CaseDef("FC3_ZeroQuantity_Exception03", CaseFc3ZeroQty, SlavePort));
                defs.Add(new CaseDef("FC3_AddressOutOfBounds_Exception02", CaseFc3OutOfRange, SlavePort));
                defs.Add(new CaseDef("UnsupportedFC07_Exception01", CaseUnsupportedFc, SlavePort));
                defs.Add(new CaseDef("TransactionIdEcho", CaseTransactionIdEcho, SlavePort));
                defs.Add(new CaseDef("Stress50_ReadWrite_NoError", CaseStress50, SlavePort));
                defs.Add(new CaseDef("ReconnectAfterClose_StillUsable", CaseReconnect, SlavePort));
                defs.Add(new CaseDef("FC1_LargeQuantity1969_Roundtrip", CaseFc1Quantity1969Roundtrip, SlavePort));
                defs.Add(new CaseDef("FC1_MaxQuantity2000_Roundtrip", CaseFc1Quantity2000Roundtrip, SlavePort));
                defs.Add(new CaseDef("ShortRead_ResponseLessThanQuantity_ThrowsIo", CaseShortReadThrows, SlavePort));
                defs.Add(new CaseDef("BadFrame_PoisonsConnection_ReconnectRecovers", CaseBadFramePoisons, SlavePort));
            }
            if (wantFragment)
            {
                defs.Add(new CaseDef("FragmentSplit3_FC3SeedRead_Fc6WriteReadBack", CaseFragmentSplit3, FragmentSplit3Port));
                defs.Add(new CaseDef("FragmentByte1_FC16BatchWrite_Fc3ReadBack", CaseFragmentByte1, FragmentByte1Port));
            }
            if (wantSticky)
            {
                defs.Add(new CaseDef("StickyStaleFrame_PoisonsConnection_ReconnectRecovers", CaseStickyStale, StickyStalePort));
            }
            if (wantSweep)
            {
                defs.Add(new CaseDef("ExceptionSweep_EightRequests_ExceptionNamesExactMatch", CaseExceptionSweep, ExceptionSweepPort));
            }
            return defs;
        }

        // ------------------------------------------------------------------ 用例

        /// <summary>契约 1：FC3 读种子寄存器，0=1234、1=5678 必须原样读出。</summary>
        private static void CaseFc3ReadSeeds(ModbusTcpClient client)
        {
            ushort[] regs = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(regs != null && regs.Length == 2, "FC3 返回 {0} 个寄存器，期望 2",
                regs == null ? -1 : regs.Length);
            Check(regs[0] == 1234 && regs[1] == 5678,
                "种子寄存器不符：期望 [1234, 5678]，实际 [{0}, {1}]", regs[0], regs[1]);
        }

        /// <summary>契约 2a：FC6 写单寄存器后 FC3 回读一致（连写两个值，排除初值巧合）。</summary>
        private static void CaseFc6WriteReadBack(ModbusTcpClient client)
        {
            WriteThenVerifyRegister(client, AddrFc6, 0xABCD);
            WriteThenVerifyRegister(client, AddrFc6, 0x0102);
        }

        /// <summary>契约 2b：FC16 批量写 5 个寄存器，块读 + 逐个回读都必须一致。</summary>
        private static void CaseFc16BatchWriteRead(ModbusTcpClient client)
        {
            ushort[] values = new ushort[] { 1, 0xFFFF, 0x1234, 0x8000, 4711 };
            client.WriteMultipleRegisters(UnitId, AddrFc16, values);    // 内部已校验从机回显

            ushort[] block = client.ReadHoldingRegisters(UnitId, AddrFc16, (ushort)values.Length);
            Check(block != null && block.Length == values.Length,
                "FC3 块读 {0} 个，期望 {1}", block == null ? -1 : block.Length, values.Length);
            for (int i = 0; i < values.Length; i++)
                Check(block[i] == values[i], "FC16 块读第 {0} 个：期望 {1}，实际 {2}",
                    i, values[i], block[i]);

            for (int i = 0; i < values.Length; i++)
            {
                ushort[] single = client.ReadHoldingRegisters(UnitId, (ushort)(AddrFc16 + i), 1);
                Check(single != null && single.Length == 1 && single[0] == values[i],
                    "FC16 逐个回读第 {0} 个：期望 {1}，实际 {2}",
                    i, values[i], single != null && single.Length == 1
                        ? single[0].ToString(CultureInfo.InvariantCulture) : "<无数据>");
            }
        }

        /// <summary>契约 2c：FC5 写单线圈 ON/OFF 各一轮，FC1 回读一致。</summary>
        private static void CaseFc5CoilWriteRead(ModbusTcpClient client)
        {
            client.WriteSingleCoil(UnitId, AddrFc5, true);
            Check(ReadSingleCoil(client, AddrFc5), "FC5 写 ON 后 FC1 回读非 ON");
            client.WriteSingleCoil(UnitId, AddrFc5, false);
            Check(!ReadSingleCoil(client, AddrFc5), "FC5 写 OFF 后 FC1 回读非 OFF");
        }

        /// <summary>契约 2d：FC15 批量写 10 个线圈（跨字节边界）后 FC1 回读一致；
        /// 再写反相图样复验，证明状态真的被写改。</summary>
        private static void CaseFc15CoilsWriteRead(ModbusTcpClient client)
        {
            bool[] pattern = new bool[] { true, false, true, true, false, false, true, false, true, true };
            VerifyCoilPattern(client, AddrFc15, pattern);
            bool[] inverted = new bool[pattern.Length];
            for (int i = 0; i < pattern.Length; i++) inverted[i] = !pattern[i];
            VerifyCoilPattern(client, AddrFc15, inverted);
        }

        /// <summary>契约 3a：FC3 数量 0 → 客户端应本地拦截；绕过拦截上线后从站必须回异常码 03。</summary>
        private static void CaseFc3ZeroQty(ModbusTcpClient client)
        {
            // 客户端契约：类型化 API 对数量 0 在本地前置校验（不上线）
            bool guarded = false;
            try { client.ReadHoldingRegisters(UnitId, 0, 0); }
            catch (ArgumentOutOfRangeException) { guarded = true; }
            Check(guarded, "客户端未前置拦截 FC3 数量 0（应抛 ArgumentOutOfRangeException）");

            // 从站契约：绕过本地校验直接上线，收 (FC3|0x80) + 03
            byte[] request = new byte[] { ModbusFunctionCode.ReadHoldingRegisters, 0x00, 0x00, 0x00, 0x00 };
            byte[] response = client.TransactRaw(UnitId, request);
            Check(response != null && response.Length == 2 &&
                response[0] == (byte)(ModbusFunctionCode.ReadHoldingRegisters | ModbusConst.ExceptionFlag),
                "从站响应非异常帧：长度 {0}", response == null ? -1 : response.Length);
            Check(response[1] == 0x03, "异常码 0x{0:X2}，期望 0x03 (ILLEGAL DATA VALUE)", response[1]);
        }

        /// <summary>契约 3b：FC3 地址越界（从站每区 0..9999）→ 原始帧收 02；
        /// 类型化 API 越界读必须映射为 ModbusSlaveException(02)。</summary>
        private static void CaseFc3OutOfRange(ModbusTcpClient client)
        {
            byte[] request = new byte[] { ModbusFunctionCode.ReadHoldingRegisters, 0xFF, 0xFF, 0x00, 0x01 };
            byte[] response = client.TransactRaw(UnitId, request);
            Check(response != null && response.Length == 2 &&
                response[0] == (byte)(ModbusFunctionCode.ReadHoldingRegisters | ModbusConst.ExceptionFlag),
                "从站响应非异常帧：长度 {0}", response == null ? -1 : response.Length);
            Check(response[1] == 0x02, "异常码 0x{0:X2}，期望 0x02 (ILLEGAL DATA ADDRESS)", response[1]);

            bool mapped = false;
            byte code = 0;
            try { client.ReadHoldingRegisters(UnitId, 9999, 2); }   // 9999+2 越出 0..9999
            catch (ModbusSlaveException ex) { mapped = true; code = ex.ExceptionCode; }
            Check(mapped, "类型化越界读未抛 ModbusSlaveException");
            Check(code == 0x02, "类型化路径异常码 0x{0:X2}，期望 0x02", code);
        }

        /// <summary>契约 3c：从站不支持的功能码（0x07）→ 原始帧收 01；
        /// 客户端把异常帧正确映射为 ModbusSlaveException(01)。</summary>
        private static void CaseUnsupportedFc(ModbusTcpClient client)
        {
            byte[] request = new byte[] { 0x07 };
            byte[] response = client.TransactRaw(UnitId, request);
            Check(response != null && response.Length == 2 &&
                response[0] == (byte)(0x07 | ModbusConst.ExceptionFlag),
                "从站响应非异常帧：长度 {0}", response == null ? -1 : response.Length);
            Check(response[1] == 0x01, "异常码 0x{0:X2}，期望 0x01 (ILLEGAL FUNCTION)", response[1]);

            bool mapped = false;
            byte code = 0;
            try { ModbusPdu.EnsureNotException(response); }
            catch (ModbusSlaveException ex) { mapped = true; code = ex.ExceptionCode; }
            Check(mapped && code == 0x01, "客户端未把异常帧映射为 ModbusSlaveException(01)");
        }

        /// <summary>契约 4：事务标识符回显。线缆层用独特 tid=0xBEEF 的自造帧验证从站
        /// 原样回显 tid/协议标识/单元标识；客户端层验证 tid 严格自增且事务成功
        /// （ExecuteTransaction 对 tid 不匹配直接抛 InvalidDataException，成功即回显成立）。</summary>
        private static void CaseTransactionIdEcho(ModbusTcpClient client)
        {
            byte[] frame = new byte[]
            {
                0xBE, 0xEF,                                 // 事务标识 0xBEEF
                0x00, 0x00,                                 // 协议标识 = 0
                0x00, 0x06,                                 // 长度 = 单元标识 + 5 字节 PDU
                UnitId,
                ModbusFunctionCode.ReadHoldingRegisters, 0x00, 0x00, 0x00, 0x02
            };
            using (TcpClientProbe probe = new TcpClientProbe())
            {
                probe.Connect(SlaveHost, SlavePort);
                probe.Stream.Write(frame, 0, frame.Length);
                byte[] header = probe.ReadExact(ModbusTcpFrame.HeaderSize);
                ushort tid, pid, len;
                byte unit;
                Check(ModbusTcpFrame.TryParseHeader(header, out tid, out pid, out len, out unit),
                    "探针帧 MBAP 头非法（协议标识非 0 或长度越界）");
                Check(tid == 0xBEEF, "事务标识未回显：发 0xBEEF 收 0x{0:X4}", tid);
                Check(pid == ModbusConst.ProtocolId, "协议标识非 0：0x{0:X4}", pid);
                Check(unit == UnitId, "单元标识未回显：发 {0} 收 {1}", UnitId, unit);
                byte[] body = probe.ReadExact(len - 1);
                Check(body.Length == 6 && body[0] == ModbusFunctionCode.ReadHoldingRegisters &&
                    body[1] == 4 && body[2] == 0x04 && body[3] == 0xD2 &&
                    body[4] == 0x16 && body[5] == 0x2E,
                    "探针响应 PDU 不符：期望 FC3 byteCount=4 值=[1234,5678]");
            }

            for (int i = 0; i < 3; i++)
            {
                ushort before = client.LastTransactionId;
                client.ReadHoldingRegisters(UnitId, 0, 1);
                ushort after = client.LastTransactionId;
                Check(after == (ushort)(before + 1), "事务标识应严格自增：{0} -> {1}", before, after);
            }
        }

        /// <summary>契约 5：连续 50 轮 FC6 写 + FC3 读全部一致，期间不得有任何 IO/协议错误。</summary>
        private static void CaseStress50(ModbusTcpClient client)
        {
            for (int i = 1; i <= 50; i++)
            {
                ushort value = (ushort)(0x1000 + i);
                client.WriteSingleRegister(UnitId, AddrStress, value);
                ushort[] back = client.ReadHoldingRegisters(UnitId, AddrStress, 1);
                Check(back != null && back.Length == 1 && back[0] == value,
                    "第 {0} 轮 FC6+FC3 不一致：写 {1}，读 {2}", i, value,
                    back != null && back.Length == 1
                        ? back[0].ToString(CultureInfo.InvariantCulture) : "<无数据>");
            }
        }

        /// <summary>契约 6：Close 断开后重连仍可读写（读回种子值 + FC6 写读一致）。</summary>
        private static void CaseReconnect(ModbusTcpClient client)
        {
            ushort[] before = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(before != null && before.Length == 2, "断开前 FC3 读取失败");
            client.Close();
            Check(!client.IsConnected, "Close() 后 IsConnected 仍为 true");
            client.Connect();
            Check(client.IsConnected, "重连后 IsConnected 为 false");

            ushort[] after = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(after != null && after.Length == 2 && after[0] == before[0] && after[1] == before[1],
                "重连后读数不一致：[{0}, {1}] vs [{2}, {3}]",
                before[0], before[1], after[0], after[1]);
            WriteThenVerifyRegister(client, AddrFc6, 0x5A5A);   // 重连后写路径也要能用
        }

        /// <summary>契约 7（P1-1）：FC1 数量 1969 往返——响应 247 字节 > 旧错误上限 0xF5(245)，
        /// 旧实现会误拒本用例；并断言线缆层 Byte Count 恰为 ceil(1969/8)=247。</summary>
        private static void CaseFc1Quantity1969Roundtrip(ModbusTcpClient client)
        {
            bool[] written = WriteCoilPattern(client, AddrBulkCoils, 1968);

            bool[] bits = client.ReadCoils(UnitId, AddrBulkCoils, 1969);
            Check(bits != null && bits.Length == 1969, "FC1 数量 1969 应返回 1969 位，实际 {0}",
                bits == null ? -1 : bits.Length);
            for (int i = 0; i < written.Length; i++)
                Check(bits[i] == written[i], "FC1 大批量回读第 {0} 位：期望 {1}，实际 {2}", i, written[i], bits[i]);
            Check(!bits[1968], "第 1969 位（未写区）应为 false");

            // 线缆层断言：Byte Count 字段 = 247（> 0xF5=245，即 P1-1 修复的直接回归点）
            byte[] raw = client.TransactRaw(UnitId,
                ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadCoils, AddrBulkCoils, 1969));
            Check(raw != null && raw.Length == 249 && raw[0] == ModbusFunctionCode.ReadCoils && raw[1] == 247,
                "FC1 1969 位响应线缆层应为 [FC=01, byteCount=247, 249 字节]，实际长度 {0}",
                raw == null ? -1 : raw.Length);
        }

        /// <summary>契约 8（P1-1）：FC1 数量 2000 往返——响应 Byte Count 恰为上限 250（=ceil(2000/8)）。</summary>
        private static void CaseFc1Quantity2000Roundtrip(ModbusTcpClient client)
        {
            bool[] written = WriteCoilPattern(client, AddrBulkCoils, 1968);

            bool[] bits = client.ReadCoils(UnitId, AddrBulkCoils, 2000);
            Check(bits != null && bits.Length == 2000, "FC1 数量 2000 应返回 2000 位，实际 {0}",
                bits == null ? -1 : bits.Length);
            for (int i = 0; i < written.Length; i++)
                Check(bits[i] == written[i], "FC1 满量回读第 {0} 位：期望 {1}，实际 {2}", i, written[i], bits[i]);
            for (int i = 1968; i < 2000; i++)
                Check(!bits[i], "FC1 满量回读填充区第 {0} 位应为 false", i);
        }

        /// <summary>契约 9（P1-2）：劣化从站短读——本地桩对 FC3 数量 5 只回 4 个寄存器（帧自洽但数据不足），
        /// 类型化读必须抛 IOException 且信息同时含请求量与实收量。</summary>
        private static void CaseShortReadThrows(ModbusTcpClient client)
        {
            using (FaultSlaveListener slave = new FaultSlaveListener("short-read"))
            {
                ModbusTcpClient degraded = new ModbusTcpClient(SlaveHost, slave.Port, 3000, 2000, 2000);
                try
                {
                    degraded.Connect();
                    Exception thrown = null;
                    try { degraded.ReadHoldingRegisters(UnitId, 0, 5); }
                    catch (Exception ex) { thrown = ex; }
                    Check(thrown is System.IO.IOException, "短读必须抛 IOException，实际 {0}",
                        thrown == null ? "<未抛>" : thrown.GetType().Name);
                    Check(thrown.Message.Contains("请求 5") && thrown.Message.Contains("实收 4"),
                        "短读异常信息须含请求量与实收量：{0}", thrown.Message);
                }
                finally
                {
                    degraded.Close();
                }
            }
        }

        /// <summary>契约 10（P1-3）：人为坏帧（劣化桩回错事务标识）→ 首调抛 InvalidDataException 并毒化断开；
        /// 后续调用必须得 InvalidOperationException("连接已因协议/网络错误失效，请重连")，
        /// 而不是残余字节流导致的诡异 TID 错；Connect() 以全新连接复活实例。</summary>
        private static void CaseBadFramePoisons(ModbusTcpClient client)
        {
            using (FaultSlaveListener slave = new FaultSlaveListener("wrong-tid"))
            {
                ModbusTcpClient poisoned = new ModbusTcpClient(SlaveHost, slave.Port, 3000, 2000, 2000);
                try
                {
                    poisoned.Connect();
                    Exception first = null;
                    try { poisoned.ReadHoldingRegisters(UnitId, 0, 1); }
                    catch (Exception ex) { first = ex; }
                    Check(first is System.IO.InvalidDataException, "坏帧首调应抛 InvalidDataException，实际 {0}",
                        first == null ? "<未抛>" : first.GetType().Name);
                    Check(!poisoned.IsConnected, "坏帧后连接应已毒化断开（IsConnected=false）");

                    Exception second = null;
                    try { poisoned.ReadHoldingRegisters(UnitId, 0, 1); }
                    catch (Exception ex) { second = ex; }
                    Check(second is InvalidOperationException, "毒化后调用应抛 InvalidOperationException，实际 {0}",
                        second == null ? "<未抛>" : second.GetType().Name);
                    Check(second != null && second.Message.Contains("失效") && second.Message.Contains("重连"),
                        "毒化异常信息应注明失效与重连：{0}",
                        second == null ? "<无>" : second.Message);

                    // 「出错即重连」：全新连接复活后读写恢复正常
                    poisoned.Connect();
                    Check(poisoned.IsConnected, "重连后 IsConnected 应为 true");
                    ushort[] regs = poisoned.ReadHoldingRegisters(UnitId, 0, 1);
                    Check(regs != null && regs.Length == 1 && regs[0] == 0xABCD,
                        "重连后读数应为桩回值 0xABCD，实际 {0}",
                        regs != null && regs.Length == 1 ? regs[0].ToString("X4") : "<无数据>");
                }
                finally
                {
                    poisoned.Close();
                }
            }
        }

        /// <summary>契约 11（分片 split3，P1 网络劣化回归）：对 --fragment split3 实例（15021，
        /// 每个响应拆 3 段 = 3B/5B/其余先后到达，段间 20-50ms）做 FC3 种子读 + FC6 写读回，
        /// 多轮写值全对——验证主站接收侧按 MBAP 长度循环补齐重组（ReadExact），半帧不当全帧用。</summary>
        private static void CaseFragmentSplit3(ModbusTcpClient client)
        {
            ushort[] seeds = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(seeds != null && seeds.Length == 2 && seeds[0] == 1234 && seeds[1] == 5678,
                "分片实例 FC3 种子读不符：期望 [1234, 5678]，实际 [{0}, {1}]",
                seeds != null && seeds.Length > 0 ? seeds[0].ToString(CultureInfo.InvariantCulture) : "?",
                seeds != null && seeds.Length > 1 ? seeds[1].ToString(CultureInfo.InvariantCulture) : "?");
            // 三轮写读回：每一轮响应都会被拆成 3 段，任何"一次 Read 当整帧"的侥幸都会翻车
            WriteThenVerifyRegister(client, AddrFc6, 0xC3D3);
            WriteThenVerifyRegister(client, AddrFc6, 0x0FF0);
            WriteThenVerifyRegister(client, AddrFc6, 0x7E7E);
        }

        /// <summary>契约 12（极端分片 byte1，P1 网络劣化回归）：对 --fragment byte1 实例（15022，
        /// 响应逐字节滴流、字节间 1-3ms）做 FC16 批量写 + FC3 块读/逐个回读全对——
        /// 验证 ReadExact 循环对最恶劣的分段（每 TCP 段仅 1 字节）仍真重组、零错位。</summary>
        private static void CaseFragmentByte1(ModbusTcpClient client)
        {
            ushort[] values = new ushort[] { 0x0F0F, 0x1E1E, 0x2D2D, 0x3C3C, 0x4B4B, 0x5A5A };
            client.WriteMultipleRegisters(UnitId, AddrFc16, values);    // 内部已校验从机回显

            ushort[] block = client.ReadHoldingRegisters(UnitId, AddrFc16, (ushort)values.Length);
            Check(block != null && block.Length == values.Length,
                "byte1 实例 FC3 块读 {0} 个，期望 {1}",
                block == null ? -1 : block.Length, values.Length);
            for (int i = 0; i < values.Length; i++)
                Check(block[i] == values[i], "byte1 FC16 块读第 {0} 个：期望 {1}，实际 {2}",
                    i, values[i], block[i]);

            for (int i = 0; i < values.Length; i++)
            {
                ushort[] single = client.ReadHoldingRegisters(UnitId, (ushort)(AddrFc16 + i), 1);
                Check(single != null && single.Length == 1 && single[0] == values[i],
                    "byte1 逐个回读第 {0} 个：期望 {1}，实际 {2}",
                    i, values[i], single != null && single.Length == 1
                        ? single[0].ToString(CultureInfo.InvariantCulture) : "<无数据>");
            }
        }

        /// <summary>契约 13（粘包/残帧→毒化闭环，P1-3 端到端）：对 --sticky-stale 1 实例（15023，
        /// 每个响应都与一帧"伪造旧 TID 的完整陈旧帧"背靠背发出）。推演确定性结局：
        /// ① 每条新连接第 1 个事务正常（主站按 MBAP 长度恰好读完自己的帧，陈旧帧残留管道）；
        /// ② 第 2 个事务必先撞陈旧帧 → 事务标识不匹配 InvalidDataException → P1-3 毒化断开
        ///    （绝不能把旧帧数据静默当真值用）；
        /// ③ 毒化后的调用必须得 InvalidOperationException("连接已因协议/网络错误失效，请重连")
        ///    ——确定性的可操作错误，而非残余字节流造成的诡异 TID/错位错（P1-3 的核心价值）；
        /// ④ Connect() 换全新 socket（干净管道）复活：读路径恢复；
        /// ⑤⑥ 再各以"新连接第 1 事务"验证写路径与落盘回读（粘包实例语义下每连接恰好一次
        /// 干净事务，故换连接验证，与现场"出错即重连"的操作一致）。</summary>
        private static void CaseStickyStale(ModbusTcpClient client)
        {
            // ① 第 1 个事务正常（响应 + 陈旧帧背靠背到达，客户端只读自己的帧）
            ushort[] seeds = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(seeds != null && seeds.Length == 2 && seeds[0] == 1234 && seeds[1] == 5678,
                "粘包实例第 1 事务种子读不符：期望 [1234, 5678]，实际 [{0}, {1}]",
                seeds != null && seeds.Length > 0 ? seeds[0].ToString(CultureInfo.InvariantCulture) : "?",
                seeds != null && seeds.Length > 1 ? seeds[1].ToString(CultureInfo.InvariantCulture) : "?");

            // ② 第 2 个事务必撞管道里的陈旧帧（旧 TID）→ 传输级校验失败 → 毒化断开
            Exception first = null;
            try { client.ReadHoldingRegisters(UnitId, 0, 1); }
            catch (Exception ex) { first = ex; }
            Check(first is System.IO.InvalidDataException,
                "粘包后第 2 事务应抛 InvalidDataException（TID 校验拦截旧帧），实际 {0}",
                first == null ? "<未抛>" : first.GetType().Name + ": " + (first == null ? "" : first.Message));
            Check(!client.IsConnected, "传输级错误后连接应已毒化断开（IsConnected=false）");

            // ③ P1-3 核心断言：毒化后的调用 = 确定性的「失效，请重连」，而非诡异 TID/错位错
            Exception second = null;
            try { client.ReadHoldingRegisters(UnitId, 0, 1); }
            catch (Exception ex) { second = ex; }
            Check(second is InvalidOperationException, "毒化后调用应抛 InvalidOperationException，实际 {0}",
                second == null ? "<未抛>" : second.GetType().Name);
            Check(second != null && second.Message.Contains("失效") && second.Message.Contains("重连"),
                "毒化异常信息应注明失效与重连：{0}", second == null ? "<无>" : second.Message);

            // ④ Connect() 复活（全新 socket = 干净管道）：读路径恢复正常
            client.Connect();
            ushort[] revived = client.ReadHoldingRegisters(UnitId, 0, 2);
            Check(revived != null && revived.Length == 2 && revived[0] == 1234 && revived[1] == 5678,
                "复活后 FC3 种子读不符：期望 [1234, 5678]");

            // ⑤ 该连接第 2 事务必再撞陈旧帧（粘包实例语义使然）——显式 Close+Connect 换新管道，
            //   以"新连接第 1 事务"验证写路径（FC6 从机回显校验在事务内完成）
            client.Close();
            client.Connect();
            client.WriteSingleRegister(UnitId, AddrFc6, 0x0B0C);

            // ⑥ 再换新管道回读 0x0B0C：证明写真的落到了从站内存
            client.Close();
            client.Connect();
            ushort[] back = client.ReadHoldingRegisters(UnitId, AddrFc6, 1);
            Check(back != null && back.Length == 1 && back[0] == 0x0B0C,
                "粘包复活后 FC6 写读回不符：期望 0x0B0C，实际 {0}",
                back != null && back.Length == 1 ? back[0].ToString("X4") : "<无数据>");
        }

        // ------------------------------------------------------------------ 工具

        /// <summary>异常码扫掠序列（--exception-sweep 从站按此序循环回异常帧；0x04 不入序列，
        /// 其名称由 GetExceptionName 单独钉值——见 CaseExceptionSweep 末尾）。</summary>
        private static readonly byte[] SweepCodes = new byte[]
        {
            0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0A, 0x0B
        };

        /// <summary>契约 14（异常码扫掠，2026-10-21 门禁轮）：对 --exception-sweep 实例（15024，
        /// 每个请求按序回异常码 01,02,03,05,06,08,0A,0B 循环）连发 8 个请求，逐请求断言：
        /// ① 类型化读抛 ModbusSlaveException（异常帧→类型化异常的翻译链真实生效）；
        /// ② ExceptionCode 与扫掠序逐一精确相等（钉住顺序，防从站/主站错位）；
        /// ③ 异常消息含 V1.1b3 §7 表的**精确名称**（GetExceptionName 全名逐码核对——
        ///    特别是 0x06=SERVER DEVICE BUSY，原 "SLAVE DEVICE BUSY" 同义异名已弃用，
        ///    名称表若回退改名此断言立即翻红）。
        /// 另以名称表断言单独钉住 0x04=SERVER DEVICE FAILURE（0x04 不入扫掠序列，
        /// 但同一张 §7 表的改名必须一起钉住）与 0x07/0x09=UNKNOWN（V1.1b3 表中无定义）。</summary>
        private static void CaseExceptionSweep(ModbusTcpClient client)
        {
            string[] expectedNames = new string[]
            {
                "ILLEGAL FUNCTION",                                  // 0x01
                "ILLEGAL DATA ADDRESS",                              // 0x02
                "ILLEGAL DATA VALUE",                                // 0x03
                "ACKNOWLEDGE",                                       // 0x05
                "SERVER DEVICE BUSY",                                // 0x06（V1.1b3 §7 原文，弃用 SLAVE DEVICE BUSY）
                "MEMORY PARITY ERROR",                               // 0x08
                "GATEWAY PATH UNAVAILABLE",                          // 0x0A
                "GATEWAY TARGET DEVICE FAILED TO RESPOND"            // 0x0B
            };
            for (int i = 0; i < SweepCodes.Length; i++)
            {
                ModbusSlaveException thrown = null;
                try { client.ReadHoldingRegisters(UnitId, 0, 1); }
                catch (ModbusSlaveException ex) { thrown = ex; }
                Check(thrown != null,
                    "扫掠第 {0} 请求（期望异常码 0x{1:X2}）未抛 ModbusSlaveException",
                    i + 1, SweepCodes[i]);
                Check(thrown.ExceptionCode == SweepCodes[i],
                    "扫掠第 {0} 请求异常码 0x{1:X2}，期望 0x{2:X2}（顺序错位）",
                    i + 1, thrown.ExceptionCode, SweepCodes[i]);
                Check(thrown.Message.IndexOf(expectedNames[i], StringComparison.Ordinal) >= 0,
                    "扫掠异常码 0x{0:X2} 的消息缺精确名称「{1}」：{2}",
                    SweepCodes[i], expectedNames[i], thrown.Message);
            }

            // 0x04 不在扫掠序列（从站端按任务口径排除），名称表单独钉值——改名必须翻红
            string name04 = ModbusSlaveException.GetExceptionName(0x04);
            Check(name04 == "SERVER DEVICE FAILURE",
                "GetExceptionName(0x04) 应为 SERVER DEVICE FAILURE（V1.1b3 §7 表原文，弃用 SLAVE DEVICE FAILURE），实际 {0}",
                name04);
            Check(name04.IndexOf("SLAVE DEVICE", StringComparison.Ordinal) < 0,
                "0x04 名称不得回退为弃用的 SLAVE DEVICE * 措辞，实际 {0}", name04);
            Check(ModbusSlaveException.GetExceptionName(0x06) == "SERVER DEVICE BUSY",
                "GetExceptionName(0x06) 应为 SERVER DEVICE BUSY（钉住改名）");
            Check(ModbusSlaveException.GetExceptionName(0x07) == "UNKNOWN EXCEPTION CODE",
                "0x07 在 V1.1b3 表中无定义，应回退 UNKNOWN EXCEPTION CODE");
            Check(ModbusSlaveException.GetExceptionName(0x09) == "UNKNOWN EXCEPTION CODE",
                "0x09 在 V1.1b3 表中无定义，应回退 UNKNOWN EXCEPTION CODE");
        }

        private static ModbusTcpClient OpenClient(int port)
        {
            ModbusTcpClient client = new ModbusTcpClient(SlaveHost, port, 3000, 2000, 2000);
            client.Connect();
            return client;
        }

        private static void Check(bool condition, string message)
        {
            if (!condition) throw new ContractFailureException(message);
        }

        private static void Check(bool condition, string format, params object[] args)
        {
            if (!condition)
                throw new ContractFailureException(string.Format(CultureInfo.InvariantCulture, format, args));
        }

        private static void WriteThenVerifyRegister(ModbusTcpClient client, ushort address, ushort value)
        {
            client.WriteSingleRegister(UnitId, address, value);         // 内部已校验从机回显
            ushort[] back = client.ReadHoldingRegisters(UnitId, address, 1);
            Check(back != null && back.Length == 1 && back[0] == value,
                "FC6 写 {0} 后 FC3 回读 {1}", value,
                back != null && back.Length == 1
                    ? back[0].ToString(CultureInfo.InvariantCulture) : "<无数据>");
        }

        private static bool ReadSingleCoil(ModbusTcpClient client, ushort address)
        {
            bool[] bits = client.ReadCoils(UnitId, address, 1);
            Check(bits != null && bits.Length == 1, "FC1 返回 {0} 个线圈，期望 1",
                bits == null ? -1 : bits.Length);
            return bits[0];
        }

        private static void VerifyCoilPattern(ModbusTcpClient client, ushort address, bool[] pattern)
        {
            client.WriteMultipleCoils(UnitId, address, pattern);        // 内部已校验从机回显
            bool[] back = client.ReadCoils(UnitId, address, (ushort)pattern.Length);
            Check(back != null && back.Length == pattern.Length, "FC1 返回 {0} 个线圈，期望 {1}",
                back == null ? -1 : back.Length, pattern.Length);
            for (int i = 0; i < pattern.Length; i++)
                Check(back[i] == pattern[i], "FC15 线圈 {0}：期望 {1}，实际 {2}",
                    address + i, pattern[i], back[i]);
        }

        /// <summary>写入交替位型（i%2==0 → ON）并返回该位型，供大批量用例比对（FC15 上限 1968）。</summary>
        private static bool[] WriteCoilPattern(ModbusTcpClient client, ushort address, int count)
        {
            bool[] pattern = new bool[count];
            for (int i = 0; i < count; i++) pattern[i] = (i % 2 == 0);
            client.WriteMultipleCoils(UnitId, address, pattern);        // 内部已校验从机回显
            return pattern;
        }

        /// <summary>
        /// 本地劣化从站桩（P1-2/P1-3 契约用）：独立 TcpListener，只服务本用例的客户端。
        ///   short-read 模式：第 1 条连接对 FC3 数量 N 只回 N-1 个寄存器（MBAP 长度自洽、数据不足）；
        ///   wrong-tid 模式：第 1 条连接回错事务标识（tid+1），其后连接正常回显。
        /// 端口由系统分配（绑定 :0），Dispose 停止监听；线程全部后台化，不阻塞用例收尾。
        /// </summary>
        private sealed class FaultSlaveListener : IDisposable
        {
            private readonly TcpListener _listener;
            private readonly string _mode;
            private int _connectionCount;

            public FaultSlaveListener(string mode)
            {
                _mode = mode;
                _listener = new TcpListener(IPAddress.Loopback, 0);
                _listener.Start();
                Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
                Thread acceptor = new Thread(AcceptLoop);
                acceptor.IsBackground = true;
                acceptor.Start();
            }

            public int Port { get; private set; }

            private void AcceptLoop()
            {
                try
                {
                    while (true)
                    {
                        TcpClient conn = _listener.AcceptTcpClient();
                        Thread worker = new Thread(delegate() { ServeOne(conn); });
                        worker.IsBackground = true;
                        worker.Start();
                    }
                }
                catch (SocketException) { }         // Stop() 后 Accept 抛错属正常收尾
                catch (ObjectDisposedException) { }
                catch (InvalidOperationException) { }
            }

            private void ServeOne(object state)
            {
                TcpClient conn = (TcpClient)state;
                int index = Interlocked.Increment(ref _connectionCount);
                try
                {
                    using (conn)
                    {
                        NetworkStream stream = conn.GetStream();
                        stream.ReadTimeout = 3000;
                        stream.WriteTimeout = 3000;
                        byte[] head = ReadExact(stream, 7);
                        ushort tid = (ushort)((head[0] << 8) | head[1]);
                        ushort length = (ushort)((head[4] << 8) | head[5]);
                        byte unit = head[6];
                        byte[] request = ReadExact(stream, length - 1);
                        byte fc = request[0];
                        ushort qty = (ushort)((request[3] << 8) | request[4]);

                        ushort tidOut = (_mode == "wrong-tid" && index == 1) ? (ushort)(tid + 1) : tid;
                        byte[] pdu;
                        if (fc == 0x03 || fc == 0x04)
                        {
                            bool degrade = (_mode == "short-read" && index == 1);
                            int regs = degrade ? qty - 1 : qty;     // 劣化：比请求少给一个寄存器
                            pdu = new byte[2 + regs * 2];
                            pdu[0] = fc;
                            pdu[1] = (byte)(regs * 2);
                            for (int i = 0; i < regs; i++) { pdu[2 + i * 2] = 0xAB; pdu[3 + i * 2] = 0xCD; }
                        }
                        else
                        {
                            pdu = new byte[] { (byte)(fc | ModbusConst.ExceptionFlag), 0x01 };
                        }

                        byte[] frame = new byte[7 + pdu.Length];
                        frame[0] = (byte)(tidOut >> 8);
                        frame[1] = (byte)(tidOut & 0xFF);
                        frame[4] = (byte)((pdu.Length + 1) >> 8);
                        frame[5] = (byte)((pdu.Length + 1) & 0xFF);
                        frame[6] = unit;
                        Buffer.BlockCopy(pdu, 0, frame, 7, pdu.Length);
                        stream.Write(frame, 0, frame.Length);
                    }   // using：用完即断，与「每连接一线程」配合
                }
                catch { }   // 劣化桩：任何 IO 异常静默退出（被测行为在客户端侧断言）
            }

            private static byte[] ReadExact(NetworkStream stream, int count)
            {
                byte[] buf = new byte[count];
                int got = 0;
                while (got < count)
                {
                    int n = stream.Read(buf, got, count - got);
                    if (n <= 0) throw new System.IO.IOException("劣化桩：客户端提前断开");
                    got += n;
                }
                return buf;
            }

            public void Dispose()
            {
                try { _listener.Stop(); } catch { }
            }
        }

        /// <summary>独立于被测客户端的裸 TCP 探针（验证从站线缆层回显，不受客户端实现影响）。</summary>
        private sealed class TcpClientProbe : IDisposable
        {
            private System.Net.Sockets.TcpClient _tcp;

            public System.Net.Sockets.NetworkStream Stream { get; private set; }

            public void Connect(string host, int port)
            {
                _tcp = new System.Net.Sockets.TcpClient();
                IAsyncResult ar = _tcp.BeginConnect(host, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(3000, false) || !_tcp.Connected)
                {
                    _tcp.Close();
                    throw new ContractFailureException("探针连接从站失败：" + host + ":" + port);
                }
                Stream = _tcp.GetStream();
                Stream.ReadTimeout = 2000;
                Stream.WriteTimeout = 2000;
            }

            public byte[] ReadExact(int count)
            {
                byte[] buf = new byte[count];
                int got = 0;
                while (got < count)
                {
                    int n = Stream.Read(buf, got, count - got);
                    if (n <= 0) throw new ContractFailureException("探针连接被远端关闭");
                    got += n;
                }
                return buf;
            }

            public void Dispose()
            {
                if (Stream != null) { try { Stream.Close(); } catch { } Stream = null; }
                if (_tcp != null) { try { _tcp.Close(); } catch { } _tcp = null; }
            }
        }
    }
}
