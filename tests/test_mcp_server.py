"""MCP stdio 服务端真协议回归测试。

**起一个真子进程，按 JSON-RPC 对话**，而不是 import 一下就算过。

为什么值得单独起一个文件：
    MCP 走 stdio，协议层必须 UTF-8 JSON。中文 Windows 的 `sys.stdout.encoding` 是
    cp936(GBK) —— 服务端只要沿用控制台编码，客户端按 UTF-8 解就会崩。
    2026-10-20 实测踩过：initialize 能回，紧接着 tools/list 就
    `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb2`，
    因为工具描述里有中文。这类 bug 不开子进程测不出来。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _Client:
    """最小 MCP 客户端：行分隔 JSON-RPC。"""

    def __init__(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mcopilot.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), env=env, text=True, encoding="utf-8", bufsize=1,
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line, "服务端关闭了 stdout"
        return json.loads(line)          # ← 这里就是 UTF-8 解码点

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


@pytest.fixture()
def client():
    c = _Client()
    try:
        yield c
    finally:
        c.close()


def test_握手与工具清单(client: _Client):
    init = client.call("initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}})
    assert init["result"]["serverInfo"]["name"] == "mcopilot"
    client.notify("notifications/initialized")

    tools = client.call("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "工具名重复"
    assert len(names) >= 14


def test_中文工具描述能正确编码(client: _Client):
    """这一条专门盯 UTF-8：描述里全是中文，GBK 输出一律解码失败。"""
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    tools = client.call("tools/list")["result"]["tools"]
    for t in tools:
        assert any("一" <= ch <= "鿿" for ch in t["description"]), \
            f"{t['name']} 的描述里没有中文，测不出编码问题"


def test_三个电子凸轮工具都在(client: _Client):
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    names = {t["name"] for t in client.call("tools/list")["result"]["tools"]}
    assert {"cam_check", "cam_plan", "cam_caps"} <= names


def test_cam_caps能真调出结果(client: _Client):
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    r = client.call("tools/call", {"name": "cam_caps", "arguments": {}})
    assert not r["result"]["isError"]
    text = r["result"]["content"][0]["text"]
    for brand in ("雷赛", "正运动", "固高"):
        assert brand in text
    assert "dmc_cam_table_unit" in text


def test_cam_check能检出样例表的速度阶跃(client: _Client):
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    r = client.call("tools/call", {"name": "cam_check", "arguments": {
        "table_path": "samples/cam/pick_place_cam.csv",
        "master_velocity": 360, "master_accel": 200,
        "slave_velocity_max": 300, "slave_accel_max": 2000,
        "slave_travel_mm": 120, "master_unit": "deg",
    }})
    assert not r["result"]["isError"]
    text = r["result"]["content"][0]["text"]
    assert "速度阶跃" in text
    assert "72" in text          # 样例表第 7 段接缝的阶跃速度


def test_cam_plan生成的表行程精确(client: _Client):
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    r = client.call("tools/call", {"name": "cam_plan", "arguments": {
        "master_travel": 360, "slave_travel_mm": 8, "segments": 4,
        "master_velocity": 360, "slave_velocity_max": 300, "slave_accel_max": 2000,
    }})
    assert not r["result"]["isError"]
    text = r["result"]["content"][0]["text"]
    assert "8.0000" in text


def test_工具出错时走isError且服务端不崩(client: _Client):
    """MCP 规范：工具执行错误走 result.isError，不是 JSON-RPC error。"""
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    r = client.call("tools/call", {"name": "no_such_tool", "arguments": {}})
    assert r["result"]["isError"] is True
    # 出错之后还得能接着对话
    r2 = client.call("tools/list")
    assert "result" in r2


def test_未知方法返回JSONRPC错误(client: _Client):
    client.call("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    client.notify("notifications/initialized")
    r = client.call("no/such/method")
    assert r["error"]["code"] == -32601
