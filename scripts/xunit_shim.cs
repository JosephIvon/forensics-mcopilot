// 仅用于**编译期**的 xUnit 最小替身。
// 目的：让 MotionContractTests.cs 在没有 NuGet 包、没有网络的机器上也能通过编译检查
// （契约测试里的物理断言要真机才跑得起来，但**语法错误不能留到现场才发现**）。
// 这个文件不会进入任何交付产物，也不参与运行。

using System;

namespace Xunit
{
    [AttributeUsage(AttributeTargets.Method)]
    public sealed class FactAttribute : Attribute { }

    public static class Assert
    {
        public static void Equal(double expected, double actual, int precision) { }
        public static void Equal(int expected, int actual) { }
        public static void True(bool condition) { }
        public static void True(bool condition, string message) { }
        public static void False(bool condition) { }
        public static void IsType<T>(object obj) { }
        public static T Throws<T>(Action action) where T : Exception { return null; }
    }

    public static class Record
    {
        public static Exception Exception(Action action) { return null; }
    }
}
