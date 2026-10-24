// ============================================================================
//  Modbus 协议契约测试（P2）—— MotionContractTests 模式移植。
//  「任何 Modbus TCP 客户端实现都必须过这套」，对端可为：契约桩 / diagslave / 真机。
//  每条断言注明知识依据（knowledge/protocols/modbus.json 的条目/章节）。
//
//  ⚠ 双 Main 不可同编：本文件自带 Main 入口，与 ModbusContractRunner.cs（另一契约
//  套件 ModbusContractTests.cs 的运行入口）**不能在同一次 csc 编译中共存**——
//  两个 Main 会报 CS0017。二选一：
//    - 跑本文件：scripts/smoke_modbus.py（自带最小桩，客户端+本文件编译为 ModbusContracts.exe）
//    - 跑另一套：run_contract.ps1（ModbusTcpClient.cs + ModbusContractTests.cs + ModbusContractRunner.cs）
//
//  跑法：ModbusContracts.exe [host] [port]   （默认 127.0.0.1:15020）
//  TODO[需实测]: 对 diagslave 正式模拟器与真机 PLC 跑同一套契约（P2/P4）。
// ============================================================================
using System;
using System.Globalization;
using Mcopilot.Protocols.Modbus;

class ModbusContracts
{
    static int _fails;
    static string _host = "127.0.0.1";
    static int _port = 15020;

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
        var c = new ModbusTcpClient(_host, _port, 3000, 3000, 3000);

        // C1 连接生命周期：连接/关闭/重连显式（契约：IsConnected 可观测）
        c.Connect();
        Check(c.IsConnected, "C1 连接后 IsConnected=true");
        c.Close();
        Check(!c.IsConnected, "C1 关闭后 IsConnected=false");
        c.Connect();
        Check(c.IsConnected, "C1 重连成功");
        Console.WriteLine("[CONTRACT] C1 连接生命周期 OK");

        // C2 FC03 读已知预置（依据 modbus.json function_codes[3] / register_model 保持寄存器表）
        ushort[] r = c.ReadHoldingRegisters(1, 0, 4);
        Check(r.Length == 4 && r[0] == 0x1234, "C2 FC03 预置值");
        Console.WriteLine("[CONTRACT] C2 FC03 读保持寄存器 OK");

        // C3 数量上限：126 寄存器必须被显式拒绝（依据 function_codes[3]：Quantity 1 to 125(0x7D)）。
        // 合法路径有二：客户端本地校验先拒（ArgumentException），或对端异常 03——沉默接受才是契约违背。
        bool c3Rejected = false;
        try
        {
            c.ReadHoldingRegisters(1, 0, 126);
        }
        catch (ArgumentException ex)
        {
            c3Rejected = ex.Message.Contains("125");
        }
        catch (ModbusSlaveException ex)
        {
            c3Rejected = ex.ExceptionCode == 0x03;
        }
        Check(c3Rejected, "C3 数量 126 必须显式拒绝（本地校验或异常 03）");
        Console.WriteLine("[CONTRACT] C3 数量上限显式拒绝 OK");

        // C4 地址越界：异常 02（依据 exception_codes[02] ILLEGAL DATA ADDRESS）。
        // 口径与交付 fixture（tests/fixtures/modbus/modbus_tcp_slave.py，每区 10000 元素，地址 0..9999）一致：
        // 不得再用「地址 100」当越界地址（对 10000 元素从站是合法地址）。两条证据：
        //   a) 0xFFFF 裸帧（任何合理内存区都越界）→ 原始帧收 [FC|0x80, 0x02]；
        //   b) 9999+2 类型化读（正好跨出 0..9999）→ ModbusSlaveException(02)。
        // 注：客户端把 ModbusSlaveException.FunctionCode 归一为原始功能码（剥 0x80 标志）。
        byte[] c4raw = c.TransactRaw(1, new byte[] { 0x03, 0xFF, 0xFF, 0x00, 0x01 });
        Check(c4raw.Length == 2 && c4raw[0] == 0x83 && c4raw[1] == 0x02,
              "C4 0xFFFF 裸帧越界应收 83 02，实际 " + BitConverter.ToString(c4raw));
        Console.WriteLine("[CONTRACT] C4 0xFFFF 裸帧越界 -> 02 OK");
        ExpectException(c, () => c.ReadHoldingRegisters(1, 9999, 2),
                        "C4 越界地址 9999+2", 0x03, 0x02);

        // C5 非法功能码 0x2F（依据 exception_codes[01] ILLEGAL FUNCTION）。
        // TransactRaw 是低层原样事务（异常检测在类型化层），契约自检返回 PDU：应为 [0x2F|0x80, 0x01]。
        byte[] raw = c.TransactRaw(1, new byte[] { 0x2F, 0x00, 0x00 });
        Check(raw.Length == 2 && raw[0] == 0xAF && raw[1] == 0x01,
              "C5 非法功能码返回异常帧 AF 01");
        Console.WriteLine("[CONTRACT] C5 非法功能码原样帧 OK（0xAF 0x01）");

        // C6 写读闭环 FC06（依据 function_codes[6]）
        c.WriteSingleRegister(1, 10, 0xABCD);
        r = c.ReadHoldingRegisters(1, 10, 1);
        Check(r.Length == 1 && r[0] == 0xABCD, "C6 FC06 写读回");
        Console.WriteLine("[CONTRACT] C6 FC06 写读闭环 OK");

        // C7 写多寄存器 FC16 + 读回（依据 function_codes[16]）
        c.WriteMultipleRegisters(1, 20, new ushort[] { 0x0102, 0x0304, 0x0506 });
        r = c.ReadHoldingRegisters(1, 20, 3);
        Check(r.Length == 3 && r[0] == 0x0102 && r[2] == 0x0506, "C7 FC16 写读回");
        Console.WriteLine("[CONTRACT] C7 FC16 批量写 OK");

        // C8 线圈 0xFF00 语义：FC05 ON 后 FC01 读回 true（依据 function_codes[5]：FF00=ON，其他值非法）
        c.WriteSingleCoil(1, 0, true);
        bool[] b = c.ReadCoils(1, 0, 3);
        Check(b.Length == 3 && b[0] && !b[1], "C8 FC05/FC01 线圈写读");
        Console.WriteLine("[CONTRACT] C8 线圈 0xFF00 语义 OK");

        // C9 异常翻译链：ModbusSlaveException.ExceptionCode 必须等于规范异常码（依据 exception_codes 全集）。
        // 口径同 C4：9999+2 越界（每区 10000 元素），不用地址 100。
        try
        {
            c.ReadHoldingRegisters(1, 9999, 2);
            Check(false, "C9 越界必须抛 ModbusSlaveException");
        }
        catch (ModbusSlaveException ex)
        {
            Check(ex.ExceptionCode == 0x02 && ex.FunctionCode == 0x03,
                  "C9 异常码字段（ExceptionCode=0x02 / FunctionCode=0x03 原始码）");
        }
        Console.WriteLine("[CONTRACT] C9 异常翻译链 OK");

        // C10 超时显式：连不存在的端口必须在有限时间抛异常，不许悬挂
        var dead = new ModbusTcpClient("127.0.0.1", 15999, 1500);
        var sw = System.Diagnostics.Stopwatch.StartNew();
        bool threw = false;
        try { dead.Connect(); }
        catch (Exception) { threw = true; }
        sw.Stop();
        Check(threw && sw.ElapsedMilliseconds < 5000, "C10 连接失败显式且及时");
        Console.WriteLine("[CONTRACT] C10 超时显式 OK（{0}ms）",
            sw.ElapsedMilliseconds.ToString(CultureInfo.InvariantCulture));

        // C11 TODO[需实测]: 断线重连（网络闪断后恢复语义）——桩不可模拟，P4 真机波
        // TODO[需实测]: 广播（unit=0）行为——串行域语义，TCP 桩不可模拟
        Console.WriteLine("[CONTRACT] C11 断线重连/广播 —— TODO[需实测]（P4 真机波）");

        // C12 数量 0：Quantity 的下限同样是协议硬约束（function_codes[3]：Quantity 1 to 125）。
        // C3 只管上限（126），且允许「本地拒」与「对端回 03」两种合法表现；
        // 数量 0 必须**本地**拒：发上线等于让对端替我发现自己发错了，客户端拿不到直接证据。
        bool c12Local = false;
        try { c.ReadHoldingRegisters(1, 0, 0); }
        catch (ArgumentException) { c12Local = true; }
        catch (ModbusSlaveException) { }   // 上了线（对端回 03）= 契约违背，保持 false
        Check(c12Local, "C12 数量 0 必须本地拦截（不上线）");
        Console.WriteLine("[CONTRACT] C12 数量 0 本地拦截 OK");

        c.Close();
        Console.WriteLine(_fails == 0 ? "[CONTRACT] RESULT: PASS" : "[CONTRACT] RESULT: FAIL (" + _fails + ")");
        return _fails == 0 ? 0 : 1;
    }

    static void ExpectException(ModbusTcpClient c, Action call,
                                string tag, byte wantFunc, byte wantCode)
    {
        try
        {
            call();
            Console.WriteLine("[CONTRACT] FAIL at {0}: 未抛异常", tag);
            _fails++;
        }
        catch (ModbusSlaveException ex)
        {
            if (ex.FunctionCode != wantFunc || ex.ExceptionCode != wantCode)
            {
                Console.WriteLine("[CONTRACT] FAIL at {0}: FunctionCode=0x{1:X2}/ExceptionCode=0x{2:X2}，期望 0x{3:X2}/0x{4:X2}",
                    tag, ex.FunctionCode, ex.ExceptionCode, wantFunc, wantCode);
                _fails++;
            }
            else
            {
                Console.WriteLine("[CONTRACT] {0} -> 异常 0x{1:X2} OK", tag, ex.ExceptionCode);
            }
        }
    }

    static void Check(bool ok, string tag)
    {
        if (!ok) { Console.WriteLine("[CONTRACT] FAIL at " + tag); _fails++; }
    }
}
