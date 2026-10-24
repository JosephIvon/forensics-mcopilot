# -*- coding: utf-8 -*-
"""eval_forensics 骨架：通信日志取证归因的 precision/recall 评测（零依赖）。

输入三件（真实使用形态，P4 forensics 协议感知开工时接线）：
  --logs       <logs.jsonl>       现场通信日志，必须先过 comm_log/1 契约
                                  （scripts/validate_comm_log.py 同一套裁判，R2：
                                  违规即拒跑——归因层不修数据，修采集端）。
  --detections <detections.jsonl> 检出结果，每行 {"id", "cause", ...}：
                                  id=归因对象标识（如日志行号或帧键），
                                  cause=归因结论（协议异常码/链路错误类）。
  --truth      <truth.jsonl>      标注真值，每行 {"id", "cause", ...}，同键同义。

判定口径（骨架版，故意简单到无法作弊）：
  检出正确 ⇔ (id, cause) 二元组同时出现在 detections 与 truth（集合语义，重复折叠）。
  precision = TP/(TP+FP)，recall = TP/(TP+FN)；输出漏检清单（truth 有检出无）与
  误报清单（检出有 truth 无）。

诚实边界（2026-10-21 落档时）：仓库内**零份真实现场日志、零份标注真值集**，
内嵌样例全部合成。本脚本当前只能证明「骨架可跑、口径自洽」，
**不能对归因质量下任何结论**——结论要等真实日志与真值集落库。

--selftest：内嵌样例（2 条合法日志、2 条检出、2 条真值：1 对 1 错 1 漏），
期望 precision=0.5 / recall=0.5，退出码 0 = 骨架行为与文档一致。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_comm_log as vcl  # 契约裁判复用（R2），不另抄一套口径

HONESTY = ("诚实边界：当前样例为合成数据；仓库零份真实日志与零份标注真值集——"
           "本骨架只证明评测链可跑，不能对归因质量下结论。")


def read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """读 JSONL → (对象列表, 坏行摘要)。行号口径与非空行序号一致（同校验器）。"""
    items: list[dict] = []
    bad: list[str] = []
    for no, chunk in enumerate((c for c in path.read_text(encoding="utf-8").splitlines()
                                if c.strip()), 1):
        try:
            rec = json.loads(chunk)
        except json.JSONDecodeError as e:
            bad.append(f"L{no}: 不是合法 JSON（{e.msg}）")
            continue
        if not isinstance(rec, dict):
            bad.append(f"L{no}: 记录必须是 JSON 对象")
            continue
        missing = [k for k in ("id", "cause")
                   if not isinstance(rec.get(k), str) or not rec[k].strip()]
        if missing:
            bad.append(f"L{no}: 缺非空字段 {missing}")
            continue
        items.append(rec)
    return items, bad


def score(detections: list[dict], truth: list[dict]) -> dict:
    """集合口径打分：匹配键 (id, cause)。重复 (id, cause) 折叠（详见模块 docstring）。"""
    dset = {(d["id"], d["cause"]) for d in detections}
    tset = {(t["id"], t["cause"]) for t in truth}
    tp = dset & tset
    fp = dset - tset
    fn = tset - dset
    precision = len(tp) / len(dset) if dset else 0.0
    recall = len(tp) / len(tset) if tset else 0.0
    return {"tp": len(tp), "fp": len(fp), "fn": len(fn),
            "precision": precision, "recall": recall,
            "missed": sorted(fn), "false_positives": sorted(fp)}


def _selftest() -> int:
    """内嵌样例：2 条合法日志 + 检出 {对, 错} + 真值 {对, 漏} → P=R=0.5。"""
    contract = vcl.load_contract(None)
    logs = [
        {"timestamp_utc": "2026-10-21T02:15:30.123Z", "seq": 0, "channel": "rtu",
         "direction": "req", "unit_id": 17, "function_code": 3,
         "device": {"host_or_port": "COM3"}},
        {"timestamp_utc": "2026-10-21T02:15:31.000Z", "seq": 1, "channel": "rtu",
         "direction": "resp", "unit_id": 17, "function_code": 3,
         "exception_code": 2, "device": {"host_or_port": "COM3"},
         "notes": "ILLEGAL DATA ADDRESS（标注示例：现场接错起始地址）"},
    ]
    detections = [
        {"id": "L2", "cause": "EX02_ILLEGAL_DATA_ADDRESS"},   # 对
        {"id": "L2", "cause": "crc_error"},                   # 错（误报）
    ]
    truth = [
        {"id": "L2", "cause": "EX02_ILLEGAL_DATA_ADDRESS"},   # 被检出
        {"id": "L2", "cause": "timeout_after_req"},           # 漏检（同一帧第二真值）
    ]
    v, _ = vcl.validate_records(logs, contract)
    if v:
        print(f"  ✗ 内嵌日志未过契约门（{len(v)} 违规）：", *v, sep="\n    ")
        return 1
    r = score(detections, truth)
    ok = (r["precision"] == 0.5 and r["recall"] == 0.5
          and r["tp"] == 1 and r["fp"] == 1 and r["fn"] == 1)
    print(f"  selftest 样例: TP={r['tp']} FP={r['fp']} FN={r['fn']} "
          f"precision={r['precision']:.2f} recall={r['recall']:.2f} "
          f"[{'OK ' if ok else 'BAD'}]（期望 1/1/1，P=R=0.50）")
    print(f"  漏检清单: {r['missed']}")
    print(f"  误报清单: {r['false_positives']}")
    print(f"eval_forensics --selftest: {'PASS' if ok else 'FAIL'}")
    print(HONESTY)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="forensics 归因评测骨架：precision/recall/漏检清单（零依赖）")
    ap.add_argument("--logs", type=Path, help="现场日志 jsonl（须过 comm_log/1 契约门）")
    ap.add_argument("--detections", type=Path, help="检出结果 jsonl（id+cause）")
    ap.add_argument("--truth", type=Path, help="标注真值 jsonl（id+cause）")
    ap.add_argument("--selftest", action="store_true", help="内嵌样例自检")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not (args.logs and args.detections and args.truth):
        ap.error("需要 --logs --detections --truth 三件输入（或 --selftest）")

    # R2：日志先过契约门，违规即拒跑（归因层不修数据）
    contract = vcl.load_contract(None)
    violations, _, _ = vcl.validate_lines(args.logs, contract)
    if violations:
        print(f"✗ 日志未过 comm_log/1 契约门（违规 {len(violations)}），拒跑归因评测（R2）")
        for s in violations[:20]:
            print("  ✗", s)
        return 2

    detections, bad_d = read_jsonl(args.detections)
    truth, bad_t = read_jsonl(args.truth)
    for s in bad_d + bad_t:
        print("  ✗", s)
    if bad_d or bad_t:
        return 2
    if not truth:
        print("✗ 真值集为空：没有真值谈不上评测（不产出无意义的 100%）")
        return 2

    r = score(detections, truth)
    print(f"forensics 归因评测: TP={r['tp']} FP={r['fp']} FN={r['fn']}")
    print(f"  precision = {r['precision']:.4f}（检出 {len({(d['id'], d['cause']) for d in detections})} 条，对 {r['tp']}）")
    print(f"  recall    = {r['recall']:.4f}（真值 {len({(t['id'], t['cause']) for t in truth})} 条，覆盖 {r['tp']}）")
    if r["missed"]:
        print("  漏检清单:")
        for mid, cause in r["missed"]:
            print(f"    - {mid}: {cause}")
    if r["false_positives"]:
        print("  误报清单:")
        for mid, cause in r["false_positives"]:
            print(f"    - {mid}: {cause}")
    print(HONESTY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
