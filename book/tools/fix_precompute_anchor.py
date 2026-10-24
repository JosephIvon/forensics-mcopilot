#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_precompute_anchor.py —— precompute 脚本的 axiscope 段改为**按锚点读**（2026-10-22）。

bug：脚本标题写着"axiscope（书中锚点 @b95ffb2）"，实际却读工作树 ——
而锚点之后 KB0 改了 +7/-3、docs 多了 7 篇 wiki，工作树读数（KB 8145 / docs 27）
与锚点真值（KB 8141 / docs 20）不同。书里的数字只能来自锚点。
"""
import io
import sys

P = r"%WORKSPACE%\forensics-learning-book\tools\precompute_frontback_facts.py"
t = io.open(P, encoding="utf-8").read()

old_helper = """def git(root, *args):"""
new_helper = '''AXI_REV = "b95ffb2"  # 书中锚点：规模数一律按此 commit 读，不读工作树


def ax_lines(rel):
    """axiscope 在锚点处的文件行（相对仓库根）。"""
    import subprocess
    r = subprocess.run(["git", "-C", AXI, "show", f"{AXI_REV}:{rel}"],
                       capture_output=True)
    if r.returncode:
        return None
    return r.stdout.decode("utf-8", "replace").splitlines()


def ax_files(subdir, ext):
    """axiscope 在锚点处的文件清单（相对仓库根）。"""
    import subprocess
    r = subprocess.run(["git", "-C", AXI, "-c", "core.quotepath=false", "ls-tree", "-r",
                        "--name-only", AXI_REV, subdir], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.endswith(ext)]


def git(root, *args):'''

if t.count(old_helper) != 1:
    print(f"[SKIP] 助手插入点命中 {t.count(old_helper)} 次")
    sys.exit(1)
t = t.replace(old_helper, new_helper)

old_sec = '''print("\\n【二】axiscope（书中锚点 @b95ffb2）")
group([os.path.join(AXI, "docs", "contracts")], ".md", "契约 C1-C7")
group([os.path.join(AXI, "docs", "kb")], ".md", "知识库 KB0-KB8")
group([os.path.join(AXI, "src", "axiscope")], ".py", "src/axiscope 实现")
group([os.path.join(AXI, "tests")], ".py", "tests 测试")
group([os.path.join(AXI, "synth")], ".py", "synth 合成被控对象")
group([os.path.join(AXI, "bench")], ".py", "bench runner 与构造")
docs_all = [os.path.join(dp, f) for dp, _dn, fn in os.walk(os.path.join(AXI, "docs"))
            for f in fn if f.endswith(".md")]
print(f"  docs md: {len(docs_all)} 件（实存）")
cases = lines_of(os.path.join(AXI, "bench", "cases.jsonl"))
print(f"  bench 用例: {len([c for c in cases if c.strip()])} 例")
hid = lines_of(os.path.join(AXI, "bench", "hidden.sha256"))
print(f"  hidden.sha256: {len([c for c in hid if c.strip() and not c.strip().startswith('#')])} 条冻结摘要"
      f"（注释行 {len([c for c in hid if c.strip().startswith('#')])} 行）")
agent = os.path.join(AXI, "src", "agent")
n_agent = sum(len(fn) for _dp, _dn, fn in os.walk(agent)) if os.path.isdir(agent) else 0
print(f"  src/agent: {n_agent} 个文件（目录{'存在' if os.path.isdir(agent) else '不存在'}）")'''

new_sec = '''print(f"\\n【二】axiscope（书中锚点 @{AXI_REV} —— 一律按锚点读，不读工作树）")


def ax_group(subdir, ext, label):
    """按锚点统计某目录下的件数 / 物理行 / 非空行。"""
    fs = ax_files(subdir, ext)
    phys = ne = 0
    for f in fs:
        ls = ax_lines(f) or []
        phys += len(ls)
        ne += sum(1 for x in ls if x.strip())
    print(f"  {label}: {len(fs)} 件 ｜ 物理行 {phys} ｜ 非空行 {ne}")
    return fs


ax_group("docs/contracts", ".md", "契约 C1-C7")
ax_group("docs/kb", ".md", "知识库 KB0-KB8")
ax_group("src/axiscope", ".py", "src/axiscope 实现")
ax_group("tests", ".py", "tests 测试")
ax_group("synth", ".py", "synth 合成被控对象")
ax_group("bench", ".py", "bench runner 与构造")
docs_all = ax_files("docs", ".md")
print(f"  docs md: {len(docs_all)} 件（锚点处实存；主体 {len([d for d in docs_all if '/wiki/' not in d])} 件"
      f" + wiki {len([d for d in docs_all if '/wiki/' in d])} 件）")
cases = ax_lines("bench/cases.jsonl") or []
print(f"  bench 用例: {len([c for c in cases if c.strip()])} 例")
hid = ax_lines("bench/hidden.sha256") or []
print(f"  hidden.sha256: {len([c for c in hid if c.strip() and not c.strip().startswith('#')])} 条冻结摘要"
      f"（注释行 {len([c for c in hid if c.strip().startswith('#')])} 行）")
agent_files = ax_files("src/agent", "")
print(f"  src/agent: {len(agent_files)} 个文件（锚点处）")'''

if t.count(old_sec) != 1:
    print(f"[SKIP] axiscope 段命中 {t.count(old_sec)} 次")
    sys.exit(1)
t = t.replace(old_sec, new_sec)
io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("[OK] precompute 的 axiscope 段已改为按锚点读")
