// ============================================================================
//  Modbus RTU 客户端（零第三方依赖，基于 System.IO.Ports.SerialPort）
//  —— 由 mcopilot protocol 生成；C# 7.3，可在 .NET Framework 4.8 直接编译。
//
//  帧格式：[从机地址(1)][功能码+数据 = PDU][CRC16 低字节][CRC16 高字节]
//  spec_ref(帧格式): MODBUS over Serial Line V1.02 §2.5.1.2 RTU 传输模式, 待与 modbus.json 对账。
//
//  本文件的静态纯函数层（不碰 IO，可单测）：
//    - ModbusCrc16   CRC16（反射多项式 0xA001，初值 0xFFFF）
//    - ModbusRtuFrame  RTU 帧构造/解析（含 CRC 校验）
//    - ModbusRtuClient.CalcT35Milliseconds  t3.5 帧间隔按波特率计算
//  行为层广播：ModbusRtuClient.SendBroadcast（地址 0、无响应、仅写命令、发送后等
//    turnaround delay——常量与 spec_ref 见类内「RTU 广播」段，值抄录自 modbus.json
//    limits_and_timeouts）。
//  PDU 层（功能码级构造/解析）在 ModbusTcpClient.cs，与 TCP 共用。
// ============================================================================

using System;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Threading;

namespace Mcopilot.Protocols.Modbus
{
    /// <summary>
    /// CRC16/Modbus：反射多项式 0xA001（即 0x8005 的反射），初值 0xFFFF，结果低字节在前上送。
    /// spec_ref(算法): MODBUS over Serial Line V1.02 §2.5.1.2 "CRC 生成", 待与 modbus.json 对账。
    /// spec_ref(字节序): 帧尾先低后高，同上 §2.5.1.2, 待对账。
    /// 自检锚点："123456789" → 0x4B37（CRC 目录标准校验值）；11 03 00 6B 00 03 → 0x8776（规范示例）。
    /// </summary>
    public static class ModbusCrc16
    {
        /// <summary>CRC 初值固定 0xFFFF。spec_ref: 同类注释, 待对账。</summary>
        public const ushort InitialValue = 0xFFFF;
        /// <summary>反射多项式 0xA001（= 0x8005 反射）。spec_ref: 同类注释, 待对账。</summary>
        public const ushort ReflectedPolynomial = 0xA001;

        /// <summary>计算 CRC16（逐位反射算法，无查表、无依赖，帧短够用）。</summary>
        public static ushort Compute(byte[] data, int offset, int count)
        {
            if (data == null) throw new ArgumentNullException("data");
            if (offset < 0 || count < 0 || offset + count > data.Length)
                throw new ArgumentOutOfRangeException("offset", "offset/count 越界");
            ushort crc = InitialValue;
            for (int i = offset; i < offset + count; i++)
            {
                crc ^= data[i];
                for (int bit = 0; bit < 8; bit++)
                {
                    if ((crc & 1) != 0)
                        crc = (ushort)((crc >> 1) ^ ReflectedPolynomial);
                    else
                        crc = (ushort)(crc >> 1);
                }
            }
            return crc;
        }

        /// <summary>便捷重载：整段数据。</summary>
        public static ushort Compute(byte[] data) { return Compute(data, 0, data.Length); }
    }

    /// <summary>
    /// RTU 帧构造与解析。static 纯函数，可单测。
    /// 帧 = 地址(1) + PDU(n) + CRC16(2，低字节在前)。
    /// spec_ref: MODBUS over Serial Line V1.02 §2.5.1.2, 待与 modbus.json 对账。
    /// </summary>
    public static class ModbusRtuFrame
    {
        /// <summary>帧最小长度：地址 + 功能码 + CRC = 4（如异常响应帧 5 字节）。</summary>
        public const int MinFrameSize = 4;

        /// <summary>构造完整 RTU 帧：addr + pdu + CRC(低,高)。地址 0 为广播地址。spec_ref: 广播 §2.1, 待对账。</summary>
        public static byte[] BuildFrame(byte unitAddress, byte[] pdu)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (pdu.Length < 1 || pdu.Length > ModbusConst.MaxPduSize)
                throw new ArgumentOutOfRangeException("pdu", "PDU 长度必须在 1.." + ModbusConst.MaxPduSize);
            byte[] frame = new byte[1 + pdu.Length + 2];
            frame[0] = unitAddress;
            Buffer.BlockCopy(pdu, 0, frame, 1, pdu.Length);
            ushort crc = ModbusCrc16.Compute(frame, 0, frame.Length - 2);   // CRC 覆盖地址+PDU，不含自身
            frame[frame.Length - 2] = (byte)(crc & 0xFF);                   // 低字节在前
            frame[frame.Length - 1] = (byte)(crc >> 8);                     // 高字节在后
            return frame;
        }

        /// <summary>解析 RTU 帧：校验长度与 CRC，通过则给出地址与 PDU。CRC 错/帧过短返回 false（静默丢弃是 RTU 正确姿势）。</summary>
        public static bool TryParseFrame(byte[] frame, int count, out byte unitAddress, out byte[] pdu)
        {
            unitAddress = 0; pdu = null;
            if (frame == null || count < MinFrameSize || count > ModbusConst.MaxRtuAduSize) return false;
            ushort rx = (ushort)(frame[count - 2] | (frame[count - 1] << 8));   // 尾 2 字节 = CRC(低,高)
            ushort expect = ModbusCrc16.Compute(frame, 0, count - 2);
            if (rx != expect) return false;                                     // CRC 不符
            unitAddress = frame[0];
            pdu = new byte[count - 3];                                          // 去掉地址(1)与 CRC(2)
            Buffer.BlockCopy(frame, 1, pdu, 0, pdu.Length);
            return true;
        }
    }

    /// <summary>
    /// Modbus RTU 串口客户端（零第三方依赖，基于 System.IO.Ports.SerialPort）。
    /// 单实例对应一个串口；内部加锁串行化事务；发送前按 t3.5 保持帧间隔，
    /// 接收按「预期响应长度」精确收满后做 CRC 校验。
    /// </summary>
    public sealed class ModbusRtuClient : IDisposable
    {
        private readonly string _portName;
        private readonly int _baudRate;
        private readonly Parity _parity;
        private readonly int _dataBits;
        private readonly StopBits _stopBits;
        private readonly int _timeoutMs;
        private readonly object _ioLock = new object();
        private SerialPort _port;
        private DateTime _lastFrameEndUtc = DateTime.MinValue;

        /// <summary>构造。默认 9600,8,N,1；unitId 为本客户端默认访问的从机地址；timeoutMs 为一帧响应的总超时。
        /// ⚠ 帧口径偏离（有意保留，现场兼容）：MODBUS over Serial Line V1.02 §2.5.1 要求 RTU 字符帧为
        /// 11 位（8E1 或 8N2：1 起始 + 8 数据 + 1 校验/停止 + 1 停止）；本实现默认 8N1 = 10 位/字符，
        /// 是与规范的偏离——不改为兼容现场大量固定 8N1 的存量设备。t3.5 帧间隔恒按 11 位/字符计算
        ///（CalcT35Milliseconds），对 8N1 实际 10 位而言间隔偏长（保守），方向安全、不产生违例。</summary>
        public ModbusRtuClient(string portName, int baudRate = 9600,
            Parity parity = Parity.None, int dataBits = 8, StopBits stopBits = StopBits.One,
            byte unitId = 1, int timeoutMs = 1000)
        {
            if (string.IsNullOrEmpty(portName)) throw new ArgumentNullException("portName");
            if (baudRate <= 0) throw new ArgumentOutOfRangeException("baudRate");
            if (dataBits < 5 || dataBits > 8) throw new ArgumentOutOfRangeException("dataBits");
            if (timeoutMs <= 0) throw new ArgumentOutOfRangeException("timeoutMs");
            _portName = portName;
            _baudRate = baudRate;
            _parity = parity;
            _dataBits = dataBits;
            _stopBits = stopBits;
            UnitId = unitId;
            _timeoutMs = timeoutMs;
        }

        /// <summary>默认从机地址（0 为广播，广播帧无响应，勿用于读）。</summary>
        public byte UnitId { get; set; }

        /// <summary>串口是否已打开。</summary>
        public bool IsOpen
        {
            get { lock (_ioLock) { return _port != null && _port.IsOpen; } }
        }

        /// <summary>
        /// t3.5 帧间隔（毫秒）：≤19200bps 时按 3.5 个字符时间计算（每字符 11 位：1 起始 + 8 数据 + 1 校验/停止 + 1 停止），
        /// 9600bps 下 ≈ 4.01ms；&gt;19200bps 按规范用固定 1.75ms。
        /// spec_ref: MODBUS over Serial Line V1.02 §2.5.1.1（t3.5 定义与 &gt;19200bps 固定值）, 待与 modbus.json 对账。
        /// </summary>
        public static double CalcT35Milliseconds(int baudRate)
        {
            if (baudRate <= 0) throw new ArgumentOutOfRangeException("baudRate");
            if (baudRate > 19200) return 1.75;
            return 3.5 * 11.0 * 1000.0 / baudRate;
        }

        // ---- RTU 广播（地址 0）常量与语义 ------------------------------------
        //
        // spec_ref(广播语义): modbus.json limits_and_timeouts.broadcast_semantics ——
        //   MODBUS over Serial Line V1.02 §2.1 p7: "No response is returned to broadcast
        //   requests sent by the master. The broadcast requests are necessarily writing
        //   commands. All devices must accept the broadcast for writing function. The
        //   address 0 is reserved to identify a broadcast exchange."（地址 0、仅写、无响应）。
        //
        // spec_ref(turnaround delay): modbus.json limits_and_timeouts.
        //   serial_turnaround_delay_after_broadcast ——
        //   MODBUS over Serial Line V1.02 §2.4.1 p10: "When a broadcast request is sent on
        //   the serial bus, no response is returned from the slaves. Nevertheless a delay is
        //   respected by the Master in order to allow any slave to process the current
        //   request before sending a new one."；modbus.json 条目值「广播后无响应，但主站须
        //   等待一段延迟（典型 100-200ms）再发新请求」。
        //   —— 以下三个常量 2026-10-21 自该 modbus.json 条目抄录（黄金测试钉值）。

        /// <summary>广播后 turnaround delay 区间下限 = 100ms（modbus.json：典型 100-200ms）。
        /// spec_ref: Serial Line V1.02 §2.4.1 p10, 已对账（2026-10-21）。</summary>
        public const int BroadcastTurnaroundDelayMinMs = 100;

        /// <summary>广播后 turnaround delay 区间上限 = 200ms（modbus.json：典型 100-200ms）。
        /// spec_ref: Serial Line V1.02 §2.4.1 p10, 已对账（2026-10-21）。</summary>
        public const int BroadcastTurnaroundDelayMaxMs = 200;

        /// <summary>广播后 turnaround delay 实际取值 = 150ms（规范建议区间 100-200ms 的中值；
        /// ≫ t3.5≈4ms@9600bps，取值后帧间隔天然满足）。
        /// spec_ref: modbus.json limits_and_timeouts.serial_turnaround_delay_after_broadcast
        /// （MODBUS over Serial Line V1.02 §2.4.1 p10）。已对账（2026-10-21）。</summary>
        public const int BroadcastTurnaroundDelayMs = 150;

        /// <summary>打开串口（幂等；参数在构造时给定）。</summary>
        public void Open()
        {
            lock (_ioLock)
            {
                if (_port != null && _port.IsOpen) return;
                var port = new SerialPort(_portName, _baudRate, _parity, _dataBits, _stopBits);
                try
                {
                    port.ReadTimeout = Math.Max(1, _timeoutMs);
                    port.WriteTimeout = Math.Max(1, _timeoutMs);
                    port.Open();
                }
                catch
                {
                    port.Dispose();     // 打开失败必须释放句柄（串口被占用时尤其要紧）
                    throw;
                }
                _port = port;
            }
        }

        /// <summary>关闭串口（幂等）。</summary>
        public void Close()
        {
            lock (_ioLock)
            {
                if (_port != null) { try { _port.Close(); } catch { } _port.Dispose(); _port = null; }
            }
        }

        /// <summary>释放资源（等价 Close）。</summary>
        public void Dispose() { Close(); }

        /// <summary>执行一次完整事务：t3.5 间隔 → 帧封装+CRC → 发送 → 按预期长度收帧 → CRC 校验 → 返回响应 PDU。</summary>
        private byte[] ExecuteTransaction(byte unitAddress, byte[] requestPdu, ushort quantity)
        {
            lock (_ioLock)
            {
                if (_port == null || !_port.IsOpen)
                    throw new InvalidOperationException("Modbus RTU 串口未打开，请先调用 Open()。");
                byte requestFc = requestPdu[0];
                byte[] frame = ModbusRtuFrame.BuildFrame(unitAddress, requestPdu);

                // —— 发送侧：与上一帧结束保持 t3.5 帧间隔 ——
                double t35 = CalcT35Milliseconds(_baudRate);
                double remainMs = t35 - (DateTime.UtcNow - _lastFrameEndUtc).TotalMilliseconds;
                if (remainMs > 0) Thread.Sleep((int)Math.Ceiling(remainMs));
                try
                {
                    _port.DiscardInBuffer();            // 丢掉陈旧字节，避免串帧
                    _port.Write(frame, 0, frame.Length);
                }
                catch (Exception ex)
                {
                    throw new IOException("Modbus RTU 发送失败：" + ex.Message, ex);
                }

                // —— 接收侧：逐字节收，总 deadline = timeoutMs ——
                DateTime deadline = DateTime.UtcNow.AddMilliseconds(_timeoutMs);
                byte head0 = ReadByteBefore(deadline);  // 地址
                byte head1 = ReadByteBefore(deadline);  // 功能码
                if (head0 != unitAddress)
                    throw new InvalidDataException(string.Format(CultureInfo.InvariantCulture,
                        "从机地址不匹配：期望 {0}，收到 {1}", unitAddress, head0));
                bool isException = (head1 & ModbusConst.ExceptionFlag) != 0;
                if (!isException && head1 != requestFc)
                    throw new InvalidDataException(string.Format(CultureInfo.InvariantCulture,
                        "响应功能码不匹配：期望 0x{0:X2}，实际 0x{1:X2}", requestFc, head1));
                // 剩余长度：异常帧 = 异常码(1)+CRC(2)；正常帧按功能码与请求数量推算
                int remaining = isException ? 3 : GetRemainingResponseLength(requestFc, quantity);
                byte[] buf = new byte[2 + remaining];
                buf[0] = head0; buf[1] = head1;
                for (int i = 2; i < buf.Length; i++)
                    buf[i] = ReadByteBefore(deadline);
                _lastFrameEndUtc = DateTime.UtcNow;

                byte unitAddr; byte[] pdu;
                if (!ModbusRtuFrame.TryParseFrame(buf, buf.Length, out unitAddr, out pdu))
                    throw new InvalidDataException("RTU 帧 CRC 校验失败（响应帧：" + BitConverter.ToString(buf) + "）");
                return pdu;
            }
        }

        /// <summary>带总 deadline 的单字节读取；到点抛 TimeoutException。</summary>
        private byte ReadByteBefore(DateTime deadline)
        {
            double remainMs = (deadline - DateTime.UtcNow).TotalMilliseconds;
            if (remainMs <= 0)
                throw new TimeoutException("Modbus RTU 等待响应超时（" + _timeoutMs + " ms）");
            _port.ReadTimeout = (int)Math.Max(1, remainMs);
            try
            {
                int b = _port.ReadByte();
                if (b < 0) throw new IOException("串口意外返回 EOF");
                return (byte)b;
            }
            catch (TimeoutException) { throw; }
            catch (Exception ex) { throw new IOException("Modbus RTU 接收失败：" + ex.Message, ex); }
        }

        /// <summary>
        /// 响应帧在 地址+功能码 之后的剩余字节数（static 纯函数，可单测）。
        /// FC1/2: 字节数(1)+位数据+CRC(2)；FC3/4: 寄存器数据(2*数量)+CRC(2)；FC5/6/15/16 回显：地址(2)+值/数量(2)+CRC(2)。
        /// </summary>
        public static int GetRemainingResponseLength(byte requestFunctionCode, ushort quantity)
        {
            switch (requestFunctionCode)
            {
                case ModbusFunctionCode.ReadCoils:
                case ModbusFunctionCode.ReadDiscreteInputs:
                    return 1 + (quantity + 7) / 8 + 2;
                case ModbusFunctionCode.ReadHoldingRegisters:
                case ModbusFunctionCode.ReadInputRegisters:
                    return 1 + quantity * 2 + 2;
                case ModbusFunctionCode.WriteSingleCoil:
                case ModbusFunctionCode.WriteSingleRegister:
                case ModbusFunctionCode.WriteMultipleCoils:
                case ModbusFunctionCode.WriteMultipleRegisters:
                    return 4 + 2;
                default:
                    throw new ArgumentOutOfRangeException("requestFunctionCode", "不支持的功能码 0x" + requestFunctionCode.ToString("X2"));
            }
        }

        // ---- 广播（地址 0，NoResponse）--------------------------------------
        // spec_ref: modbus.json limits_and_timeouts.broadcast_semantics
        //   （Serial Line V1.02 §2.1 p7：广播无响应、必然是写命令、地址 0）；
        //   turnaround delay 数值与 spec_ref 见上方常量注释（§2.4.1 p10，典型 100-200ms）。

        /// <summary>
        /// 广播核心方法：组帧（从机地址 + PDU + CRC16）→ 发送 → <b>不接收任何响应</b> →
        /// 仅等待广播后 turnaround delay（<see cref="BroadcastTurnaroundDelayMs"/> = 150ms，
        /// 区间 100-200ms 抄录自 modbus.json limits_and_timeouts.
        /// serial_turnaround_delay_after_broadcast；spec_ref: Serial Line V1.02 §2.4.1 p10）。
        ///
        /// ⚠ 广播语义（spec_ref: Serial Line V1.02 §2.1 p7，经 modbus.json
        /// limits_and_timeouts.broadcast_semantics 对账）：
        /// ① 从站对广播一概<b>不回帧</b>——写是否被执行、是否越界、是否异常统统<b>错误不可知</b>；
        /// ② 广播请求必然是<b>写命令</b>（FC5/6/15/16），读命令广播在参数校验即被拒绝；
        /// ③ 方法返回仅代表「帧已上总线并等完 turnaround delay」，<b>不代表任何从站已执行</b>
        /// ——仅适用于广播安全命令（统一清零/统一点动等）；需确认结果请用单播写 + 回读。
        /// </summary>
        /// <param name="slaveAddress">必须为广播地址 0（<see cref="ModbusConst.BroadcastAddress"/>）。</param>
        /// <param name="pdu">完整请求 PDU（功能码 + 参数），须为写命令 FC5/6/15/16。</param>
        public void SendBroadcast(byte slaveAddress, byte[] pdu)
        {
            if (pdu == null) throw new ArgumentNullException("pdu");
            if (slaveAddress != ModbusConst.BroadcastAddress)
                throw new ArgumentException(string.Format(CultureInfo.InvariantCulture,
                    "广播地址必须为 0（收到 {0}）。spec_ref: Serial Line V1.02 §2.1：地址 0 保留为广播",
                    slaveAddress), "slaveAddress");
            byte fc = pdu.Length > 0 ? pdu[0] : (byte)0;
            bool isBroadcastWrite =
                fc == ModbusFunctionCode.WriteSingleCoil ||
                fc == ModbusFunctionCode.WriteSingleRegister ||
                fc == ModbusFunctionCode.WriteMultipleCoils ||
                fc == ModbusFunctionCode.WriteMultipleRegisters;
            if (!isBroadcastWrite)
                throw new ArgumentException(string.Format(CultureInfo.InvariantCulture,
                    "广播请求必须是写命令 FC5/6/15/16（收到 0x{0:X2}）。spec_ref: Serial Line V1.02 §2.1：广播必然是写命令", fc), "pdu");

            lock (_ioLock)
            {
                if (_port == null || !_port.IsOpen)
                    throw new InvalidOperationException("Modbus RTU 串口未打开，请先调用 Open()。");
                byte[] frame = ModbusRtuFrame.BuildFrame(slaveAddress, pdu);
                double t35 = CalcT35Milliseconds(_baudRate);
                double remainMs = t35 - (DateTime.UtcNow - _lastFrameEndUtc).TotalMilliseconds;
                if (remainMs > 0) Thread.Sleep((int)Math.Ceiling(remainMs));
                try
                {
                    _port.DiscardInBuffer();        // 广播虽无响应，仍丢弃陈旧字节防串帧
                    _port.Write(frame, 0, frame.Length);
                }
                catch (Exception ex)
                {
                    throw new IOException("Modbus RTU 广播发送失败：" + ex.Message, ex);
                }
                _lastFrameEndUtc = DateTime.UtcNow;
                // —— 广播语义核心：不接收任何响应，仅等 turnaround delay ——
                // （150ms ≫ t3.5≈4ms@9600bps，下一帧的 t3.5 帧间隔因此天然满足）
                Thread.Sleep(BroadcastTurnaroundDelayMs);
            }
        }

        // ---- 公开读写方法（RTU 用实例 UnitId；广播地址 0 只该用于写）----

        /// <summary>FC1 读线圈：1..2000 个。返回 bool[]（数量恒等于 quantity，尾部填充位已裁剪）。</summary>
        public bool[] ReadCoils(ushort startAddress, ushort quantity)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadCoils, startAddress, quantity), quantity);
            ModbusPdu.EnsureNotException(pdu);
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadCoils);
            ModbusPdu.EnsureReadCount(bits.Length, quantity, ModbusFunctionCode.ReadCoils);   // P1-2：短读防护
            if (bits.Length > quantity) Array.Resize(ref bits, quantity);   // 契约：要多少给多少
            return bits;
        }

        /// <summary>FC2 读离散输入：1..2000 个（数量恒等于 quantity）。</summary>
        public bool[] ReadDiscreteInputs(ushort startAddress, ushort quantity)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadDiscreteInputs, startAddress, quantity), quantity);
            ModbusPdu.EnsureNotException(pdu);
            bool[] bits = ModbusPdu.ParseBitResponse(pdu, ModbusFunctionCode.ReadDiscreteInputs);
            ModbusPdu.EnsureReadCount(bits.Length, quantity, ModbusFunctionCode.ReadDiscreteInputs);   // P1-2：短读防护
            if (bits.Length > quantity) Array.Resize(ref bits, quantity);
            return bits;
        }

        /// <summary>FC3 读保持寄存器：1..125 个。</summary>
        public ushort[] ReadHoldingRegisters(ushort startAddress, ushort quantity)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadHoldingRegisters, startAddress, quantity), quantity);
            ModbusPdu.EnsureNotException(pdu);
            ushort[] regs = ModbusPdu.ParseRegisterResponse(pdu, ModbusFunctionCode.ReadHoldingRegisters);
            ModbusPdu.EnsureReadCount(regs.Length, quantity, ModbusFunctionCode.ReadHoldingRegisters);   // P1-2：短读防护
            return regs;
        }

        /// <summary>FC4 读输入寄存器：1..125 个。</summary>
        public ushort[] ReadInputRegisters(ushort startAddress, ushort quantity)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildReadRequest(ModbusFunctionCode.ReadInputRegisters, startAddress, quantity), quantity);
            ModbusPdu.EnsureNotException(pdu);
            ushort[] regs = ModbusPdu.ParseRegisterResponse(pdu, ModbusFunctionCode.ReadInputRegisters);
            ModbusPdu.EnsureReadCount(regs.Length, quantity, ModbusFunctionCode.ReadInputRegisters);   // P1-2：短读防护
            return regs;
        }

        /// <summary>FC5 写单线圈（单播语义：等响应 + 校验从机回显）。
        /// 广播（unitId=0）"发送即返回"请改用 <see cref="WriteSingleCoilNoResponse"/>；
        /// 本方法若以广播地址调用会一直等到响应超时（广播无响应是规范语义）。</summary>
        public void WriteSingleCoil(ushort address, bool value)
        {
            ushort coil = value ? ModbusConst.CoilOn : ModbusConst.CoilOff;
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildWriteSingleCoilRequest(address, value), 1);
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteSingleCoil, address, coil);
        }

        /// <summary>FC6 写单寄存器。</summary>
        public void WriteSingleRegister(ushort address, ushort value)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildWriteSingleRegisterRequest(address, value), 1);
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteSingleRegister, address, value);
        }

        /// <summary>FC15 写多线圈：1..1968 个。</summary>
        public void WriteMultipleCoils(ushort address, bool[] values)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildWriteMultipleCoilsRequest(address, values), (ushort)values.Length);
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteMultipleCoils, address, (ushort)values.Length);
        }

        /// <summary>FC16 写多寄存器：1..123 个。</summary>
        public void WriteMultipleRegisters(ushort address, ushort[] values)
        {
            byte[] pdu = ExecuteTransaction(UnitId, ModbusPdu.BuildWriteMultipleRegistersRequest(address, values), (ushort)values.Length);
            ModbusPdu.EnsureNotException(pdu);
            ModbusPdu.VerifyEchoResponse(pdu, ModbusFunctionCode.WriteMultipleRegisters, address, (ushort)values.Length);
        }

        // ---- 广播写 NoResponse 变体（unitId 恒 = 0 广播地址）----
        //
        // 共同语义（详见 SendBroadcast XML 注释，spec_ref: Serial Line V1.02 §2.1/§2.4.1）：
        //   - 以广播地址 0 组帧发送，不接收任何响应，发送后仅等 turnaround delay
        //     （BroadcastTurnaroundDelayMs = 150ms，modbus.json：典型 100-200ms 取中值）；
        //   - ⚠ 广播无响应 = 错误不可知（规范语义如此）：是否执行、是否越界、是否异常
        //     均无法得知，方法返回 ≠ 执行成功；
        //   - ⚠ 仅适用于广播安全命令（统一清零、统一点动等无副作用的批量写）；
        //     需要确认结果时请用单播写 + 回读。

        /// <summary>FC5 写单线圈【广播 NoResponse】：unitId=0，无响应、错误不可知，
        /// 仅适用于广播安全命令；发送后仅等 turnaround delay。</summary>
        public void WriteSingleCoilNoResponse(ushort address, bool value)
        {
            SendBroadcast(ModbusConst.BroadcastAddress, ModbusPdu.BuildWriteSingleCoilRequest(address, value));
        }

        /// <summary>FC15 写多线圈【广播 NoResponse】：unitId=0，无响应、错误不可知，
        /// 仅适用于广播安全命令；发送后仅等 turnaround delay。</summary>
        public void WriteMultipleCoilsNoResponse(ushort address, bool[] values)
        {
            SendBroadcast(ModbusConst.BroadcastAddress, ModbusPdu.BuildWriteMultipleCoilsRequest(address, values));
        }

        /// <summary>FC6 写单寄存器【广播 NoResponse】：unitId=0，无响应、错误不可知，
        /// 仅适用于广播安全命令；发送后仅等 turnaround delay。</summary>
        public void WriteSingleRegisterNoResponse(ushort address, ushort value)
        {
            SendBroadcast(ModbusConst.BroadcastAddress, ModbusPdu.BuildWriteSingleRegisterRequest(address, value));
        }

        /// <summary>FC16 写多寄存器【广播 NoResponse】：unitId=0，无响应、错误不可知，
        /// 仅适用于广播安全命令；发送后仅等 turnaround delay。</summary>
        public void WriteMultipleRegistersNoResponse(ushort address, ushort[] values)
        {
            SendBroadcast(ModbusConst.BroadcastAddress, ModbusPdu.BuildWriteMultipleRegistersRequest(address, values));
        }
    }
}
