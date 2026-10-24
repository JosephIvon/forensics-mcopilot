// 样例：故意包含典型实时运动上位机缺陷的代码，供 mcopilot review 演示与自检。
// 缺陷清单：RT-001 / RT-002 / RT-003 / RT-004 / RT-005 / RT-006 / RT-007 / RT-008
using System;
using System.Threading;
using System.Threading.Tasks;
using Motion;

namespace LegacyMotionApp
{
    public class PlaceController
    {
        private const string VisionServerIp = "192.168.1.50";
        private readonly IMotionController _card;
        private bool _isRunning;
        private static double _sharedOffset;

        public PlaceController(IMotionController card)
        {
            _card = card;
        }

        /// <summary>贴装流程</summary>
        public void RunPlace()
        {
            _card.Open();
            _card.Enable(0, true);
            _card.MoveAbs(0, 120.0, MotionProfile.Default);

            // RT-001 + RT-003：阻塞等待 + 无超时死循环
            while (!_card.IsMotionDone(0))
            {
                Thread.Sleep(10);
            }

            // RT-006：魔法数字
            double target = 45.0;
            _card.MoveAbs(1, target, MotionProfile.Default);

            // RT-004：把 mm 直接传给了以脉冲为单位的接口（漏乘脉冲当量）
            DmcBoard.dmc_pmove(0, 1, target, 1);

            try
            {
                SendToVision(VisionServerIp);
            }
            catch (Exception)
            {
                // RT-002：空 catch，异常被完全吞掉
            }

            // RT-005：硬编码 IP
            var client = new System.Net.Sockets.TcpClient("192.168.1.88", 6000);

            // RT-007：浮点等值比较
            if (_card.GetPositionMm(0) == 120.0)
            {
                _sharedOffset = 0.0;
            }
        }

        // RT-008：同步阻塞等待异步结果
        public async Task<double> ReadPositionAsync(int axis)
        {
            var t = Task.Run(() => _card.GetPositionMm(axis));
            return await t;
        }

        private void SendToVision(string ip)
        {
            // 模拟一次会失败的通信
            if (_sharedOffset < 0)
            {
                throw new InvalidOperationException("vision failure");
            }
        }
    }

    /// <summary>旧版雷赛 P/Invoke（此处的声明本身就演示了手写 P/Invoke 的典型风险）</summary>
    internal static class DmcBoard
    {
        [System.Runtime.InteropServices.DllImport("dmc.dll")]
        public static extern short dmc_pmove(short cardNo, short axis, int dist, short posiMode);
    }
}
