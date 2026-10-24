// ============================================================================
//  SLMP TCP 客户端（3E 帧·二进制码）—— P2 第二协议交付。
//  零第三方依赖（System.Net.Sockets），C# 5 兼容（老 csc 可编译）。
//  帧字段与软元件码取自 knowledge/protocols/slmp.json（FX5 SLMP 手册 JY997D54401 机械提取）。
//
//  诚实边界：
//  - 副头部值（0x5000/0xD000）在手册中位于消息图解（pypdf 列打散），slmp.json 中为
//    judgment + needs:manual_check——本实现与自建契约桩互洽，真机核对前不视为已验证。
//  - 结束代码（End code）值表不在 FX5 SLMP 手册文字层，本客户端只区分 0=正常/非 0=错误
//    并透传原始码，不编造翻译表（TODO[需实测]: 对真机核对错误码语义，MC Protocol 手册）。
// ============================================================================
using System;
using System.Globalization;
using System.IO;
using System.Net.Sockets;

namespace Mcopilot.Protocols.Slmp
{
    /// <summary>软元件二进制码（slmp.json device_code 条目）。</summary>
    public static class SlmpDevice
    {
        public const byte DataRegisterD = 0xA8;   // slmp.json: D* A8H (A800H)
        public const byte WordDeviceW = 0xB4;     // slmp.json: W* B4H (B400H)
        public const byte InputX = 0x9C;          // slmp.json: X* 9CH (9C00H)
        public const byte InternalRelayM = 0x90;  // slmp.json: M* 90H (9000H)
    }

    /// <summary>指令与子指令（slmp.json command 条目）。</summary>
    public static class SlmpCommand
    {
        public const ushort DeviceReadBatch = 0x0401;    // slmp.json: SLMP-CMD-0401
        public const ushort DeviceWriteBatch = 0x1401;   // slmp.json: SLMP-CMD-1401
        public const ushort SubWordUnits = 0x0000;       // 字单位
        public const ushort SubBitUnits = 0x0001;        // 位单位
        public const int MaxWordPointsBinary = 960;      // slmp.json: BIN 960 words (15360 points)
    }

    /// <summary>从机错误响应：EndCode 为原始结束代码（0x0000=正常，非 0 语义待真机核对）。</summary>
    public class SlmpException : Exception
    {
        public ushort EndCode { get; private set; }

        public SlmpException(ushort endCode)
            : base("SLMP 结束代码 0x" + endCode.ToString("X4", CultureInfo.InvariantCulture)
                   + "（非 0=异常；语义核对 TODO[需实测]，本实现不编造翻译）")
        {
            EndCode = endCode;
        }
    }

    public sealed class SlmpTcpClient : IDisposable
    {
        private readonly string _host;
        private readonly int _port;
        private readonly int _connectTimeoutMs;
        private TcpClient _tcp;
        private NetworkStream _stream;
        private readonly object _ioLock = new object();

        public bool IsConnected
        {
            get { return _tcp != null && _tcp.Connected; }
        }

        /// <summary>构造。端口默认 SLMP(3E/4C) 的 1027……按现场参数可改。</summary>
        public SlmpTcpClient(string host, int port = 1027, int connectTimeoutMs = 3000)
        {
            if (string.IsNullOrEmpty(host)) throw new ArgumentNullException("host");
            _host = host;
            _port = port;
            _connectTimeoutMs = connectTimeoutMs;
        }

        public void Connect()
        {
            lock (_ioLock)
            {
                if (IsConnected) return;
                _tcp = new TcpClient();
                var ar = _tcp.BeginConnect(_host, _port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(_connectTimeoutMs))
                {
                    _tcp.Close(); _tcp = null;
                    throw new IOException("SLMP 连接超时: " + _host + ":" + _port);
                }
                _tcp.EndConnect(ar);
                _stream = _tcp.GetStream();
                _stream.ReadTimeout = _connectTimeoutMs;
                _stream.WriteTimeout = _connectTimeoutMs;
            }
        }

        public void Close()
        {
            lock (_ioLock)
            {
                if (_stream != null) { try { _stream.Close(); } catch { } _stream = null; }
                if (_tcp != null) { try { _tcp.Close(); } catch { } _tcp = null; }
            }
        }

        public void Dispose() { Close(); }

        /// <summary>批量读字软元件（0401H/0000H，BIN 上限 960 点）。返回大端已解的 ushort[]。</summary>
        public ushort[] ReadWordDevices(byte deviceCode, int startDeviceNumber, ushort count)
        {
            if (count < 1 || count > SlmpCommand.MaxWordPointsBinary)
                throw new ArgumentOutOfRangeException("count",
                    "字软元件批量读数量必须在 1.." + SlmpCommand.MaxWordPointsBinary + "（BIN 上限）");
            byte[] req = BuildRequest(0x0000, w => w
                .U16(SlmpCommand.DeviceReadBatch)
                .U16(SlmpCommand.SubWordUnits)
                .U8(deviceCode)
                .U24(startDeviceNumber)
                .U16(count));
            byte[] data = TransactRaw(req);
            if (data.Length != count * 2)
                throw new IOException("SLMP 响应数据长度与点数不符: " + data.Length + "B / " + count + " 点");
            ushort[] r = new ushort[count];
            for (int i = 0; i < count; i++)
                r[i] = (ushort)(data[i * 2] | (data[i * 2 + 1] << 8));
            return r;
        }

        /// <summary>批量写字软元件（1401H/0000H）。</summary>
        public void WriteWordDevices(byte deviceCode, int startDeviceNumber, ushort[] values)
        {
            if (values.Length < 1 || values.Length > SlmpCommand.MaxWordPointsBinary)
                throw new ArgumentOutOfRangeException("values",
                    "字软元件批量写数量必须在 1.." + SlmpCommand.MaxWordPointsBinary + "（BIN 上限）");
            byte[] req = BuildRequest(0x0000, w => w
                .U16(SlmpCommand.DeviceWriteBatch)
                .U16(SlmpCommand.SubWordUnits)
                .U8(deviceCode)
                .U24(startDeviceNumber)
                .U16((ushort)values.Length)
                .Words(values));
            TransactRaw(req);   // 正常响应无数据，仅核对结束代码
        }

        // ---- 3E 帧：[Subheader 0x5000][Net 0][PC 0xFF][I/O FF03][Multidrop 0][Len][Timer][PDU] ----

        private delegate void Writer(ByteArray w);

        private byte[] BuildRequest(ushort monitorTimer, Writer body)
        {
            ByteArray w = new ByteArray();
            w.U16(0x5000);      // 副头部（judgment 值，见文件头诚实边界）
            w.U8(0x00);         // 网络号
            w.U8(0xFF);         // PC 号
            w.U16(0x03FF);      // 模块 I/O
            w.U8(0x00);         // 多站
            w.U16(0x0000);      // 数据长度占位（头 9 字节之后的部分，末尾回填）
            w.U16(monitorTimer);
            body(w);
            byte[] frame = w.ToArray();
            int len = frame.Length - 9;   // 数据长度 = 监视定时器 + 请求数据（头 9 字节之后）
            frame[7] = (byte)(len & 0xFF);
            frame[8] = (byte)(len >> 8);
            return frame;
        }

        /// <summary>低层事务：发整帧（BuildRequest 产物）、按副头部 0xD000 分支、返回数据区或抛 SlmpException。</summary>
        public byte[] TransactRaw(byte[] frame)
        {
            if (!IsConnected) throw new InvalidOperationException("SLMP 未连接，请先 Connect()");
            lock (_ioLock)
            {
                _stream.Write(frame, 0, frame.Length);
                byte[] head = ReadExact(9);
                if (head[0] != 0x00 || head[1] != 0xD0)
                    throw new IOException("SLMP 响应副头部异常: " + head[1].ToString("X2") + head[0].ToString("X2"));
                int len = head[7] | (head[8] << 8);
                byte[] rest = ReadExact(len - 2);
                ushort endCode = (ushort)(rest[0] | (rest[1] << 8));
                if (endCode != 0x0000) throw new SlmpException(endCode);
                byte[] data = new byte[rest.Length - 2];
                Array.Copy(rest, 2, data, 0, data.Length);
                return data;
            }
        }

        private byte[] ReadExact(int n)
        {
            byte[] buf = new byte[n];
            int off = 0;
            while (off < n)
            {
                int got = _stream.Read(buf, off, n - off);
                if (got <= 0) throw new IOException("SLMP 对端关闭连接");
                off += got;
            }
            return buf;
        }
    }

    /// <summary>小端字节组装器（SLMP 二进制码为小端）。</summary>
    internal class ByteArray
    {
        private readonly System.Collections.Generic.List<byte> _b = new System.Collections.Generic.List<byte>();

        public ByteArray U8(int v) { _b.Add((byte)v); return this; }

        public ByteArray U16(int v)
        {
            _b.Add((byte)(v & 0xFF));
            _b.Add((byte)(v >> 8));
            return this;
        }

        public ByteArray U24(int v)
        {
            _b.Add((byte)(v & 0xFF));
            _b.Add((byte)((v >> 8) & 0xFF));
            _b.Add((byte)((v >> 16) & 0xFF));
            return this;
        }

        public ByteArray Words(ushort[] vals)
        {
            foreach (ushort v in vals) U16(v);
            return this;
        }

        public byte[] ToArray() { return _b.ToArray(); }
    }
}
