"""统一命令行入口。

    python -m mcopilot <命令> [参数]
    mcopilot.exe / mcopilot.bat 包装脚本见仓库根目录 mcopilot.bat

设计：CLI 与 MCP server 共用同一套 agent 函数，保证两条入口行为一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents import adapter_gen, cam_lab, forensics, motion_lab, requirements, review, servo, spc, threshold_lab
from .core.util import DEFAULT_OUT_DIR, ensure_out_dir, sample_path, write_json

# 控制台编码跟随本机（中文 Windows 的 cmd.exe 是 GBK，PS7/Windows Terminal 是 UTF-8），
# errors="replace" 保证遇到无法表示的字符时不会把整个进程打挂。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding=getattr(_stream, "encoding", None) or "utf-8",
                            errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def _out(args: argparse.Namespace) -> Path:
    return ensure_out_dir(args.out)


def _say(path: Path) -> None:
    print(f"✅ 已生成：{path}")


# ---------------------------------------------------------- requirements


def cmd_requirements(args: argparse.Namespace) -> int:
    out = _out(args)
    res = requirements.run(out, stem=args.stem)
    for k, v in res.items():
        _say(v)
    return 0


# ------------------------------------------------------------------ motion


def cmd_motion_plan(args: argparse.Namespace) -> int:
    out = _out(args)
    res = motion_lab.run_plan(args.distance, args.v, args.a, args.j,
                              args.freq, args.damping, args.tol, out, args.stem)
    rep = res["report"]
    written = rep.write(out, args.stem)
    print(rep.to_markdown())
    for v in written.values():
        _say(v)
    if res["warnings"]:
        print("\n⚠ 存在风险提示，见报告「风险提示」一节。")
    return 0


def cmd_motion_gear(args: argparse.Namespace) -> int:
    res = motion_lab.run_scale(args.lead, args.encoder, args.ratio, args.ppr,
                               args.configured, args.travel)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "一致" in res["verdict"] else 2


def cmd_motion_compare(args: argparse.Namespace) -> int:
    p = motion_lab.build_profile(args.distance, args.v, args.a, args.j)
    res = motion_lab.compare_point(p, args.target, args.counts_per_mm, args.exposure_us,
                                   args.max_shift)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_motion_vectors(args: argparse.Namespace) -> int:
    cases = [
        {"name": "短行程_达不到目标速度", "distance": 1.0, "v": 200.0, "a": 1000.0, "j": 5000.0},
        {"name": "常规行程_含匀速段", "distance": 100.0, "v": 100.0, "a": 500.0, "j": 2000.0},
        {"name": "长行程", "distance": 500.0, "v": 200.0, "a": 1000.0, "j": 5000.0},
        {"name": "负方向", "distance": -50.0, "v": 80.0, "a": 400.0, "j": 1500.0},
    ]
    data = motion_lab.golden_vectors(cases)
    target = Path(args.file)
    if target.is_dir():
        target = target / "golden_vectors.json"
    path = write_json(target, data)
    _say(path)
    return 0


# ------------------------------------------------------------------ cam（电子凸轮）


def cmd_cam_check(args: argparse.Namespace) -> int:
    out = _out(args)
    table = cam_lab.load_table(args.table)
    res = cam_lab.run_check(table, args.master_v, args.master_a, args.slave_v_max,
                             args.slave_a_max, args.slave_travel, args.freq, args.tol,
                             out, args.stem, args.master_unit, args.slave_unit)
    written = res["report"].write(out, args.stem)
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0 if res["result"]["verdict_code"] != "fail" else 2


def cmd_cam_plan(args: argparse.Namespace) -> int:
    out = _out(args)
    ratios = [float(x) for x in args.slave_ratios.split(",")] if args.slave_ratios else None
    res = cam_lab.run_plan(args.master_travel, args.slave_travel, args.segments,
                           args.master_v, args.slave_v_max, args.slave_a_max,
                           ratios, args.ramp_points, out, args.stem)
    written = res["report"].write(out, args.stem)
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    for k, v in res["written"].items():
        _say(v)
    print("\n下一步：mcopilot cam check " + str(res["written"].get("csv")) +
          " --master-v ... --slave-v-max ... --slave-a-max ...")
    return 0


def cmd_cam_caps(args: argparse.Namespace) -> int:
    out = _out(args)
    res = cam_lab.run_caps(out, args.stem)
    print(res["report"].to_markdown())
    for v in res["written"].values():
        _say(v)
    return 0


# ------------------------------------------------------------------ forensics


def cmd_forensics(args: argparse.Namespace) -> int:
    out = _out(args)
    res = forensics.run(Path(args.log), out, args.stem)
    written = res["report"].write(out, args.stem)
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


def cmd_forensics_probe(args: argparse.Namespace) -> int:
    """格式体检：量化「这套工具对你们的日志有多少耦合」。"""
    out = _out(args)
    res = forensics.run_probe(Path(args.log), out, args.stem)
    written = res["report"].write(out, args.stem or f"probe_{Path(args.log).stem}")
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


def cmd_forensics_thresholds(args: argparse.Namespace) -> int:
    """阈值灵敏度分析：扫出每条阈值的结论翻转点 + 检测器误报边界。"""
    out = _out(args)
    res = threshold_lab.run(Path(args.log), out, args.stem)
    written = res["report"].write(out, args.stem or f"threshold_{Path(args.log).stem}")
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


# ------------------------------------------------------------------ spc


def cmd_spc(args: argparse.Namespace) -> int:
    out = _out(args)
    res = spc.run(Path(args.csv), args.metric, args.usl, args.lsl, args.group_by,
                  out, args.result_col, args.ng_col, args.stem)
    written = res["report"].write(out, args.stem)
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


# ------------------------------------------------------------------ review


def cmd_review(args: argparse.Namespace) -> int:
    out = _out(args)
    paths = [Path(p) for p in args.paths]
    res = review.run(paths, out, Path(args.root) if args.root else None)
    written = res["report"].write(out, args.stem)
    problems = [i for i in res["issues"] if not i.is_positive]
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    high = [i for i in problems if i.level == "高"]
    print(f"\n命中 {len(problems)} 处问题（高危 {len(high)} 处）。")
    return 1 if high else 0


# ------------------------------------------------------------------ adapter


def cmd_adapter_gen(args: argparse.Namespace) -> int:
    out = ensure_out_dir(args.out)
    # 与 `mcopilot all` 保持同一目录布局（C# 源码统一进 out/csharp/），
    # 否则同一份产物会散在两个地方，用的人会分不清哪份是新的。
    res = adapter_gen.run_gen(args.sdk, out / "csharp")
    for k, v in res["written"].items():
        _say(v)
    todo = [f for f in res["sdk"].get("pinvoke", [])
            if f.get("verified") == "needs-manual-check" and not f.get("skip_emit")]
    if todo:
        print(f"\n⚠ 生成的适配器中有 {len(todo)} 处标了 TODO[需核对厂商手册]，"
              f"请对照厂商函数手册补齐后再上机。")
    return 0


def cmd_adapter_matrix(args: argparse.Namespace) -> int:
    out = _out(args)
    res = adapter_gen.run_matrix(out, args.stem)
    written = res["report"].write(out, args.stem)
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


# ------------------------------------------------------------------ servo


def cmd_servo_diagnose(args: argparse.Namespace) -> int:
    out = _out(args)
    ev = Path(args.events) if getattr(args, "events", None) else None
    ax = Path(args.axis) if getattr(args, "axis", None) else None
    dp = Path(args.drive_params) if getattr(args, "drive_params", None) else None
    res = servo.run_diagnose(Path(args.csv), out, args.accel, args.stem,
                             args.time_unit, events_path=ev, axis_path=ax,
                             drive_params_path=dp)
    written = res["report"].write(out, args.stem or f"servo_{Path(args.csv).stem}")
    print(res["report"].to_markdown())
    for v in written.values():
        _say(v)
    return 0


def cmd_servo_synth(args: argparse.Namespace) -> int:
    out = _out(args)
    csv_path = Path(args.csv) if args.csv else out / f"servo_{args.model}.csv"
    res = servo.run_synth(args.model, csv_path, wn=args.wn, zeta=args.zeta,
                          j1=args.j1, j2=args.j2, wf=args.wf, zf=args.zf,
                          kt=args.kt, kp=args.kp, kv=args.kv,
                          duration=args.duration, fs=args.fs)
    _say(res["csv"])
    _say(csv_path.with_suffix(".truth.json"))
    print(json.dumps(res["truth"], ensure_ascii=False, indent=2))
    print("\n下一步：mcopilot servo diagnose " + str(csv_path) + "  —— 拿估计值和这份真值对照。")
    return 0


# ------------------------------------------------------------------ all


def cmd_all(args: argparse.Namespace) -> int:
    out = _out(args)
    print("▶ 1/9 工业需求基线与追溯")
    for v in requirements.run(out, stem="requirements_map").values():
        _say(v)
    print("▶ 2/9 运动卡能力矩阵")
    for v in adapter_gen.run_matrix(out)["report"].write(out, "card_capability").values():
        _say(v)
    print("▶ 3/9 适配层代码生成")
    for sdk in ("dmc", "zmotion", "gts"):
        for v in adapter_gen.run_gen(sdk, out / "csharp")["written"].values():
            _say(v)
    print("▶ 4/9 日志取证")
    sample_log = sample_path("logs", "machine_a.log")
    if sample_log.exists():
        for v in forensics.run(sample_log, out, "forensics_sample")["report"].write(out, "forensics_sample").values():
            _say(v)
    print("▶ 5/9 日志格式体检（量化格式耦合成本）")
    sample_log2 = sample_path("logs", "vendor_b.log")
    if sample_log2.exists():
        for v in forensics.run_probe(sample_log2, out, "probe_sample")["report"].write(
                out, "probe_sample").values():
            _say(v)
    print("▶ 5b/9 阈值灵敏度与误报边界")
    if sample_log.exists():
        for v in threshold_lab.run(sample_log, out, "threshold_sample")["report"].write(
                out, "threshold_sample").values():
            _say(v)
    print("▶ 6/9 SPC 与良率")
    sample_csv = sample_path("process", "line1_lot.csv")
    if sample_csv.exists():
        for v in spc.run(sample_csv, "place_x_mm", None, None, "lot", out,
                         stem="spc_sample")["report"].write(out, "spc_sample").values():
            _say(v)
    print("▶ 7/9 伺服波形离线诊断（逆向）")
    sample_wave = sample_path("servo", "case_b_resonance.csv")
    if sample_wave.exists():
        for v in servo.run_diagnose(sample_wave, out, stem="servo_sample")["report"].write(
                out, "servo_sample").values():
            _say(v)
    print("▶ 7b/9 电子凸轮（表可行性 + 三家能力差异）")
    sample_cam = sample_path("cam", "pick_place_cam.csv")
    if sample_cam.exists():
        # 样例表是「手画表」典型：第 7 段接缝处有 72 mm/s 速度阶跃，
        # 这里就是要让它被检出来 —— 结论是 fail 属正常，不中断整条流水线。
        res_cam = cam_lab.run_check(
            cam_lab.load_table(sample_cam),
            master_v=360.0, master_a=200.0,
            slave_v_max=300.0, slave_a_max=2000.0,
            slave_travel_limit=120.0,
            master_unit="deg",
            out_dir=out, stem="cam_check")
        for v in res_cam["report"].write(out, "cam_check").values():
            _say(v)
        print(f"   样例表自检结论：{res_cam['result']['verdict']}（样例故意留了缺陷，用来证明检得出）")
    for v in cam_lab.run_caps(out, "cam_caps")["written"].values():
        _say(v)
    print("▶ 8/9 代码评审（样例代码）")
    sample_src = sample_path("code")
    if sample_src.exists():
        for v in review.run([sample_src], out, sample_src)["report"].write(out, "review_sample").values():
            _say(v)
    print("▶ 9/9 文档/清单类产物")
    print(f"\n全部产物已输出到：{out}")
    return 0


# ------------------------------------------------------------------ 参数解析


# 叶子命令共享的 --out；default=SUPPRESS 保证未指定时不覆盖顶层默认值
_OUT_PARENT = argparse.ArgumentParser(add_help=False)
_OUT_PARENT.add_argument("--out", default=argparse.SUPPRESS, help="输出目录")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mcopilot",
        description="运动控制上位机 AI 工程助手套件 —— 把工业需求里能被 AI 承担的部分做成能进生产流程的工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  mcopilot requirements report
  mcopilot motion plan --distance 100 --v 200 --a 1000 --j 5000 --freq 50 --damping 0.7 --tol 0.01
  mcopilot motion gear --lead 10 --encoder 131072 --ratio 1 --ppr 16384 --configured 1638.4 --travel 200
  mcopilot cam check out/cam_plan_table.csv --master-v 360 --slave-v-max 300 --slave-a-max 2000
  mcopilot cam plan --master-travel 360 --slave-travel 20 --segments 4 --master-v 360 --slave-v-max 300 --slave-a-max 2000
  mcopilot cam caps
  mcopilot forensics analyze device.log
  mcopilot forensics probe device.log
  mcopilot servo diagnose wave.csv --accel 1000
  mcopilot servo synth --model 2inertia
  mcopilot spc report process.csv --metric place_x_mm --group-by lot
  mcopilot review ../MyApp/Source
  mcopilot adapter gen --sdk dmc
  mcopilot all --out out/
""")
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="输出目录（默认 out/）")
    sub = p.add_subparsers(dest="cmd", required=True)

    # requirements
    req_p = sub.add_parser("requirements", help="工业需求基线与能力地图")
    req_sub = req_p.add_subparsers(dest="sub", required=True)
    req_r = req_sub.add_parser("report", help="生成工业需求基线报告", parents=[_OUT_PARENT])
    req_r.add_argument("--stem", default="requirements_map")
    req_r.set_defaults(func=cmd_requirements)

    # motion
    mo_p = sub.add_parser("motion", help="运动参数验证（S 曲线/到位/跟随误差/脉当量/比较点）")
    mo_sub = mo_p.add_subparsers(dest="sub", required=True)

    pl = mo_sub.add_parser("plan", help="算 S 曲线与到位时间", parents=[_OUT_PARENT])
    pl.add_argument("--distance", type=float, required=True, help="位移 mm（负数为反方向）")
    pl.add_argument("--v", type=float, required=True, help="最大速度 mm/s")
    pl.add_argument("--a", type=float, required=True, help="最大加速度 mm/s²")
    pl.add_argument("--j", type=float, required=True, help="最大 jerk mm/s³")
    pl.add_argument("--freq", type=float, help="伺服自然频率 Hz（用于跟随误差估算）")
    pl.add_argument("--damping", type=float, help="阻尼比 ζ")
    pl.add_argument("--tol", type=float, help="位置容差 mm")
    pl.add_argument("--stem", default="motion_plan")
    pl.set_defaults(func=cmd_motion_plan)

    gr = mo_sub.add_parser("gear", help="电子齿轮/脉冲当量自检", parents=[_OUT_PARENT])
    gr.add_argument("--lead", type=float, required=True, help="丝杆导程 mm/转")
    gr.add_argument("--encoder", type=float, required=True, help="编码器分辨率 pulse/转")
    gr.add_argument("--ratio", type=float, required=True, help="传动比（电机圈/负载圈）")
    gr.add_argument("--ppr", type=float, required=True, help="电子齿轮设定 脉冲/电机转")
    gr.add_argument("--configured", type=float, required=True, help="上位机配置的脉冲当量 pulse/mm")
    gr.add_argument("--travel", type=float, required=True, help="典型行程 mm")
    gr.set_defaults(func=cmd_motion_gear)

    cp = mo_sub.add_parser("compare", help="硬件比较输出/飞拍触发点", parents=[_OUT_PARENT])
    cp.add_argument("--distance", type=float, required=True)
    cp.add_argument("--v", type=float, required=True)
    cp.add_argument("--a", type=float, required=True)
    cp.add_argument("--j", type=float, required=True)
    cp.add_argument("--target", type=float, required=True, help="触发位置 mm")
    cp.add_argument("--counts-per-mm", type=float, required=True, help="编码器计数/mm")
    cp.add_argument("--exposure-us", type=float, required=True, help="曝光时间 μs")
    cp.add_argument("--max-shift", type=float, default=0.01, help="允许的曝光窗口位移 mm")
    cp.set_defaults(func=cmd_motion_compare)

    ve = mo_sub.add_parser("vectors", help="生成上位机单测用的黄金测试向量", parents=[_OUT_PARENT])
    ve.add_argument("--file", default="out/golden_vectors.json", help="黄金测试向量输出路径")
    ve.set_defaults(func=cmd_motion_vectors)

    # cam（电子凸轮）
    cm_p = sub.add_parser("cam", help="电子凸轮表校验 / 生成 / 三家能力差异")
    cm_sub = cm_p.add_subparsers(dest="sub", required=True)

    cc = cm_sub.add_parser("check", help="校验一张凸轮表能不能用", parents=[_OUT_PARENT])
    cc.add_argument("table", help="凸轮表文件（CSV 两列：主轴,从轴 / JSON）")
    cc.add_argument("--master-v", type=float, required=True, help="主轴最大速度（主轴单位/s）")
    cc.add_argument("--master-a", type=float, default=0.0, help="主轴最大加速度（主轴单位/s²）")
    cc.add_argument("--slave-v-max", type=float, required=True, help="从轴最大速度 mm/s")
    cc.add_argument("--slave-a-max", type=float, required=True, help="从轴最大加速度 mm/s²")
    cc.add_argument("--slave-travel", type=float, help="从轴行程上限 mm")
    cc.add_argument("--freq", type=float, help="从轴伺服自然频率 Hz（跟随误差估算）")
    cc.add_argument("--tol", type=float, help="从轴位置容差 mm")
    cc.add_argument("--master-unit", default=None, help="主轴单位标签（如 deg / mm，默认「主轴单位」）")
    cc.add_argument("--slave-unit", default=None, help="从轴单位标签（默认 mm）")
    cc.add_argument("--stem", default="cam_check")
    cc.set_defaults(func=cmd_cam_check)

    cp2 = cm_sub.add_parser("plan", help="按梯形速度剖面生成凸轮表并自检", parents=[_OUT_PARENT])
    cp2.add_argument("--master-travel", type=float, required=True, help="主轴总行程")
    cp2.add_argument("--slave-travel", type=float, required=True, help="从轴总行程 mm")
    cp2.add_argument("--segments", type=int, default=4, help="段数")
    cp2.add_argument("--master-v", type=float, required=True, help="主轴速度（主轴单位/s）")
    cp2.add_argument("--slave-v-max", type=float, required=True, help="从轴速度上限 mm/s")
    cp2.add_argument("--slave-a-max", type=float, required=True, help="从轴加速度上限 mm/s²")
    cp2.add_argument("--slave-ratios", default=None, help="各段从轴行程比例，逗号分隔（如 1,2,1）")
    cp2.add_argument("--ramp-points", type=int, default=4, help="每条加减速斜坡上的采样点数")
    cp2.add_argument("--stem", default="cam_plan")
    cp2.set_defaults(func=cmd_cam_plan)

    ccs = cm_sub.add_parser("caps", help="三家电子凸轮能力差异", parents=[_OUT_PARENT])
    ccs.add_argument("--stem", default="cam_caps")
    ccs.set_defaults(func=cmd_cam_caps)

    # forensics
    fo_p = sub.add_parser("forensics", help="设备日志根因分析")
    fo_sub = fo_p.add_subparsers(dest="sub", required=True)
    fa = fo_sub.add_parser("analyze", help="分析日志", parents=[_OUT_PARENT])
    fa.add_argument("log", help="日志文件路径")
    fa.add_argument("--stem", default=None)
    fa.set_defaults(func=cmd_forensics)

    fp = fo_sub.add_parser("probe", help="格式体检：量化适配成本与哪些检测器会跑不了",
                            parents=[_OUT_PARENT])
    fp.add_argument("log", help="待体检的日志文件路径")
    fp.add_argument("--stem", default=None)
    fp.set_defaults(func=cmd_forensics_probe)

    ft = fo_sub.add_parser("thresholds", help="阈值灵敏度分析：哪些阈值脆、哪些没生效、误报边界在哪",
                            parents=[_OUT_PARENT])
    ft.add_argument("log", help="日志文件路径")
    ft.add_argument("--stem", default=None)
    ft.set_defaults(func=cmd_forensics_thresholds)

    # spc
    sp_p = sub.add_parser("spc", help="SPC 与良率分析")
    sp_sub = sp_p.add_subparsers(dest="sub", required=True)
    sr = sp_sub.add_parser("report", help="生成 SPC 报告", parents=[_OUT_PARENT])
    sr.add_argument("csv", help="工艺数据 CSV")
    sr.add_argument("--metric", required=True, help="控制指标列名")
    sr.add_argument("--group-by", default="lot", help="分组列（lot / device）")
    sr.add_argument("--usl", type=float, help="工程规格上限")
    sr.add_argument("--lsl", type=float, help="工程规格下限")
    sr.add_argument("--result-col", default=None)
    sr.add_argument("--ng-col", default=None)
    sr.add_argument("--stem", default=None)
    sr.set_defaults(func=cmd_spc)

    # review
    rv_p = sub.add_parser("review", help="实时运动代码规则评审", parents=[_OUT_PARENT])
    rv_p.add_argument("paths", nargs="+", help="源码文件或目录")
    rv_p.add_argument("--root", default=None, help="报告中的相对路径根")
    rv_p.add_argument("--stem", default="review")
    rv_p.set_defaults(func=cmd_review)

    # adapter
    ad_p = sub.add_parser("adapter", help="运动卡适配层与能力矩阵")
    ad_sub = ad_p.add_subparsers(dest="sub", required=True)
    ag = ad_sub.add_parser("gen", help="从厂商 API 绑定生成 C# 适配器与契约测试", parents=[_OUT_PARENT])
    ag.add_argument("--sdk", required=True, help="SDK 绑定名（knowledge/sdks 下的文件名）")
    ag.set_defaults(func=cmd_adapter_gen)
    am = ad_sub.add_parser("matrix", help="生成品牌能力矩阵", parents=[_OUT_PARENT])
    am.add_argument("--stem", default="card_capability")
    am.set_defaults(func=cmd_adapter_matrix)

    # servo
    sv_p = sub.add_parser("servo", help="伺服波形离线诊断（实测波形 → 等效参数 → 候选根因）")
    sv_sub = sv_p.add_subparsers(dest="sub", required=True)
    sd = sv_sub.add_parser("diagnose", help="诊断一段伺服波形 CSV", parents=[_OUT_PARENT])
    sd.add_argument("csv", help="波形 CSV（需含时间列与位置列）")
    sd.add_argument("--accel", type=float, help="指令加速度 mm/s²（用于实测误差 vs 理论值对比）")
    sd.add_argument("--time-unit", default="auto", choices=["auto", "s", "ms", "us"],
                    help="时间列单位（默认按列名自动判定；判定错会导致 ωn 差 1000 倍）")
    sd.add_argument("--events", default=None,
                    help="事件流 events.jsonl（C6 格式：一行一事件，t/source/code 必填）。"
                         "补上它才能评软件诱导族（SRV-23/24/25/26/28/29）；"
                         "事件与波形逐拍对齐（锚点残差≤时钟不确定度）才允许因果归因")
    sd.add_argument("--axis", default=None,
                    help="轴铭牌侧车 axis.json（cpr/pole_pairs/screw_pitch_mm）。"
                         "有了它才能把转矩纹波谱线归因到阶次"
                         "（6× 电频率=逆变器/死区特征，每转整数阶=机械周期误差）")
    sd.add_argument("--drive-params", default=None,
                    help="驱动器参数侧车 drive_params.json"
                         "（current_loop_bandwidth_hz 必填）。"
                         "有了它才能评 SRV-18：转矩谐振是否超出电流环带宽")
    sd.add_argument("--stem", default=None)
    sd.set_defaults(func=cmd_servo_diagnose)

    ss = sv_sub.add_parser("synth", help="合成已知真值的阶跃波形（用来验证估计器）", parents=[_OUT_PARENT])
    ss.add_argument("--model", default="2nd", choices=["2nd", "2inertia"])
    ss.add_argument("--csv", default=None, help="输出 CSV 路径（默认写到输出目录）")
    ss.add_argument("--wn", type=float, default=60.0, help="自然频率 rad/s（model=2nd）")
    ss.add_argument("--zeta", type=float, default=0.4, help="阻尼比（model=2nd）")
    ss.add_argument("--j1", type=float, default=1.0, help="电机惯量（model=2inertia）")
    ss.add_argument("--j2", type=float, default=1.0, help="负载惯量（model=2inertia）")
    ss.add_argument("--wf", type=float, default=300.0, help="柔性传动固有频率 rad/s")
    ss.add_argument("--zf", type=float, default=0.05, help="柔性传动阻尼比")
    ss.add_argument("--kt", type=float, default=1.0, help="转矩常数")
    ss.add_argument("--kp", type=float, default=400.0, help="位置环比例增益")
    ss.add_argument("--kv", type=float, default=0.0, help="速度前馈增益")
    ss.add_argument("--duration", type=float, default=0.6)
    ss.add_argument("--fs", type=float, default=2000.0)
    ss.set_defaults(func=cmd_servo_synth)

    # all
    al = sub.add_parser("all", help="一键跑通全部智能体（产出全套报告）", parents=[_OUT_PARENT])
    al.set_defaults(func=cmd_all)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 执行失败：{exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

