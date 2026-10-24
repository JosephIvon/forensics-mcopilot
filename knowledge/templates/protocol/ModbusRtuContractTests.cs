// ============================================================================
//  ModbusRtuContractTests.cs —— Modbus RTU 行为契约测试集（com0com 虚拟串口对）
//
//  与 TCP 版（ModbusContractTests.cs）同构，但总线换成本机 com0com 虚拟串口对：
//    C# 主站(本 exe) ↔ COM3 ══虚拟对══ COM4 ↔ python 从站 modbus_rtu_slave.py
//  验证的是 RTU 真实链路行为契约：字节流 + CRC16 + 帧间隔 + 广播无响应语义。
//  注意边界：com0com 虚拟对忽略波特率/电气层，9600 仅是形式参数；真机波特率
//  时序仍需现场验证（README 已标注该诚实边界）。
//
//  用例（normal 阶段 10 条 + corrupt 阶段 1 条）：
//    N1 FC3_ReadSeededRegisters        种子读 FC3=[1234,5678]
//    N2 FC6_WriteSingleRegister_ReadBack
//    N3 FC16_WriteMultipleRegisters_ReadBack
//    N4 FC5_WriteSingleCoil_ReadBack
//    N5 FC15_WriteMultipleCoils_ReadBack
//    N6 FC3_ZeroQuantity_ClientReject  数量 0 → 客户端本地拦截（ArgumentException）
//    N7 FC3_AddressOutOfBounds_Exception02  越界 9999+2 → 异常码 02，且总线不毒化
//    N8 Broadcast_WriteSingleRegister_ClosedLoop
//       WriteSingleRegisterNoResponse(0, 800, 777) 无异常快速返回 → FC3 unit1
//       读回 800==777（证明从站收到并执行了广播）
//    N9 BroadcastTurnaroundDelay_Measured  广播发送到返回的实测间隔 ≥ 下限 100ms
//       （客户端实现应等待 turnaround delay=150ms；spec_ref: Serial Line V1.02 §2.4.1）
//    N10 Stress30Transactions_ZeroError  连续 30 次读写事务零错误
//    C1 CorruptNextResponse_Rejected_NextTransactionNormal
//       从站以 --corrupt-next 启动：第一个响应故意坏 CRC → 客户端必须拒收
//       （InvalidDataException/TimeoutException），且下一事务立即恢复正常
//       （劣化仅注入一帧，验证管道不毒化）。
//
//  C# 5 兼容写法（.NET Framework 4 自带 csc.exe 可直接编译），零第三方依赖。
//  ⚠ 编译组合（run_rtu_contract.ps1）：ModbusTcpClient.cs + ModbusRtuClient.cs +
//    本文件 —— Main 在本文件内，勿再混入其他 Main（CS0017）。
// ============================================================================

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Threading;
using Mcopilot.Protocols.Modbus;

namespace Mcopilot.Protocols.Modbus.RtuContractTests
{
    /// <summary>单条 RTU 契约用例的执行结果。</summary>
    public sealed class RtuContractCaseResult
    {
        /// <summary>用例名。</summary>
        public string Name { get; private set; }
        /// <summary>true = PASS。</summary>
        public bool Passed { get; private set; }
        /// <summary>失败原因；通过时为空。</summary>
        public string Detail { get; private set; }

        public RtuContractCaseResult(string name, bool passed, string detail)
        {
            Name = name;
            Passed = passed;
            Detail = detail == null ? "" : detail;
        }
    }

    /// <summary>契约断言失败（行为不符合契约，区别于 IO/协议异常）。</summary>
    public sealed class RtuContractFailureException : Exception
    {
        public RtuContractFailureException(string message) : base(message) { }
    }

    /// <summary>Modbus RTU 行为契约测试集：static 用例集合 + RunPhase(phase) 汇总运行。</summary>
    public static class ModbusRtuContractTests
    {
        // ---- 链路拓扑常量（与 run_rtu_contract.ps1 的从站参数保持一致）------------
        /// <summary>主站占用端（com0com 配对 A 端）。spec_ref: 本仓库 com0com 配对 0。</summary>
        public const string ClientPortName = "COM3";
        /// <summary>python 从站占用端（com0com 配对 B 端）。</summary>
        public const string SlavePortName = "COM4";
        /// <summary>标称波特率（虚拟对忽略，真机仍需现场验证）。</summary>
        public const int BaudRate = 9600;
        /// <summary>从站单播地址（modbus_rtu_slave.py 默认 --unit 1）。</summary>
        public const byte UnitId = 1;
        /// <summary>响应超时（一帧响应的总上限）。</summary>
        public const int TimeoutMs = 1000;

        // 写操作安全区：全部 >=100，避开种子寄存器 0/1（与 TCP 版约定一致）。
        private const ushort AddrFc6 = 100;
        private const ushort AddrFc16 = 200;
        private const ushort AddrFc5 = 300;
        private const ushort AddrFc15 = 400;
        private const ushort AddrBroadcast = 800;
        private const ushort AddrTurnaround = 810;
        private const ushort AddrStress = 900;
        /// <summary>越界地址：从站每区 10000 元素（0..9999），9999+2 正好跨出（口径同 TCP 版）。</summary>
        private const ushort AddrOutOfRange = 9999;

        private sealed class RtuCaseDef
        {
            public readonly string Name;
            public readonly Action<ModbusRtuClient> Body;
            public RtuCaseDef(string name, Action<ModbusRtuClient> body) { Name = name; Body = body; }
        }

        /// <summary>normal 阶段用例清单（顺序执行；写操作只落在安全区，顺序无关）。</summary>
        private static List<RtuCaseDef> NormalCases()
        {
            List<RtuCaseDef> defs = new List<RtuCaseDef>();
            defs.Add(new RtuCaseDef("FC3_ReadSeededRegisters", CaseFc3ReadSeeds));
            defs.Add(new RtuCaseDef("FC6_WriteSingleRegister_ReadBack", CaseFc6WriteReadBack));
            defs.Add(new RtuCaseDef("FC16_WriteMultipleRegisters_ReadBack", CaseFc16WriteReadBack));
            defs.Add(new RtuCaseDef("FC5_WriteSingleCoil_ReadBack", CaseFc5CoilWriteRead));
            defs.Add(new RtuCaseDef("FC15_WriteMultipleCoils_ReadBack", CaseFc15CoilsWriteRead));
            defs.Add(new RtuCaseDef("FC3_ZeroQuantity_ClientReject", CaseFc3ZeroQuantity));
            defs.Add(new RtuCaseDef("FC3_AddressOutOfBounds_Exception02", CaseFc3OutOfRange));
            defs.Add(new RtuCaseDef("Broadcast_WriteSingleRegister_ClosedLoop", CaseBroadcastClosedLoop));
            defs.Add(new RtuCaseDef("BroadcastTurnaroundDelay_Measured", CaseBroadcastTurnaround));
            defs.Add(new RtuCaseDef("Stress30Transactions_ZeroError", CaseStress30));
            return defs;
        }

        /// <summary>按阶段执行用例。phase = normal | corrupt | all。</summary>
        public static List<RtuContractCaseResult> RunPhase(string phase)
        {
            List<RtuCaseDef> defs;
            if (phase == "corrupt")
            {
                defs = new List<RtuCaseDef>();
                defs.Add(new RtuCaseDef("CorruptNextResponse_Rejected_NextTransactionNormal",
                    CaseCorruptNextRejectThenRecover));
            }
            else if (phase == "all")
            {
                defs = NormalCases();
                defs.Add(new RtuCaseDef("CorruptNextResponse_Rejected_NextTransactionNormal",
                    CaseCorruptNextRejectThenRecover));
            }
            else if (phase == "normal")
            {
                defs = NormalCases();
            }
            else
            {
                throw new ArgumentException("未知阶段 '" + phase + "'（可用：normal|corrupt|all）");
            }
            return RunCases(defs);
        }

        private static List<RtuContractCaseResult> RunCases(List<RtuCaseDef> defs)
        {
            List<RtuContractCaseResult> results = new List<RtuContractCaseResult>();
            foreach (RtuCaseDef def in defs)
            {
                // 每条用例独立开/关串口：隔离状态，单条失败不污染后续用例
                ModbusRtuClient client = new ModbusRtuClient(ClientPortName, BaudRate,
                    Parity.None, 8, StopBits.One, UnitId, TimeoutMs);
                try
                {
                    client.Open();
                    Check(client.IsOpen, "串口 {0} 打开后 IsOpen 应为 true", ClientPortName);
                    def.Body(client);
                    results.Add(new RtuContractCaseResult(def.Name, true, ""));
                }
                catch (RtuContractFailureException ex)
                {
                    results.Add(new RtuContractCaseResult(def.Name, false, ex.Message));
                }
                catch (Exception ex)
                {
                    results.Add(new RtuContractCaseResult(def.Name, false,
                        ex.GetType().Name + ": " + ex.Message));
                }
                finally
                {
                    client.Close();     // Close() 幂等
                }
                RtuContractCaseResult r = results[results.Count - 1];
                Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "[{0}] {1}{2}",
                    r.Passed ? "PASS" : "FAIL", r.Name,
                    r.Passed ? "" : "  -- " + r.Detail));
            }
            return results;
        }

        // ------------------------------------------------------------------ 用例

        /// <summary>N1：FC3 读种子寄存器，0=1234、1=5678 必须原样读出（RTU 帧 + CRC 全链路）。</summary>
        private static void CaseFc3ReadSeeds(ModbusRtuClient client)
        {
            ushort[] regs = client.ReadHoldingRegisters(0, 2);
            Check(regs != null && regs.Length == 2, "FC3 返回 {0} 个寄存器，期望 2",
                regs == null ? -1 : regs.Length);
            Check(regs[0] == 1234 && regs[1] == 5678,
                "种子寄存器不符：期望 [1234, 5678]，实际 [{0}, {1}]", regs[0], regs[1]);
        }

        /// <summary>N2：FC6 写单寄存器后 FC3 回读一致（写两个不同值，排除初值巧合）。</summary>
        private static void CaseFc6WriteReadBack(ModbusRtuClient client)
        {
            WriteThenVerifyRegister(client, AddrFc6, 0xABCD);
            WriteThenVerifyRegister(client, AddrFc6, 0x0102);
        }

        /// <summary>N3：FC16 批量写 3 个寄存器，块读 + 逐个回读一致。</summary>
        private static void CaseFc16WriteReadBack(ModbusRtuClient client)
        {
            ushort[] values = new ushort[] { 0x0102, 0x0304, 0x0506 };
            client.WriteMultipleRegisters(AddrFc16, values);
            ushort[] block = client.ReadHoldingRegisters(AddrFc16, 3);
            Check(block.Length == 3 && block[0] == 0x0102 && block[1] == 0x0304 && block[2] == 0x0506,
                "FC16 块读回不符：[{0}, {1}, {2}]", block[0], block[1], block[2]);
            for (int i = 0; i < values.Length; i++)
            {
                ushort[] one = client.ReadHoldingRegisters((ushort)(AddrFc16 + i), 1);
                Check(one.Length == 1 && one[0] == values[i],
                    "FC16 逐个回读 [{0}] 不符：期望 0x{1:X4}，实际 0x{2:X4}", i, values[i], one[0]);
            }
        }

        /// <summary>N4：FC5 写单线圈 ON/OFF 各一次，FC1 回读布尔一致（0xFF00=ON 语义）。</summary>
        private static void CaseFc5CoilWriteRead(ModbusRtuClient client)
        {
            client.WriteSingleCoil(AddrFc5, true);
            bool[] on = client.ReadCoils(AddrFc5, 1);
            Check(on.Length == 1 && on[0], "FC5 写 ON 后 FC1 读回应为 true，实际 {0}", on[0]);
            client.WriteSingleCoil(AddrFc5, false);
            bool[] off = client.ReadCoils(AddrFc5, 1);
            Check(off.Length == 1 && !off[0], "FC5 写 OFF 后 FC1 读回应为 false，实际 {0}", off[0]);
        }

        /// <summary>N5：FC15 写多线圈（10101 位型），FC1 回读位打包一致（LSB first）。</summary>
        private static void CaseFc15CoilsWriteRead(ModbusRtuClient client)
        {
            bool[] pattern = new bool[] { true, false, true, false, true };
            client.WriteMultipleCoils(AddrFc15, pattern);
            bool[] back = client.ReadCoils(AddrFc15, (ushort)pattern.Length);
            Check(back.Length == pattern.Length, "FC15 回读数量 {0}，期望 {1}",
                back.Length, pattern.Length);
            for (int i = 0; i < pattern.Length; i++)
            {
                Check(back[i] == pattern[i], "FC15 线圈 [{0}] 不符：期望 {1}，实际 {2}",
                    i, pattern[i], back[i]);
            }
        }

        /// <summary>N6：FC3 数量 0 必须被客户端本地拦截（ArgumentException），不发线上帧。</summary>
        private static void CaseFc3ZeroQuantity(ModbusRtuClient client)
        {
            bool rejected = false;
            try
            {
                client.ReadHoldingRegisters(0, 0);
            }
            catch (ArgumentException)
            {
                rejected = true;
            }
            Check(rejected, "FC3 数量 0 必须客户端本地拦截（ArgumentException）");
        }

        /// <summary>N7：地址越界 9999+2 → 从站异常码 02；且异常事务后总线不毒化（补一次正常读）。</summary>
        private static void CaseFc3OutOfRange(ModbusRtuClient client)
        {
            bool threw = false;
            try
            {
                client.ReadHoldingRegisters(AddrOutOfRange, 2);
            }
            catch (ModbusSlaveException ex)
            {
                threw = true;
                Check(ex.ExceptionCode == 0x02, "越界应得异常码 02，实际 0x{0:X2}", ex.ExceptionCode);
                Check(ex.FunctionCode == 0x03, "异常功能码应归一为原始码 03，实际 0x{0:X2}", ex.FunctionCode);
            }
            Check(threw, "地址越界必须抛 ModbusSlaveException");
            // 异常帧消费完整、管道未毒化：紧接一次正常读必须成功
            ushort[] regs = client.ReadHoldingRegisters(0, 1);
            Check(regs.Length == 1 && regs[0] == 1234,
                "异常事务后正常读失败（管道疑似毒化）：期望 1234，实际 {0}",
                regs.Length == 1 ? regs[0] : -1);
        }

        /// <summary>
        /// N8：广播闭环——WriteSingleRegisterNoResponse(800, 777) 无异常快速返回，
        /// 随后 FC3 unit1 读回 800==777，证明从站收到并执行了广播（无响应语义闭环）。
        /// </summary>
        private static void CaseBroadcastClosedLoop(ModbusRtuClient client)
        {
            Stopwatch sw = Stopwatch.StartNew();
            client.WriteSingleRegisterNoResponse(AddrBroadcast, 777);   // 广播：不回帧，不抛异常
            sw.Stop();
            Check(sw.ElapsedMilliseconds < TimeoutMs,
                "广播调用应快速返回（< 响应超时 {0}ms），实测 {1}ms", TimeoutMs, sw.ElapsedMilliseconds);
            ushort[] regs = client.ReadHoldingRegisters(AddrBroadcast, 1);
            Check(regs.Length == 1 && regs[0] == 777,
                "广播闭环失败：FC6 广播写 777 后 FC3 读回 {0}（从站未执行广播？）",
                regs.Length == 1 ? regs[0] : -1);
        }

        /// <summary>
        /// N9：turnaround delay 实测——广播发送完成到方法返回的间隔 ≥ 下限常量
        /// BroadcastTurnaroundDelayMinMs(100ms)（实现应等 BroadcastTurnaroundDelayMs=150ms），
        /// 且不应显著超过上限（200ms+400ms 余量）。顺便验证该广播写已被从站执行。
        /// spec_ref: MODBUS over Serial Line V1.02 §2.4.1 p10（modbus.json 对账 2026-10-21）。
        /// </summary>
        private static void CaseBroadcastTurnaround(ModbusRtuClient client)
        {
            Stopwatch sw = Stopwatch.StartNew();
            client.WriteSingleRegisterNoResponse(AddrTurnaround, 0xBEEF);
            sw.Stop();
            long measured = sw.ElapsedMilliseconds;
            Check(measured >= ModbusRtuClient.BroadcastTurnaroundDelayMinMs,
                "实测广播间隔 {0}ms < 常量下限 {1}ms（turnaround delay 未兑现？）",
                measured, ModbusRtuClient.BroadcastTurnaroundDelayMinMs);
            Check(measured <= (long)ModbusRtuClient.BroadcastTurnaroundDelayMaxMs + 400,
                "实测广播间隔 {0}ms 显著超过常量上限 {1}ms+余量（疑似在等响应）",
                measured, ModbusRtuClient.BroadcastTurnaroundDelayMaxMs);
            ushort[] regs = client.ReadHoldingRegisters(AddrTurnaround, 1);
            Check(regs.Length == 1 && regs[0] == 0xBEEF,
                "turnaround 用例的广播写未被执行：期望 0xBEEF，实际 0x{0:X4}",
                regs.Length == 1 ? regs[0] : 0);
        }

        /// <summary>N10：连续 30 次事务（FC6/FC3 交替）零错误。</summary>
        private static void CaseStress30(ModbusRtuClient client)
        {
            const int total = 30;
            int lastWritten = -1;
            for (int i = 0; i < total; i++)
            {
                if (i % 2 == 0)
                {
                    int val = 1000 + i;
                    client.WriteSingleRegister(AddrStress, (ushort)val);
                    lastWritten = val;
                }
                else
                {
                    ushort[] regs = client.ReadHoldingRegisters(AddrStress, 1);
                    Check(regs.Length == 1 && regs[0] == (ushort)lastWritten,
                        "压力事务 #{0} 读回不符：期望 {1}，实际 {2}", i, lastWritten, regs[0]);
                }
            }
            Check(true, "");    // 走到这里 = 30 事务零异常
        }

        /// <summary>
        /// C1（corrupt 阶段，从站以 --corrupt-next 启动）：第一个响应故意坏 CRC →
        /// 客户端必须拒收（CRC 校验失败抛 InvalidDataException；若链路把帧吃掉则
        /// 退化为 TimeoutException，也算拒收）；下一事务必须立即恢复正常——
        /// 证明劣化只注入一帧、接收管道不毒化。
        /// </summary>
        private static void CaseCorruptNextRejectThenRecover(ModbusRtuClient client)
        {
            string rejectDetail = "";
            bool rejected = false;
            try
            {
                client.ReadHoldingRegisters(0, 2);      // 本实例第一个响应 = 坏 CRC
            }
            catch (InvalidDataException ex)
            {
                rejected = true;
                rejectDetail = "InvalidDataException: " + ex.Message;
            }
            catch (TimeoutException)
            {
                rejected = true;
                rejectDetail = "TimeoutException(可接受的拒收形态)";
            }
            Check(rejected, "坏 CRC 响应必须被拒收（实际未抛异常）");
            Console.WriteLine(string.Format(CultureInfo.InvariantCulture,
                "      拒收形态: {0}", rejectDetail));
            ushort[] regs = client.ReadHoldingRegisters(0, 2);
            Check(regs.Length == 2 && regs[0] == 1234 && regs[1] == 5678,
                "坏 CRC 后下一事务必须恢复正常：期望 [1234,5678]，实际 [{0}, {1}]",
                regs.Length == 2 ? regs[0] : -1, regs.Length == 2 ? regs[1] : -1);
        }

        // ------------------------------------------------------------------ 工具

        private static void WriteThenVerifyRegister(ModbusRtuClient client, ushort addr, ushort value)
        {
            client.WriteSingleRegister(addr, value);
            ushort[] regs = client.ReadHoldingRegisters(addr, 1);
            Check(regs.Length == 1 && regs[0] == value,
                "FC6 写读回不符：写 0x{0:X4}，读回 0x{1:X4}", value, regs.Length == 1 ? regs[0] : 0);
        }

        private static void Check(bool ok, string format, params object[] args)
        {
            if (!ok)
            {
                throw new RtuContractFailureException(string.Format(
                    CultureInfo.InvariantCulture, format, args));
            }
        }
    }

    // ============================================================================
    //  运行入口：ModbusRtuContractRunner.exe [normal|corrupt|all]（缺省 all）
    //  逐条回显 PASS/FAIL+用例名；另输出机器可解析行：
    //    RESULT<TAB>PASS|FAIL<TAB>用例名<TAB>失败说明
    //  退出码 = 失败用例数（0 = 全部通过）。
    // ============================================================================
    internal static class ModbusRtuContractRunner
    {
        private static int Main(string[] args)
        {
            try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }
            string phase = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "all";
            Console.WriteLine("==== Modbus RTU 行为契约测试（阶段: " + phase + "）====");
            Console.WriteLine("链路: 本 exe(" + ModbusRtuContractTests.ClientPortName + ") ══com0com 虚拟对══ " +
                ModbusRtuContractTests.SlavePortName + "(python 从站)" +
                "  baud=" + ModbusRtuContractTests.BaudRate + "(虚拟对忽略)" +
                "  unit=" + ModbusRtuContractTests.UnitId +
                "  timeout=" + ModbusRtuContractTests.TimeoutMs + "ms");
            Console.WriteLine();

            List<RtuContractCaseResult> results;
            try
            {
                results = ModbusRtuContractTests.RunPhase(phase);
            }
            catch (ArgumentException ex)
            {
                Console.WriteLine("未知阶段 '" + phase + "'：" + ex.Message);
                Console.WriteLine("用法: ModbusRtuContractRunner.exe [normal|corrupt|all]");
                return 98;
            }

            Console.WriteLine();
            int failed = 0;
            foreach (RtuContractCaseResult r in results)
            {
                if (!r.Passed) failed++;
                Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "RESULT\t{0}\t{1}\t{2}",
                    r.Passed ? "PASS" : "FAIL", r.Name, r.Passed ? "" : r.Detail));
            }
            Console.WriteLine();
            Console.WriteLine(string.Format(CultureInfo.InvariantCulture,
                "RTU 契约用例（阶段 {0}）{1} 条：通过 {2}，失败 {3}",
                phase, results.Count, results.Count - failed, failed));
            return failed;      // 退出码 = 失败数
        }
    }
}
