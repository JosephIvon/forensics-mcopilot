#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_refs_heads.py —— 多仓"文档说的 vs HEAD 有的"一致性检查器（2026-10-22，批 B 用）。

比上一版 probe 严谨的地方（上一版有假阳性，当场修）：
  · 去掉 `:行号` / `:行号-行号` 后缀再当路径查；
  · 展开 `{a,b}` 花括号列���；
  · 跳过 glob（`*`）与占位（`<...>`）；
  · **跨仓引用不算缺失**：各仓互有引用，路径可能在另一个仓里；
  · 区分三类：HEAD 有 / 仅工作树有（生成物或未入库）/ 各仓都没有（**真断链**）。

口径：以 HEAD 为准（`git ls-files`）。工作树里有而 HEAD 没有的，公开后读者同样拿不到。

四个解析根（2026-10-24 电子书并入代码仓后新增 book/ 一层）：
  · mcopilot —— 代码仓根（src/ knowledge/ tests/ ...）
  · book     —— 电子书本体（chapters/ tools/ decision-lists/ ...），**嵌在** mcopilot 仓内
  · axiscope / trae_factory —— 同级的另外两个工程仓
嵌套关系下 book/ 的文件只由 book 那一轮扫（解析根不同，混扫会出假断链）。
"""
import io
import os
import re
import subprocess
import sys
# 本脚本要往 stdout 打中文。控制台编码不是 UTF-8 时，`print` 会抛
# UnicodeEncodeError —— 脚本于是**崩在打印上**，而不是给出判定。
# 2026-10-24 在 GitHub Actions runner 上实测：那边控制台是 cp1252，
# 本机是 UTF-8 —— 于是本机绿、runner 红。处置与本仓其他脚本一致
# （见 scripts/verify_doc_refs.py、scripts/fault_farm.py）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 环境相关
    pass

# 仓根定位：从本文件位置反推，目录改名 / 搬家不用改这里。
#   <repo>/book/tools/check_doc_refs_heads.py
#   <repo>/book/     ← BOOK      电子书本体（自带 .gitattributes，仓根相对引用在这一层解析）
#   <repo>/          ← REPO_ROOT mcopilot 代码仓根（src/ knowledge/ tests/ ...）
#   <repo>/../       ← WS       axiscope / trae_factory 的同级目录
# 环境变量可覆盖（CI / 别的机器上用）：
#   MCOPILOT_REPO / BOOK_REPO / AXISCOPE_REPO / TRAE_REPO
HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(BOOK)
WS = os.path.dirname(REPO_ROOT)


def _repo(env, default):
    p = os.environ.get(env)
    return os.path.abspath(p) if p and os.path.isdir(p) else default


REPOS = {
    "mcopilot": _repo("MCOPILOT_REPO", REPO_ROOT),
    "book": _repo("BOOK_REPO", BOOK),
    "axiscope": _repo("AXISCOPE_REPO", os.path.join(WS, "axiscope")),
    "trae_factory": _repo("TRAE_REPO", os.path.join(WS, "trae_factory")),
}

# 哪些仓**在位**？在位 = 目录存在，且里面**有东西可核**（自己的 .git，或者至少一个文件）。
#   · book/ 自 2026-10-24 并仓后**不再有自己的 .git** —— 它是 mcopilot 仓里的一个目录，
#     由"未入库文件"那条路被扫到（见下面的 docs 收集），所以它算在位。
#   · axiscope / trae_factory 是独立仓，不随本仓发布；干净检出上不在位。
# 缺仓时，"在任何一个仓都找不到这条路径"**不能**判成真断链——
# 那条路径很可能就在缺的那个仓里。照旧判死，CI 第一次跑就是红的，
# 读者也会拿到一份"全是断链"的假报告。
#
# 处置：缺仓时找不到的路径归入「缺仓不可判定」——**不判 FAIL，但必须喊出来**。
# 全仓在位时口径不变（严判，真断链必须为 0）。
def _looks_present(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    if os.path.isdir(os.path.join(path, ".git")):
        return True
    try:
        for _dp, _dns, fns in os.walk(path):
            if fns:
                return True
    except OSError:
        return False
    return False


PRESENT = {name: _looks_present(p) for name, p in REPOS.items()}
MISSING_REPOS = [n for n, ok in PRESENT.items() if not ok]

# 嵌套仓：book/ 在 mcopilot 仓内独立成根。外层扫描必须跳过它，
# 否则同一篇章节会被扫两遍、且两遍的解析根不同 → 假断链。
NESTED_SKIP = {"mcopilot": ("book/",), "book": ()}
TOP = (r"(?:docs|scripts|src|knowledge|data|bench|gen|tests|out|samples|examples|synth|"
       r"tools|\.github|out_v_unique)")
# 后缀**长的在前**（json 必须排在 js 之前，否则 "*.json" 被截成 "*.js"）
EXT = r"(?:jsonl|json|yaml|yml|html|toml|ipynb|md|csv|py|ps1|js|ts|exe|dll|txt|ini|log|md)"
PATH = re.compile(r"((?<![\w/])" + TOP + r"/[A-Za-z0-9_\-./{}*]*\." + EXT + r"(?::[\d,\-]+)?)")
LINESUF = re.compile(r":[\d,\-]+$")


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or "").strip()


def expand_braces(p):
    m = re.search(r"\{([^{}]*)\}", p)
    if not m:
        return [p]
    out = []
    for opt in m.group(1).split(","):
        out += expand_braces(p[:m.start()] + opt.strip() + p[m.end():])
    return out


def norm(raw):
    """去掉行号后缀、展开花括号、跳过 glob/占位。"""
    cands = []
    for one in expand_braces(raw):
        one = LINESUF.sub("", one).strip().replace("\\", "/")
        if not one or "*" in one or "<" in one or ">" in one:
            continue
        if one.endswith("/"):
            continue
        cands.append(one)
    return cands


HEADS = {name: set(f for f in git(repo, "ls-files", "-z").split("\0") if f)
         for name, repo in REPOS.items()}   # -z：中文路径不加引号（否则整批中文名文件漏检）
WORKTREE = {}
for name, repo in REPOS.items():
    s = set()
    for dp, dns, fns in os.walk(repo):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__", "node_modules", ".venv")]
        for fn in fns:
            s.add(os.path.relpath(os.path.join(dp, fn), repo).replace("\\", "/"))
    WORKTREE[name] = s

def _historical_paths(repo, name):
    """该仓 git 历史里**出现过**的所有路径（改名/删除前的也算）。

    嵌套仓要特别处理 ✓：book/ 在 mcopilot 仓内，`git -C book log --name-only`
    给出的是**外层仓根**的相对路径（`book/xxx.md` ✓），
    而本仓的坐标是**仓根**相对（`xxx.md` ✓）→ 不处理就会口径错位 ✓，
    把书里引用的 `src/mcopilot/...` 误判成「历史残留」（实测 182 条假断链 ✓）。
    """
    out = git(repo, "log", "--all", "--name-only", "--format=")
    paths = {ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()}
    if name == "book":
        prefix = "book/"
        paths = {p[len(prefix):] for p in paths if p.startswith(prefix)}
    return paths


# 只对**在位仓**取历史：缺的那个仓连目录都没有，历史无从取起。
HISTORY = {name: (_historical_paths(repo, name) if PRESENT.get(name) else set())
           for name, repo in REPOS.items()}


def _in_history(ref):
    """这条路径是不是「在位仓的历史里有、现在 HEAD 与工作树都没有」的残留？

    这正是「本仓改名/删除文件后残留的引用」✓ —— 兄弟仓在不在位与它无关 ✓。
    """
    return any(ref in paths for paths in HISTORY.values())


def ignored_prefixes(repo, extra_gitignore=None):
    """从 .gitignore 解析"声明不入库"的顶层目录（如 out/*）——这些路径不是断链，是生成物位置。

    extra_gitignore：嵌套仓（book/）实际受**外层仓根**的 .gitignore 约束，
    所以外层那份也要一起读，否则 out/ 这类会被误判成"真断链"。
    """
    out = set()
    gis = [os.path.join(repo, ".gitignore")]
    if extra_gitignore:
        gis.append(extra_gitignore)
    for gi in gis:
        if not os.path.isfile(gi):
            continue
        for ln in io.open(gi, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln or ln.startswith("#") or ln.startswith("!"):
                continue
            ln = ln.split("#")[0].strip().rstrip("/")
            if not ln:
                continue
            if "*" in ln or "?" in ln:
                ln = ln.split("*")[0].split("?")[0]
            ln = ln.rstrip("/")
            if "/" in ln:
                out.add(ln)          # data/incoming/** 这样的多级前缀
            else:
                out.add(ln + "/")    # out/* 这样的顶层目录
    return out


IGNORED = {name: ignored_prefixes(repo, os.path.join(REPO_ROOT, ".gitignore")
                                  if name == "book" else None)
           for name, repo in REPOS.items()}
TRUE_GAPS, ONLY_WT, CROSS = [], [], []
COUNTER_EX = []
REL_OK = []
RECORD = []
IGNORED_HITS = []
UNDECIDED = []          # 缺仓导致的不可判定引用（不算断链，但必须喊）
# 反例引用识别：行内明说该路径不存在（教材式举反例 / 事故记要的"缺失即证据"）
COUNTER = re.compile(r"不存在|一个都|从未|未进|未入库|不入库|缺失|不在仓|没有.*(?:进|在)仓|已被清|清理|删除|已删|拆成|"
                     r"取代|不再|过期|草稿|曾引用|实际落盘路径|复算脚本未入库|本地.*产物.*不入库|"
                     r"更名为|已更名|改名|原名|曾名|旧名|原为|落点")
for name, repo in REPOS.items():
    tracked = [f for f in git(repo, "ls-files", "-z").split("\0") if f]
    untracked = [f for f in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if f
                 if f.lower().endswith((".md", ".json")) and not f.startswith("out/")]
    docs = sorted(set(f for f in tracked
                      if f.lower().endswith((".md", ".json")) and not f.startswith("out/")
                      and not any(f.startswith(pref) for pref in NESTED_SKIP.get(name, ())))) \
        + [f for f in untracked
           if not any(f.startswith(pref) for pref in NESTED_SKIP.get(name, ()))]
    for rel in docs:
        p = os.path.join(repo, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        lines = txt.splitlines()
        for i, line in enumerate(lines, 1):
            # 分型看**本行 + 下一行**：文档里"说明在下一行"是常态
            # （例：「上一路废稿 `scripts/x.py` … 已删除」——"已删除"在下一行）
            ctx = line + ("\n" + lines[i] if i < len(lines) else "")
            for m in PATH.finditer(line):
                for ref in norm(m.group(1)):
                    if ref in HEADS[name]:
                        continue
                    # 相对路径：相对**所在文件目录**解析（README 里写 docs/X.md 可能指同目录）
                    rel_dir = os.path.dirname(rel)
                    if rel_dir:
                        cand = (rel_dir + "/" + ref).replace("//", "/")
                        if cand in HEADS[name] or cand in WORKTREE[name]:
                            REL_OK.append((name, rel, i, ref))
                            continue
                    # 记录性引用：校验报告里的历史 path/file 字段（记录当时的事实，不是声称现在有）
                    if re.search(r'"(?:path|file|raw_file|original)"\s*:\s*"' + re.escape(ref) + r'"', line):
                        RECORD.append((name, rel, i, ref))
                        continue
                    in_other = [o for o in REPOS if ref in HEADS[o]]
                    if in_other:
                        CROSS.append((name, rel, i, ref, in_other))
                        continue
                    if any(ref.startswith(p) for p in IGNORED[name]):
                        # .gitignore 声明的不入库区（out/ 等）：生成物位置，不是断链
                        IGNORED_HITS.append((name, rel, i, ref))
                        continue
                    # **工作树归属先于断链判定**：这条路径可能在**别的仓**的工作树里
                    # （合并/嵌套布局下很常见：书里写的是代码仓的仓根相对路径，
                    #  而那个仓还没提交 → HEAD 没有、工作树有）。
                    # 那种情况不是"链接失效"，是"那个仓还没入库"——归到「仅工作树」，
                    #  并记下归属仓；只有**所有仓**的 HEAD 与工作树都没有，才算真断链。
                    owner = [o for o in REPOS if ref in WORKTREE[o]]
                    if owner:
                        ONLY_WT.append((name, rel, i, ref, owner))
                        continue
                    # 反例引用：这一行**明说**该路径不存在（教材式举反例），不算断链
                    if COUNTER.search(ctx):
                        COUNTER_EX.append((name, rel, i, ref))
                    elif _in_history(ref):
                        # **历史残留**：这条路径在在位仓的 git 历史里存在过
                        # （改名/删除前它在那儿），现在 HEAD 与工作树都没有 →
                        # 这就是「本仓改名/删除文件后残留的引用」。
                        # 它与兄弟仓在不在位**无关**：缺仓不能给本仓的断链开脱。
                        # （原先所有「找不到」都归「缺仓不可判定」，于是 CI 上
                        #  TRUE_GAPS 结构性不可达——这道门的检测力只存在于本地，
                        #  从不存在于 CI。）
                        TRUE_GAPS.append((name, rel, i, ref))
                    elif MISSING_REPOS:
                        # 有仓不在位 → 这条路径可能在缺的那个仓里，判死是冤枉
                        UNDECIDED.append((name, rel, i, ref))
                    else:
                        TRUE_GAPS.append((name, rel, i, ref))

print("=" * 92)
print("【一】真断链（各仓 HEAD 与工作树都没有）——必须清偿")
print("=" * 92)
if MISSING_REPOS:
    print(f"  ⚠ **缺仓**：{'、'.join(MISSING_REPOS)} 不在位（独立仓，不随本仓发布）。")
    print("     缺仓期间「所有仓都找不到」的路径一律归【八】不可判定，**不判死链**。")
    print("     但**历史残留**（在位仓的 git 历史里有、现在 HEAD 与工作树都没有）仍判死链 ——")
    print("     那是本仓改名/删除文件后残留的引用，与兄弟仓在不在位无关 ✓。")
for name, rel, i, ref in TRUE_GAPS:
    print(f"  ✗ [{name}] {rel}:{i}  →  {ref}")
print(f"  小计：{len(TRUE_GAPS)} 处")

print()
print("=" * 92)
print("【二】仅工作树有（生成物 / 未入库）——公开后读者拿不到，需补指针或补入库")
print("=" * 92)
agg = {}
for name, rel, i, ref, owner in ONLY_WT:
    agg.setdefault((name, ref, owner[0] if owner else "?"), []).append(f"{rel}:{i}")
for (name, ref, owner), srcs in sorted(agg.items())[:40]:
    print(f"  · [{name}] {ref}   ← {len(srcs)} 处（{', '.join(srcs[:3])}）   归属仓：{owner}")
print(f"  小计：{len(agg)} 个不同路径")

print()
print("=" * 92)
print("【三】跨仓引用（路径在另一个仓里）——不算断链，但公开后要能指过去")
print("=" * 92)
agg2 = {}
for name, rel, i, ref, other in CROSS:
    agg2.setdefault((name, ref, other[0]), []).append(f"{rel}:{i}")
for (name, ref, other), srcs in sorted(agg2.items()):
    print(f"  ↔ [{name}] {ref}  →  {other} 仓   ← {len(srcs)} 处（{', '.join(srcs[:2])}）")
print(f"  小计：{len(agg2)} 个不同路径")

print()
print("=" * 92)
print("【四】反例引用（行内明说不存在）——不算断链，供人工确认")
print("=" * 92)
for name, rel, i, ref in COUNTER_EX:
    print(f"  ○ [{name}] {rel}:{i}  →  {ref}")
print(f"  小计：{len(COUNTER_EX)} 处")

print()
print("=" * 92)
print("【五】相对路径（相对所在目录解析，命中）——不算断链")
print("=" * 92)
for name, rel, i, ref in REL_OK:
    print(f"  ↪ [{name}] {rel}:{i}  →  {ref}")
print(f"  小计：{len(REL_OK)} 处")

print()
print("=" * 92)
print("【六】记录性引用（校验报告里的历史 path 字段）——不算断链")
print("=" * 92)
for name, rel, i, ref in RECORD:
    print(f"  ▷ [{name}] {rel}:{i}  →  {ref}")
print(f"  小计：{len(RECORD)} 处")

print()
print("=" * 92)
print("【七】不入库区路径（.gitignore 声明，如 out/）——不是断链，但公开后读者拿不到")
print("=" * 92)
agg7 = {}
for name, rel, i, ref in IGNORED_HITS:
    agg7.setdefault((name, ref), []).append(f"{rel}:{i}")
for (name, ref), srcs in sorted(agg7.items()):
    print(f"  ∅ [{name}] {ref}   ← {len(srcs)} 处（{', '.join(srcs[:2])}）")
print(f"  小计：{len(agg7)} 个不同路径")

print()
print("=" * 92)
print("【八】缺仓不可判定（路径在不在位的仓里，本机无从核）——不是断链，但本机核不了")
print("=" * 92)
agg8 = {}
for name, rel, i, ref in UNDECIDED:
    agg8.setdefault((name, ref), []).append(f"{rel}:{i}")
for (name, ref), srcs in sorted(agg8.items()):
    print(f"  ? [{name}] {ref}   ← {len(srcs)} 处（{', '.join(srcs[:2])}）")
print(f"  小计：{len(agg8)} 个不同路径"
      + (f"　（缺仓：{'、'.join(MISSING_REPOS)}）" if MISSING_REPOS else ""))

print(f"\n真断链 {len(TRUE_GAPS)} ｜ 仅工作树 {len(agg)} ｜ 跨仓 {len(agg2)} "
      f"｜ 反例引用 {len(COUNTER_EX)} ｜ 相对路径 {len(REL_OK)} ｜ 记录性 {len(RECORD)} "
      f"｜ 不入库区 {len(agg7)} ｜ 缺仓不可判定 {len(agg8)}")
if MISSING_REPOS:
    print(f"在位仓：{'、'.join(n for n, ok in PRESENT.items() if ok)}"
          f"　｜　缺仓：{'、'.join(MISSING_REPOS)}")
sys.exit(1 if TRUE_GAPS else 0)
