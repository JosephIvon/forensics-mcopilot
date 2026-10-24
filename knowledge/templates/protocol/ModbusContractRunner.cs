// ============================================================================
//  ModbusContractRunner.cs —— 契约测试运行入口
//  用法：ModbusContractRunner.exe [normal|fragment|sticky|all]（缺省 normal）
//  Main 调 ModbusContractTests.RunPhase(phase)，逐条回显 PASS/FAIL+用例名，
//  另输出机器可解析行：RESULT<TAB>PASS|FAIL<TAB>用例名<TAB>失败说明
//  退出码 = 失败用例数（0 = 全部通过）。
//  C# 5 兼容写法（.NET Framework 4 自带 csc.exe 可直接编译）。
//  ⚠ 双 Main 不可同编：本文件 Main 与 ModbusContracts.cs 的 Main 不能在同一次 csc
//    编译中共存（CS0017）。本入口只配 ModbusTcpClient.cs + ModbusContractTests.cs
//    （见 run_contract.ps1 的源文件清单）；ModbusContracts.cs 由 scripts/smoke_modbus.py 单独编译。
// ============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Mcopilot.Protocols.Modbus.ContractTests;

internal static class ModbusContractRunner
{
    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch { }
        string phase = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "normal";
        Console.WriteLine("==== Modbus TCP 行为契约测试（阶段: " + phase + "）====");
        Console.WriteLine("目标: " + ModbusContractTests.SlaveHost +
            "  normal=" + ModbusContractTests.SlavePort +
            "  split3=" + ModbusContractTests.FragmentSplit3Port +
            "  byte1=" + ModbusContractTests.FragmentByte1Port +
            "  sticky=" + ModbusContractTests.StickyStalePort +
            "  unit=" + ModbusContractTests.UnitId);
        Console.WriteLine();

        List<ContractCaseResult> results;
        try
        {
            results = ModbusContractTests.RunPhase(phase);
        }
        catch (ArgumentException ex)
        {
            Console.WriteLine("未知阶段 '" + phase + "'：" + ex.Message);
            Console.WriteLine("用法: ModbusContractRunner.exe [normal|fragment|sticky|all]");
            return 98;
        }

        Console.WriteLine();
        int failed = 0;
        foreach (ContractCaseResult r in results)
        {
            if (!r.Passed) failed++;
            Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "RESULT\t{0}\t{1}\t{2}",
                r.Passed ? "PASS" : "FAIL", r.Name, r.Passed ? "" : r.Detail));
        }
        Console.WriteLine();
        Console.WriteLine(string.Format(CultureInfo.InvariantCulture,
            "契约用例（阶段 {0}）{1} 条：通过 {2}，失败 {3}",
            phase, results.Count, results.Count - failed, failed));
        return failed;      // 退出码 = 失败数
    }
}
