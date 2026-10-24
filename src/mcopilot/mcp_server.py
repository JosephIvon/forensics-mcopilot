"""MCP stdio 服务端：把同一套智能体暴露成 MCP 工具，可直接挂进 IDE / 桌面 Agent。

    python -m mcopilot.mcp_server

实现的是 MCP 的最小可用子集（initialize / tools/list / tools/call / ping），
零第三方依赖，走 stdio 的行分隔 JSON-RPC。

为什么要有这一层：CLI 适合工程师手动跑，**MCP 让工具出现在他们每天用的 AI 里**——
问一句「这段日志为什么定位老偏」，Agent 就能直接调用取证工具，而不是让工程师
复制粘贴日志再手动跑脚本。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .agents import adapter_gen, cam_lab, forensics, motion_lab, requirements, review, servo, spc, threshold_lab
from .core.util import DEFAULT_OUT_DIR, ensure_out_dir

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcopilot", "version": "1.0.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "requirements_map",
        "description": "拆解运动控制上位机软件工程的工业需求基线，输出每条需求的 AI 承担度、"
                       "判定（高替代/增强/人主导）、必须由人负责的部分，以及工具覆盖审计。",
        "inputSchema": {"type": "object", "properties": {"out_dir": {"type": "string"}}, "required": []},
    },
    {
        "name": "motion_plan",
        "description": "计算 7 段 jerk 受限 S 曲线：总运动时间、峰值速度/加速度、匀速段、"
                       "制动距离，并可估算伺服带宽下的最大跟随误差是否超容差。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "distance_mm": {"type": "number", "description": "位移 mm，负数为反方向"},
                "max_velocity_mm_s": {"type": "number"},
                "max_accel_mm_s2": {"type": "number"},
                "max_jerk_mm_s3": {"type": "number"},
                "servo_freq_hz": {"type": "number", "description": "伺服自然频率，用于跟随误差估算"},
                "damping_ratio": {"type": "number"},
                "position_tolerance_mm": {"type": "number"},
            },
            "required": ["distance_mm", "max_velocity_mm_s", "max_accel_mm_s2", "max_jerk_mm_s3"],
        },
    },
    {
        "name": "motion_gear_check",
        "description": "电子齿轮/脉冲当量自检：按丝杆导程、编码器分辨率、传动比计算应有的脉冲当量，"
                       "并给出偏差在典型行程上造成的定位误差。换卡/换丝杆后必查。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_mm_per_rev": {"type": "number", "description": "丝杆导程 mm/转"},
                "encoder_ppr": {"type": "number", "description": "编码器分辨率 pulse/转"},
                "gear_ratio": {"type": "number", "description": "电机圈数/负载圈数"},
                "electronic_gear_ppr": {"type": "number", "description": "电子齿轮 脉冲/电机转"},
                "configured_pulses_per_mm": {"type": "number", "description": "上位机当前配置值"},
                "travel_mm": {"type": "number"},
            },
            "required": ["lead_mm_per_rev", "encoder_ppr", "gear_ratio",
                         "electronic_gear_ppr", "configured_pulses_per_mm", "travel_mm"],
        },
    },
    {
        "name": "cam_check",
        "description": "电子凸轮表可行性校验：算段间速度阶跃（机械冲击的来源）、从轴峰值速度/加速度、"
                       "跟随误差预算，并给出「要消化这个阶跃、过渡段最少得多宽」的建议。"
                       "凸轮表可以是 CSV（主轴,从轴 两列）或 JSON。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_path": {"type": "string", "description": "凸轮表文件（CSV 两列或 JSON）"},
                "master_velocity": {"type": "number", "description": "主轴最大速度（主轴单位/s）"},
                "master_accel": {"type": "number", "description": "主轴最大加速度（主轴单位/s²）"},
                "slave_velocity_max": {"type": "number", "description": "从轴最大速度 mm/s"},
                "slave_accel_max": {"type": "number", "description": "从轴最大加速度 mm/s²"},
                "slave_travel_mm": {"type": "number", "description": "从轴行程上限 mm"},
                "servo_freq_hz": {"type": "number"},
                "position_tolerance_mm": {"type": "number"},
                "out_dir": {"type": "string"},
            },
            "required": ["table_path", "master_velocity",
                         "slave_velocity_max", "slave_accel_max"],
        },
    },
    {
        "name": "cam_plan",
        "description": "生成电子凸轮表：按梯形速度剖面分段（段接缝处从轴速度归零，因此没有速度阶跃），"
                       "输出通用格式的凸轮表 CSV/JSON，并做一次自检。"
                       "注意：下发到控制器前必须按厂商凸轮表格式转换（点数上限/单位/枚举语义查手册）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "master_travel": {"type": "number", "description": "主轴总行程"},
                "slave_travel_mm": {"type": "number", "description": "从轴总行程 mm"},
                "segments": {"type": "integer", "description": "段数"},
                "master_velocity": {"type": "number"},
                "slave_velocity_max": {"type": "number"},
                "slave_accel_max": {"type": "number"},
                "slave_ratios": {"type": "array", "items": {"type": "number"},
                                 "description": "各段从轴行程比例"},
                "ramp_points": {"type": "integer", "description": "每条加减速斜坡上的采样点数"},
                "out_dir": {"type": "string"},
            },
            "required": ["master_travel", "slave_travel_mm", "master_velocity",
                         "slave_velocity_max", "slave_accel_max"],
        },
    },
    {
        "name": "cam_caps",
        "description": "三家运动控制卡的电子凸轮能力差异：雷赛=凸轮表（可从上位机整表下发）、"
                       "正运动=凸轮表（表在控制器侧，上位机只能引用区间）、固高=跟随段+事件交叉（无表）。"
                       "每条都钉在官方 C# 绑定与 DLL 导出表上。",
        "inputSchema": {"type": "object", "properties": {"out_dir": {"type": "string"}},
                        "required": []},
    },
    {
        "name": "forensics_analyze",
        "description": "设备日志根因分析：重建时间轴，检出定位偏差、时序竞争、通信丢包、参数覆盖、"
                       "标定漂移、节拍抖动、超时聚集、心跳断流等问题，输出带行号证据的根因候选。",
        "inputSchema": {
            "type": "object",
            "properties": {"log_path": {"type": "string"}, "out_dir": {"type": "string"}},
            "required": ["log_path"],
        },
    },
    {
        "name": "servo_diagnose",
        "description": "伺服波形离线诊断（逆向链）：由实测波形反推等效二阶参数（ωn/ζ）、"
                       "超调、整定时间、振铃频率与跟随误差特征，给出候选根因与验证方法。"
                       "与 motion_plan（正向：由参数算误差）互为补充。"
                       "注意：等效二阶参数不等于机械固有频率；e≈a/ωn² 仅在 type-2 成立。"
                       "输出遵循 C3 诊断契约（schema mcopilot.servo.diagnosis/1）："
                       "hypotheses[] 每条带 fault_mode（KB0 §2 的 22 个 slug 之一）、"
                       "supporting_evidence / contradicting_evidence、expected_effect.basis、"
                       "next_data_to_collect；结构性不可评估的规则进 differential.not_evaluable 并附 blocked_by，"
                       "**不进 hypotheses**；没有 basis 的条目不给百分比。"
                       "频率类判据以「谱线绝对幅值 ÷ 误差动态 std」判定，"
                       "落在指令刷新率及其谐波上的谱峰按「指令刷新成分、非对象响应」登记。"
                       "可选输入：波形 CSV 里的转矩/电流列（解锁机械摩擦/爬行/转矩纹波/双惯量）、"
                       "events_path 事件流（C6 格式，解锁软件诱导族）；"
                       "事件流需锚点对齐（残差≤时钟不确定度）才允许把事件归因为误差原因，"
                       "否则相关判据按 events_sync_unverified 结构性拒答。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "波形 CSV（时间列 + 位置列，可选速度/误差/转矩列）"},
                "cmd_accel_mm_s2": {"type": "number", "description": "指令加速度，用于实测误差与理论值对比"},
                "time_unit": {"type": "string", "enum": ["auto", "s", "ms", "us"],
                              "description": "时间列单位，默认按列名自动判定"},
                "events_path": {"type": "string",
                                "description": "事件流 events.jsonl（C6 格式：t/source/code 必填），"
                                               "解锁软件诱导族判据"},
                "axis_path": {"type": "string",
                              "description": "轴铭牌侧车 axis.json（cpr/pole_pairs/screw_pitch_mm），"
                                             "解锁转矩纹波的阶次归因"},
                "drive_params_path": {"type": "string",
                                      "description": "驱动器参数侧车 drive_params.json"
                                                     "（current_loop_bandwidth_hz），解锁 SRV-18"},
                "out_dir": {"type": "string"},
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "forensics_thresholds",
        "description": "阈值灵敏度与误报边界：把每条阈值单独扫一遍，用二分精确定位「结论翻转点」，"
                       "标出哪些阈值脆（现场标定时优先标定）、哪些偏严（当前值永远不会命中）、"
                       "哪些配置根本没被代码读取（死阈值）。附每个检测器的误报源与人工复核方法。",
        "inputSchema": {
            "type": "object",
            "properties": {"log_path": {"type": "string"}, "out_dir": {"type": "string"}},
            "required": ["log_path"],
        },
    },
    {
        "name": "forensics_probe",
        "description": "设备日志格式体检：量化「这套工具对这份日志有多少耦合」——"
                       "行格式匹配率、哪些事件正则要改、哪些检测器会因为格式跑不了、"
                       "哪些只是没有埋点。用于评估接入成本。",
        "inputSchema": {
            "type": "object",
            "properties": {"log_path": {"type": "string"}, "out_dir": {"type": "string"}},
            "required": ["log_path"],
        },
    },
    {
        "name": "spc_report",
        "description": "SPC 与良率分析：I-MR 控制图、Cp/Cpk、不良 Pareto、良率趋势、CUSUM 变点检测、"
                       "工艺参数与不良的相关性。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string"},
                "metric": {"type": "string", "description": "控制指标列名"},
                "group_by": {"type": "string", "description": "分组列，默认 lot"},
                "usl": {"type": "number"},
                "lsl": {"type": "number"},
                "out_dir": {"type": "string"},
            },
            "required": ["csv_path", "metric"],
        },
    },
    {
        "name": "review_scan",
        "description": "实时运动上位机代码规则评审：阻塞等待、空 catch、无超时死循环、漏乘脉冲当量、"
                       "硬编码 IP、魔法数字、浮点等值比较、嵌套锁等。",
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}},
                           "out_dir": {"type": "string"}},
            "required": ["paths"],
        },
    },
    {
        "name": "card_capability_matrix",
        "description": "运动控制卡品牌能力矩阵：位置/速度单位口径、插补模型、硬件比较输出、位置锁存、"
                       "跨品牌差异与风险，以及各品牌的待核对项清单。",
        "inputSchema": {"type": "object", "properties": {"out_dir": {"type": "string"}}, "required": []},
    },
    {
        "name": "adapter_generate",
        "description": "从厂商 API 绑定生成 C# 适配器、统一抽象层接口、仿真器与跨品牌契约测试。",
        "inputSchema": {
            "type": "object",
            "properties": {"sdk": {"type": "string", "description": "dmc / zmotion"},
                           "out_dir": {"type": "string"}},
            "required": ["sdk"],
        },
    },
]


def _out(args: dict) -> Path:
    return ensure_out_dir(args.get("out_dir") or str(DEFAULT_OUT_DIR))


def _call_tool(name: str, args: dict) -> str:
    if name == "requirements_map":
        res = requirements.run(_out(args))
        return res["markdown"].read_text(encoding="utf-8")

    if name == "motion_plan":
        res = motion_lab.run_plan(
            args["distance_mm"], args["max_velocity_mm_s"], args["max_accel_mm_s2"],
            args["max_jerk_mm_s3"], args.get("servo_freq_hz"), args.get("damping_ratio"),
            args.get("position_tolerance_mm"), _out(args), "motion_plan")
        return res["report"].to_markdown()

    if name == "motion_gear_check":
        return json.dumps(motion_lab.run_scale(
            args["lead_mm_per_rev"], args["encoder_ppr"], args["gear_ratio"],
            args["electronic_gear_ppr"], args["configured_pulses_per_mm"], args["travel_mm"]),
            ensure_ascii=False, indent=2)

    if name == "cam_check":
        res = cam_lab.run_check(
            cam_lab.load_table(args["table_path"]),
            args["master_velocity"], args.get("master_accel", 0.0),
            args["slave_velocity_max"], args["slave_accel_max"],
            args.get("slave_travel_mm"), args.get("servo_freq_hz"),
            args.get("position_tolerance_mm"), _out(args), "cam_check")
        return res["report"].to_markdown()

    if name == "cam_plan":
        res = cam_lab.run_plan(
            args["master_travel"], args["slave_travel_mm"], args.get("segments", 4),
            args["master_velocity"], args["slave_velocity_max"], args["slave_accel_max"],
            args.get("slave_ratios"), args.get("ramp_points", 4), _out(args), "cam_plan")
        return res["report"].to_markdown()

    if name == "cam_caps":
        return cam_lab.run_caps(_out(args), "cam_caps")["report"].to_markdown()

    if name == "forensics_analyze":
        res = forensics.run(Path(args["log_path"]), _out(args))
        return res["report"].to_markdown()

    if name == "servo_diagnose":
        ev = args.get("events_path")
        ax = args.get("axis_path")
        dp = args.get("drive_params_path")
        res = servo.run_diagnose(Path(args["csv_path"]), _out(args),
                                 args.get("cmd_accel_mm_s2"),
                                 time_unit=args.get("time_unit", "auto"),
                                 events_path=Path(ev) if ev else None,
                                 axis_path=Path(ax) if ax else None,
                                 drive_params_path=Path(dp) if dp else None)
        return res["report"].to_markdown()

    if name == "forensics_probe":
        res = forensics.run_probe(Path(args["log_path"]), _out(args))
        return res["report"].to_markdown()

    if name == "forensics_thresholds":
        res = threshold_lab.run(Path(args["log_path"]), _out(args))
        return res["report"].to_markdown()

    if name == "spc_report":
        res = spc.run(Path(args["csv_path"]), args["metric"], args.get("usl"), args.get("lsl"),
                      args.get("group_by", "lot"), _out(args))
        return res["report"].to_markdown()

    if name == "review_scan":
        res = review.run([Path(p) for p in args["paths"]], _out(args))
        return res["report"].to_markdown()

    if name == "card_capability_matrix":
        res = adapter_gen.run_matrix(_out(args))
        return res["report"].to_markdown()

    if name == "adapter_generate":
        res = adapter_gen.run_gen(args["sdk"], _out(args) / "csharp")
        return "\n".join(f"已生成：{p}" for p in res["written"].values())

    raise ValueError(f"未知工具：{name}")


def _handle(msg: dict) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {}) or {}
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            text = _call_tool(name, args)
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as exc:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"执行失败：{exc}"}],
                               "isError": True}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"未实现的方法：{method}"}}
    return None


def main() -> int:
    # MCP 走 stdio，**协议层必须是 UTF-8 JSON**。
    # 这里不能沿用控制台编码 —— 中文 Windows 的 sys.stdout.encoding 是 cp936(GBK)，
    # 沿用它 = 服务端吐出的中文是 GBK 字节，客户端按 UTF-8 解会直接崩
    # （表现：initialize 能回，第二个请求就读不出行了）。
    # 实测踩过：非 ASCII 的工具描述一出现就解码失败。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
