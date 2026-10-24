#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_missing_artifacts.py —— 断链件"是否只是改名/搬到别处"的全局搜索（2026-10-22）。

纪律：改文档前先查工件在不在——可能在别的仓、别的目录、别的文件名（大小写/前缀不同）。
"""
import io
import os
import subprocess
from _localenv import expand

REPOS = {
    "mcopilot": expand(r"%WORKSPACE%\mcopilot"),
    "axiscope": expand(r"%WORKSPACE%\axiscope"),
    "trae_factory": expand(r"%WORKSPACE%\trae_factory"),
}
BASENAMES = [
    "annotate_provenance.py", "test_sdk_provenance.py", "JointEval.md", "TruthChain.md",
    "c1_sample.py", "c1_from_servo_sample.py", "shared_eval.json", "joint_eval.py",
    "verify_darus3252_servo.py", "verify_darus6114_servo.py", "verify_darus6114_sweep.py",
    "verify_klipper_resonance.py", "verify_export10_truth.py", "run_gates.py",
    "golden_vectors.json", "c3_example_h1h2.json", "KB5-servo-simulation.md",
    "ApiChecklist.md", "CapabilityMatrix.md", "_tmp_tablecheck.py", "probe_out.txt",
    "C1_periodic.csv", "C1_p2p.csv",
]


def git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


HEADS = {n: git(r, "ls-files").splitlines() for n, r in REPOS.items()}

for bn in BASENAMES:
    hits_head, hits_wt = [], []
    for n, repo in REPOS.items():
        for f in HEADS[n]:
            if os.path.basename(f).lower() == bn.lower():
                hits_head.append(f"{n}:{f}")
        for dp, dns, fns in os.walk(repo):
            dns[:] = [d for d in dns if d not in (".git", "__pycache__", "node_modules", ".venv")]
            for fn in fns:
                if fn.lower() == bn.lower():
                    hits_wt.append(f"{n}:" + os.path.relpath(os.path.join(dp, fn), repo).replace("\\", "/"))
    tag = "HEAD 有" if hits_head else ("仅工作树" if hits_wt else "**三仓皆无**")
    print(f"  {bn:<34} {tag}")
    for h in hits_head[:3]:
        print(f"      HEAD: {h}")
    for h in sorted(set(hits_wt) - set(hits_head))[:3]:
        print(f"      工作树: {h}")
