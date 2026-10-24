// ============================================================================
//  SLMP 协议契约测试（P2）—— ProtocolContractTests 模式的 SLMP 分册。
//  对端：自建契约桩（scripts/smoke_slmp.py）；diagslave 等价的 SLMP 模拟器待 TODO[需实测]。
//  每条断言注明知识依据（knowledge/protocols/slmp.json 条目）。
//
//  跑法：SlmpContracts.exe [host] [port]   （默认 127.0.0.1:10270）
// ============================================================================
using System;
using System.Globalization;
using System.IO;
using Mcopilot.Protocols.Slmp;

class SlmpContracts
{
    static int _fails;
    static string _host = "127.0.0.1";
    static int _port = 10270;

    static int Main(string[] args)
    {
        if (args.Length > 0) _host = args[0];
        if (args.Length > 1) int.TryParse(args[1], out _port);
        try
        {
            return Run();
        }
        catch (Exception ex)
        {
            Console.WriteLine("[CONTRACT] RESULT: FAIL - " + ex.Message);
            return 1;
        }
    }

    static int Run()
    {
        var c = new SlmpTcpClient(_host, _port, 3000);

        // C1 连接生命周期
        c.Connect();
        Check(c.IsConnected, "C1 连接后 IsConnected=true");
        c.Close();
        Check(!c.IsConnected, "C1 关闭后 IsConnected=false");
        c.Connect();
        Check(c.IsConnected, "C1 重连成功");
        Console.WriteLine("[CONTRACT] C1 连接生命周期 OK");

        // C2 批量读预置（依据 slmp.json SLMP-CMD-0401 + SLMP-DEV-D*-A8H：桩预置 D100=0x1234）
        ushort[] r = c.ReadWordDevices(SlmpDevice.DataRegisterD, 100, 3);
        Check(r.Length == 3 && r[0] == 0x1234, "C2 0401H 读 D100 预置");
        Console.WriteLine("[CONTRACT] C2 批量读 D100..102 OK");

        // C3 数量上限：961 字必须显式拒绝（依据 SLMP-CMD-0401：BIN 960 words 上限）。
        // 合法路径：客户端本地校验（ArgumentOutOfRangeException）或对端结束代码非 0。
        bool c3 = false;
        try { c.ReadWordDevices(SlmpDevice.DataRegisterD, 0, 961); }
        catch (ArgumentOutOfRangeException) { c3 = true; }
        catch (SlmpException) { c3 = true; }
        Check(c3, "C3 数量 961 > 960 显式拒绝");
        Console.WriteLine("[CONTRACT] C3 数量上限显式拒绝 OK");

        // C4 软元件/编号越界：桩对 D>2000 回非 0 结束代码（依据 3E 帧 End code 机制，slmp.json framing）
        bool c4 = false;
        try { c.ReadWordDevices(SlmpDevice.DataRegisterD, 90000, 1); }
        catch (SlmpException ex) { c4 = ex.EndCode != 0x0000; }
        Check(c4, "C4 越界必须非 0 结束代码");
        Console.WriteLine("[CONTRACT] C4 越界结束代码 OK");

        // C5 未知指令 9999H（TransactRaw 原样帧）：对端必须回非 0 结束代码（依据 3E 帧响应结构）。
        // 手工整帧：副头 5000H / net 0 / PC FF / I/O FF03 / multi 0 / len=12(0C)=timer2+cmd2+sub2+dev1+num3+count2
        var req = new byte[] {
            0x00, 0x50, 0x00, 0xFF, 0xFF, 0x03, 0x00,
            0x0C, 0x00, 0x00, 0x00,
            0x99, 0x99, 0x00, 0x00, 0xA8, 0x64, 0x00, 0x00, 0x01, 0x00 };
        bool c5 = false;
        try
        {
            c.TransactRaw(req);
        }
        catch (SlmpException ex) { c5 = ex.EndCode != 0x0000; }
        catch (IOException) { c5 = true; }   // 桩选择直接断开也算显式拒绝
        Check(c5, "C5 未知指令 9999H 显式拒绝");
        Console.WriteLine("[CONTRACT] C5 未知指令 OK");

        // C6 写读闭环 1401H → 0401H（依据 slmp.json SLMP-CMD-1401）
        c.WriteWordDevices(SlmpDevice.DataRegisterD, 200, new ushort[] { 0xABCD, 0xEF12 });
        r = c.ReadWordDevices(SlmpDevice.DataRegisterD, 200, 2);
        Check(r.Length == 2 && r[0] == 0xABCD && r[1] == 0xEF12, "C6 1401H 写读回");
        Console.WriteLine("[CONTRACT] C6 写读闭环 OK");

        // C7 大端小端核对：写 0x1234 读回应为 0x1234（线上一律小端字节序，客户端已解）
        c.WriteWordDevices(SlmpDevice.DataRegisterD, 300, new ushort[] { 0x0102 });
        r = c.ReadWordDevices(SlmpDevice.DataRegisterD, 300, 1);
        Check(r.Length == 1 && r[0] == 0x0102, "C7 字节序闭环");
        Console.WriteLine("[CONTRACT] C7 字节序 OK");

        // C8 异常对象字段：SlmpException.EndCode == 对端回的原始码
        try
        {
            c.ReadWordDevices(SlmpDevice.DataRegisterD, 90000, 1);
            Check(false, "C8 越界必须抛 SlmpException");
        }
        catch (SlmpException ex)
        {
            Check(ex.EndCode != 0x0000, "C8 EndCode 字段透传");
        }
        Console.WriteLine("[CONTRACT] C8 结束代码字段 OK");

        // C9 超时显式
        var dead = new SlmpTcpClient("127.0.0.1", 15999, 1500);
        var sw = System.Diagnostics.Stopwatch.StartNew();
        bool threw = false;
        try { dead.Connect(); }
        catch (Exception) { threw = true; }
        sw.Stop();
        Check(threw && sw.ElapsedMilliseconds < 5000, "C9 连接失败显式且及时");
        Console.WriteLine("[CONTRACT] C9 超时显式 OK（{0}ms）",
            sw.ElapsedMilliseconds.ToString(CultureInfo.InvariantCulture));

        // C10 TODO[需实测]: 位单位读写（0001H 子指令）与真机 CPU 互操作——桩本轮只实现字单位
        Console.WriteLine("[CONTRACT] C10 位单位/真机 —— TODO[需实测]");

        c.Close();
        Console.WriteLine(_fails == 0 ? "[CONTRACT] RESULT: PASS" : "[CONTRACT] RESULT: FAIL (" + _fails + ")");
        return _fails == 0 ? 0 : 1;
    }

    static void Check(bool ok, string tag)
    {
        if (!ok) { Console.WriteLine("[CONTRACT] FAIL at " + tag); _fails++; }
    }
}
