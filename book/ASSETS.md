# ASSETS · 素材登记表（本书唯一证据层）

> 原则：书的证据层 = **耐久工件**。会话是进行时过程产物，只作叙事素材
> （正文标"作者亲历"），不进证据链、不设引用坐标、不留快照。

## 一、耐久工件

### 本仓（引用锚定 commit `285da78`）

> 锚点从旧工作副本 `mcopilot@b53ac62` 切到**本仓** `285da78`（2026-10-24）：
> 旧仓是发布前的工作副本，**读者手里没有**——坐标锚在读者拿不到的仓里，
> 等于「只对作者可核」。锚点必须落在读者 clone 下来就有的那个仓。

| 工件 | 供章 |
|---|---|
| `docs/项目回顾与收尾_20261021.md` | 第1章 |
| `docs/TODO需实测_协议域.md`（T1-T5 显式挂起） | 第2章 |
| `knowledge/protocols/anchors.json`（17 锚点） | 第2章 |
| `scripts/gate_protocol.ps1`（G1-G12）+ `gate_negative.ps1` | 第3章 |
| `docs/评审_Trae修复.md`→`评审_Trae修复验证.md`→`评审_Trae修复_二轮.md`（修复→独立复核→主控落地） | 第3/7章 |
| `docs/协议提取SOP.md` + `knowledge/contracts/comm_log_contract.json` + `scripts/validate_comm_log.py` | 第4章 |
| `scripts/fault_farm.py` + `scripts/lemay_corpus.py` + `docs/kb3_判据抽取.md` + issues_corpus | 第5章 |
| `src/mcopilot/agents/forensics_comm.py`（7 规则）+ `knowledge/protocols/failure_signatures.json` + `scripts/onboard_loop.py` + `scripts/eval_forensics.py` | 第6章 |
| `evidence/MANIFEST.txt`（134 分流+损失实录）——**仓外原件的入库副本**，逐行不变，
  见 `evidence/README.md` | 第7章 |
| `docs/事故_G6幽灵功能_20261022.md`（立照 `58d685f`）+ 修复 `5563b51`/`0cfc358` | 第3章 案三 |

### 记忆与台账（`%USERPROFILE%\self-improving\`）

| 工件 | 供章 |
|---|---|
| `memory.md`（章程头 + 条目 1-17 + 候选区） | 第8章 |
| `ledger.md`（应用台账 + 决策清单索引） | 第9章 |

### 本书自有工件

| 工件 | 供章 |
|---|---|
| `decision-lists/mcopilot-b53ac62.md`（首份决策清单，R1 四件套首战） | 第9章 / 卷三第一篇 |
| `decision-lists/mcopilot-353182e.md`（**第二份决策清单，R1 四件套第二战**：公开前审第一批——收尾 4 项未提交逐件定性（3 入库 / 1 退回）+ 账实相符清偿 41 处真断链→0；否决 V5–V8、边界 B5–B7、真值 T5–T7、诚实账 C4–C7） | 第9章 / 卷三第一篇 |
| `chapters/ch03-门禁与负向测试.md`（样章，格式定版） | 第3章 |
| `chapters/ch01/ch02/ch04/ch05/ch06/ch07/ch08/ch09`（M4 六章 + M5 两章验算流，坐标审计过审） | 各章 |
| `crops/裁剪版.md`（163 行）（**单件合并裁剪**：九章的「可验证主张」+「讲师 90 分钟」两段原样裁出；2026-10-24 由两件——简历版 / 讲师版——合并为一件，求职口径已删，理由见该件「为什么只有一版」一节） | 输出件 |
| `前言.md`（书级前言：**写给读者的建议** / 这本书在解决什么 / 这一本书讲什么，以及为什么只有一本 / 全书路线 / 五条硬纪律 / 怎么验这本书 / 不承诺什么 / 三种读法） | 书级 |
| `尾声.md`（书级尾声：写给读者 / 这一场战役的收尾 / 诚实账三张表 / 三条最贵的教训 / 欠账挂账） | 书级 |
| `chapters/00-导读.md`（卷首导读：写给读者的建议 / 三段路线 / 九章速查表 / 三种读法 / 关于坐标，64 行） | 卷首导读 |
| `tools/audit_vol2_coords.py`（坐标审计器：**按锚点 commit 读源文件**而非工作树；覆盖 12 个文件（卷一 9 章 + 1 份卷首导读 + 前言 + 尾声）272 引用 0 失败；支持 C1–C7 与 KB0–KB8 别名、区间行号、跨仓消歧、尾路径匹配）、`tools/fix_vol2_anchors.py`（锚点清偿）、`tools/build_crops.py`（**单件裁剪生成器**，仓根从 `__file__` 反推）、`tools/verify_crops_verbatim.py`（裁剪件逐行"原样"核验 + 求职口径复查）、`tools/check_vol2s_structure.py`（**1 卷 + 1 份导读 + 前后记**结构体检；必备件含承接段与证据区，违禁项含裸行号与会话坐标）、`tools/verify_book_numbers.py`（**核书里带文件名的数字**：文件长过、行号没跟着走时，坐标门禁只查『行号在不在范围内』会放行——这道门禁查的是**数字本身对不对**）、`tools/precompute_frontback_facts.py`（规模数亲跑，**axiscope 段按锚点读**；章与导读分列计行）、`tools/machine_ize_all_bare_refs.py` + `tools/attribute_bare_refs.py`（裸行号机判化与归属核对）、`tools/arrange_content_data.py` + `tools/arrange_apply.py`（编排改造②中档：承接段与坐标块下沉） | 全书生产工具链 |
| `tools/check_doc_refs_heads.py`（**账实相符检查器**：按各仓 `HEAD` 核文档里的路径引用，**八类**分流——真断链 / 仅工作树有 / 跨仓引用 / 反例引用 / 相对路径 / 记录性引用 / 不入库区 / 缺仓不可判定；只有「真断链」判失败；同级独立仓（`axiscope` / `trae_factory`）不在位时归【八】不判死链，否则干净检出上 CI 首跑必红；`.gitignore` 声明的不入库区（`out/` 等）单列为"公开后读者拿不到"；首跑 41 处真断链 → 清偿后 0）、`tools/scan_absolute_paths.py`（**脱敏门禁**：扫家目录/用户名与本机工作区路径，公开前必清零；便携 + 扫工作树，`--tracked` / `--all`）、`tools/_localenv.py`（**路径占位符解析**：`%USERPROFILE%` / `%WORKSPACE%` → 实路径，仓根与工作区从 `__file__` 反推）、`tools/fix_batch_b_doc_gaps.py`（mcopilot 定点清偿 26 处，精确串+命中次数断言，次数不符即退出）、`tools/verify_batch_b_edits.py`（清偿后复验：JSON 解析 / 关键字段 / 行数零漂移）、`tools/verify_codewiki_numbers.py` + `tools/verify_codewiki_numbers2.py` + `tools/verify_codewiki_tree.py`（CodeWiki 数字逐个本机亲跑）、`tools/fix_codewiki_numbers.py`（订正 8 处过期计数）、`tools/probe_exe_rebuild.py`（exe 重建 vs 元数据抖动的判据）、`tools/probe_codewiki_numbers.py`、`tools/probe_gap_windows.py`、`tools/dump_gap_lines.py`、`tools/show_gap_context.py`、`tools/find_missing_artifacts.py`、`tools/probe_doc_head_consistency.py`、`tools/probe_counter_regex.py`、`tools/verify_codewiki_numbers3.py`、`tools/toggle_readme_outnote.py`（分笔提交用行开关） | 公开前审工具链 |
| `tools/split_vol2_into_two.py`（卷二拆两册：git mv + 章内 §编号重编 60 处）、`tools/fix_section_ranges.py`（区间断链 3 处定点清偿）、`tools/fix_vol2_count_koujing.py`（计数口径更正 4 处）、`tools/fix_ch04_machine_coords.py`、`tools/fix_ch04_machine_coords2.py`、`tools/fix_ch06_07_03_machine_coords.py`（裸行号坐标机判化 18+2 处）、`tools/fix_ch03_cross_repo_anchor.py`（官方物证落点跨仓锚更正） | 拆册与清偿工具链 |

### 锚点变更登记

- [2026-10-22 收尾] **trae_factory@`2da4559`**（卷二底稿）：71 条未提交逐件裁决
  清零入库——真值链全量接入（truth_kb 死路径修复，58 条 P/Invoke 全挂
  [源|核对|提取]标注）、ACS 品牌套件、TruthChain/JointEval 文档层、
  out_v_unique 29 件迁居登记。跨仓真值桥当日验算全 [OK]，全品牌再生退出码 0。
  未结清：五品牌套件 TruthChain 完整度未逐份复核（决策清单 C2）。
  决策清单：`decision-lists/trae_factory-2da4559.md`。
- [2026-10-22 收尾] **axiscope@`36e2c74`**（卷二/卷三底稿；comm_log 契约纪律与
  servo 判据的权威上游）：收尾文档 `docs/项目回顾与收尾_20261022.md` 入库，
  403 项测试当日亲验全过。诚实账三笔在案：脱敏未完成、KB7 标题不一致未裁决、
  真机波次 0（设计性挂起）。决策清单：`decision-lists/axiscope-36e2c74.md`。
  **清偿延伸锚点**：trae_factory `954c210`（五品牌 TruthChain 刷新）；axiscope
  `adf4c4b`（脱敏执行 + KB7 裁决，收尾文档第七节追记）——原三笔未结清项
  当日全部清账，仅剩真机波次维持设计性挂起。
- [2026-10-22 午后] mcopilot 主线修复四连：`58d685f`（事故立照）→ `5563b51`
  （G6 修复）→ `0cfc358`（路径清偿）→ `01eb884`（账本 path 清偿）。
  **已核全部被引素材文件在 b53ac62→01eb884 区间零变更**（jd.py/路径脚本/
  coverage_ledger.json 均不在本书被引清单），全书锚点维持 `b53ac62` 不变。

- [2026-10-22 本轮·作者三问「闭环？code-review？传 GitHub？」] **mcopilot 收尾两笔**：
  `5d7321a`（收尾：固高适配器入树图、回归计数 332→387、`docs/CodeWiki_20261022.md`
  683 行入库并订正 8 处过期数字、**模板 exe 退回**——同源重建非代码变更：`.text` 段
  28868 相同，字节差异仅 PE 时间戳与编译器随机 GUID）
  → `353182e`（账实相符清偿：覆盖账本 9 处、PROVENANCE 7 处、5 份 truth.json、
  focas/模板 README/根 README）。
  **全书锚点维持 `b53ac62` 不变**（动锚点要重验 697 个坐标，收益远小于代价）；
  新增 `tools/check_doc_refs_heads.py`：按 `HEAD` 核文档引用的路径，分六类
  （真断链/仅工作树/跨仓/反例/相对路径/记录性），并把 `.gitignore` 声明的不入库区单列
  ——首跑 **41 处真断链 → 清偿后 0**。门禁 G1–G12 全绿（12/12）；
  pytest 383 passed / 2 failed / 2 skipped（2 failed 为基线既有的控制台编码问题，非本轮引入）。
  决策清单：`decision-lists/mcopilot-353182e.md`。

- [2026-10-22 本轮·作者三项授权] **axiscope 锚点后的变更与审计口径**：
  锚点 `7b0fd88` 之后仓内又有提交（HEAD `a57e67b`）：`docs/kb/KB0-conventions.md` +7/-3、
  新增 `docs/wiki/` 7 篇（合计 518 行）。**书内规模数一律按锚点口径**
  （KB 8 件 = 8141 物理行、docs md 实存 20 件 = 主体 19 + 收尾文档 1，wiki 0 件）；
  工作树读数为 KB 8145 / docs 27，**不是书的数**。审计器同步改为**按锚点 commit 读源文件**
  （`git show <rev>:<path>`），否则"行还在"会判 [OK] 却指的是另一行，0 失败成假话。
  审计根目录新增 `mcopilot-pending-20261022`（MANIFEST）、`%USERPROFILE%\self-improving`
  （memory.md / ledger.md）、`mcopilot-external`（厂商原件 `LTDMC.cs`）——
  三处原为"仓外原件指针"，现已全部可解析。
  本轮坐标机判化后**全书裸行号清零**（清点正则由 "`:\d+`" 改为 "`:\d+(?:-\d+)?`"，
  前者漏掉区间写法）。
- [2026-10-22 本轮] 书级前后记（`前言.md` / `尾声.md`）首次落盘，并纳入坐标审计与结构体检。
- [2026-10-22 本轮] **编排改造②中档**（作者签"②中档 + 前言尾声同步改读者导览"）：
  - 新增卷首导读页（`chapters/00-导读.md` 64 行），内容为读者导览：写给读者的建议 → 分部路线 →
    逐章速查表 → 三种读法 → 坐标说明；**不入证据层**（导读只指路，不引新事实），
    但入坐标审计与结构体检。
  - 9 章章首统一加「**本章承接 / 学完你会 / 前置**」三行（逐章手写，贴该章主张与动手节）。
  - 9 章章首的「素材坐标 / 已验算」块**下沉**至章末新小节「## 证据与坐标」，
    章首只留「可验证主张 / 讲师切分」指针行；**正文论证、坐标内容、习题、可验证主张、
    讲师切分、尾注坐标清单一律未动**。
  - 《前言》改写为读者导览（新增"写给读者的建议"与"全书路线"两节，原七节保留）；
    《尾声》新增"写给读者"开场。
  - 由此产生的行数变化（物理行，章与导读分列）：9 章 2079 + 导读 64 = 2143。

- [2026-10-24 改锚] **坐标锚点从旧工作副本切到本仓**（`b53ac62` → `285da78`）：
  - **为什么切**：旧仓 `mcopilot` 是发布前的工作副本，**不随本仓公开**。
    坐标锚在读者拿不到的仓里，「当场可核」就只剩作者能做——而这正是本书要证伪的那件事。
    故锚点改指**读者 clone 下来就有的那个仓**（本仓 `285da78`）。
  - **切锚不是改一行字符串**：审计器的锚点读取是 `git show <rev>:<path>`，
    切过去以后要重验全部坐标（引用 272 / 可解析 272 / 失败 0）。
    另修一处**会静默出假绿的坑**：锚点根切到本仓之后，`book/` 恰好落在锚点根下面——
    若不排除，书里对 `decision-lists/*.md` 的引用会被拿**上一次提交的文字**去核，
    核的是旧行号、报的是假结果。故 `anchored_read()` 显式排除本书仓：
    **书是活物，读工作树；只有代码读锚点。**
  - **仓外原件的处置**：`MANIFEST.txt`（134 条快照实录）原件在仓外的快照仓，读者拿不到。
    故把原件**逐行不变**地收进 `book/evidence/`（只脱敏本机绝对路径），
    并附 `evidence/README.md` 说明来龙去脉——**被引用的仓外原件要留证**，
    否则那条主张就只剩作者能核。
  - **历史陈述不动**：停机点 `b53ac62`、决策清单文件名 `mcopilot-b53ac62.md`、
    「0 未提交 @ b53ac62」这些是**当时的事实**，改它们就是篡改历史。
    改锚只动**锚点陈述**（坐标指向哪个 commit），不动**记录性陈述**。

- [2026-10-24 公开后硬化] **这条仓第一次推上 GitHub 就被自己的流水线打回三回**，
  每一回都不是"被测对象坏了"，而是**门禁自己没跑起来**：
  - **第 1 回**（红在 pytest）：`setup-python` 给的是**干净解释器**，里面没有 pytest，
    而 workflow 从来没装过依赖 → `No module named pytest` 退 1，后面九道门禁一步没跑。
    **徽章从第一次推送起就是红的**——本机却绿，因为本机早装好了。
    这就是本书反复说的那种最坏的形态：**绿的不是"门禁通过"，是"门禁没跑起来"**。
    修法：CI 装 `pytest` 与 `matplotlib`（本仓的 `dev` / `charts` 两个 extra），
    **不装本包**——装了就破坏"从仓库根直接 import mcopilot 应当不成立"这条布局契约。
  - **第 2 回**（红在 G11 故障农场）：runner 上只有 COM2，没有 com0com 的 COM3/COM4 对。
    农场的 RTU 前置探测里，串口层打不开口时抛的是 **`SystemExit`**，
    而 `SystemExit` 继承 `BaseException`——`except Exception` **接不住**，
    于是本该记 SKIP 的"环境缺席"把整个农场进程带崩。**缺席是环境事实，不是场景失败。**
  - **第 3 回**（红在锚点门禁）：runner 的控制台编码是 **cp1252**，本机是 UTF-8。
    门禁脚本往 stdout 打中文，`print` 遇编不出来的字符就抛 `UnicodeEncodeError`——
    **脚本崩在打印上，而不是给出判定**。实测有 **8 支**脚本如此（不止报错那一支）。
  - **三回都补了回归测试**（环境缺席、非 UTF-8 控制台、门禁自身的判定），
    并**逐条反向自测**：把修复抽掉，测试必须红；放回去，必须绿。
    这道工序的规矩是：**修复不配回归测试，就等于没修**——下一回还会换个实例再来。
  - **这三条进书吗？** 它们是 2026-10-24 的事后修补，**不是 2026-10-22 那场战役的内容**，
    所以正文一个字不动；这里只留**账**——读者要知道这本书的配套流水线是绿的，
    以及它曾经以什么方式不绿。

- [2026-10-24 并仓] **书随 mcopilot 仓开源**（`forensics-mcopilot/book/`）：
  - **只留与本仓代码对得上的一册**：另两册（axiscope / 代码工厂）的正文、导读、
    裁剪件与大纲随册移出本仓——判断标准是"哪本的坐标能在这份代码里核得到"，
    不是"哪本好看"。两册各自的收尾账留在本仓 `decision-lists/`，一条不少。
  - **裁剪件由两件合并为一件**（`crops/裁剪版.md`）：求职口径（简历版）删，
    主张与切分都留；生成器换为 `tools/build_crops.py`（仓根从 `__file__` 反推，不写死路径）。
  - **"简历句框"改称"可验证主张"**（9 章 39 处，前言 / 导读 / 裁剪件 / 结构体检同步改名）：
    开源后面对的是**一类开发者**，不是一个人的求职。
  - 规模数按实跑重记：正文 9 章 + 1 份卷首导读（物理行 2143）｜坐标 **272 引用 272 可解析 0 失败**
    ｜裁剪件 **1 件**｜工具 96 支 py｜决策清单 5 份。
  - 仓根解析改为**不依赖固定层数**（`core/util.py` 的 `_resolve_root()`）：
    写死 `parents[1]` 会在装成 wheel 后把根指到 `site-packages`；并附**可操作的报错**
    （本仓的分发单元是仓库不是 wheel）。这条契约由 `tests/test_layout_contract.py` 钉住。
  - **公开前脱敏**（481 处 → 0）：代码仓早在批 C 做过一轮绝对路径外置，**书没有**——
    于是书里留着 47 处家目录/用户名与 194 处本机工作区路径（外加一条会话 ID、
    一个浏览器 profile 路径）。
    处理方式：**脱敏而不删**——家目录前缀 → `%USERPROFILE%`，
    工作区前缀 → `%WORKSPACE%`（由 `tools/_localenv.py` 统一解析成"本仓的上一级"，
    因为同级仓就在那儿）。**删掉读者就看不出那是个路径**，而且没法照着跑。
    （**连这段说明自己也不写具体值**——写下"某某用户目录"的那一刻，
    泄露就重新发生了；`tools/scan_absolute_paths.py` 扫的就是这个。）
    配套：`tools/scan_absolute_paths.py` 改为**便携 + 扫工作树**（原来只扫已跟踪文件，
    第一次提交前扫出来是 0 处，显得干净），并加 `--tracked` / `--all`；
    仓根与工作区从 `__file__` 反推，不写死路径。
  - **书里仍在用的工具接上占位符展开**（`tools/_localenv.expand()`）：
    占位符**不会自己展开**——`r"%WORKSPACE%\axiscope"` 拿去当路径前缀会永远匹配不上，
    `anchored_read` 于是静默改读工作树，**锚点就失效了**（"0 失败"成假话）。
    历史的一次性脚本（`fix_*` / `probe_*`）已经跑完，其占位符就只是记录，不接。
  - **`docs/wiki/07-运行方式.md` 从 `book/wiki/` 移回 `docs/wiki/`**：
    它讲的是"怎么把这份代码跑起来"，属于**仓**不属于**书**；放在书里会让读者
    当成书的配套件。移回时逐条改正：CLI 域名 `jd` → `requirements`、
    MCP 工具名 `jd_map` → `requirements_map`、`pyproject.toml:10` → `:14`、
    回归测试 368 → 398、`file:///<工作区>/...` 本机链接 → 仓内相对路径、
    规划中但从未写成的 01–06 与总览 → **删掉占位死链**（本仓只有这一篇 Wiki）。
  - **新增第 2 道坐标门禁**（`scripts/verify_doc_refs.py`）：原来只查真值 CSV 的行号引用，
    **代码行号引用没人管**——`pyproject.toml:10` 就是这么烂掉的。
    新增：文件必须存在、行号必须在范围内；仓外原件区（厂商手册/头文件，不入本仓）
    单独归类但**照样核行号**（`LTDMC.cs:891` 因此被证明真的有 `dmc_get_position`）。
  - **锚点门禁从六类扩到八类**：并仓后 `axiscope` / `trae_factory` 不再随本仓发布，
    干净检出上只有 `mcopilot` + `book` 在位——此时"所有仓都找不到"的路径很可能就在缺仓里，
    判成断链是冤枉，且会让 CI 首跑直接红。故新增**「缺仓不可判定」**一类：
    缺仓期间不判失败，但**必须喊出来**（连同缺的是哪个仓）。
    全仓在位时口径不变（严判，真断链必须是 0）。

- [2026-10-22 本轮·批 C 公开前硬化] **三仓各自落定**（面向"传 GitHub"这件事）：
  - **mcopilot** `02c6988`（绝对路径外置 14 处 + **7 份厂商原件外置**到
    `../mcopilot-external/vendor_docs/protocol_specs/` + 锚点清单补登 14→15 条 +
    门禁"原件不在位记 SKIP 但必须 loud" + quote 反查与两个验收测试按
    「指纹在档自洽 / 原件在位核实物」两段改口径 + **子进程 stdout 编码错位修复** 4 处
    ——该错位是干净 HEAD 基线即存在的 2 failed，字节级证据为 GBK 输出被按 UTF-8 解码）
    → `cd3263f`（补 CI `.github/workflows/gates.yml` + 覆盖账本 `meta.projects[].path`
    去本机化 + CodeWiki §9.4/§9.7 与 `samples/servo/PROVENANCE.md` 的
    "本仓无 .github/" 等过期说法改到实况）。
    复验：门禁 **12/12** ✓、pytest **387 passed / 0 failed** ✓（基线 383/2failed/2skipped ✓）。
  - **axiscope** `b84bbbc`（脱敏清账 10 处本机路径与机构标识值 + LICENSE/NOTICE +
    CI `.github/workflows/tests.yml` + README 一处路径订正 `probe_pii.py`→`data/probe_pii.py`）。
    复验：pytest **403 passed** ✓；三个标识值 token 在发布产物里实测归零 ✓。
  - **trae_factory** `7a92023`（生成器去绝对路径 + **4 处账实不符修正** +
    **单文件交付物重建**——入库的 `上位机代码工厂.html` 落后于 `gen/` 152 增 15 删，
    浏览器里跑的一直是旧代码 + 7 品牌再生 + `out_v_unique` 20 件刷新 +
    **README 从零写** + LICENSE/NOTICE + CI `.github/workflows/build.yml`）。
  - 本书新增 `tools/scan_absolute_paths.py`（三仓绝对路径清账，可机判）：
    家目录/用户名 **0** ✓、本机工作区 **0** ✓；余 14 处为 `C:\Program Files` / `C:\Windows`
    系统路径 ✓，10 处为 `s7.json` 内嵌 C 代码的扫描器误报 ✓，均逐条定性 ✓。
  - **全书锚点维持不变**（mcopilot `b53ac62` / axiscope `7b0fd88` / trae_factory `954c210`）✓
    ——本轮动的是工作树与新提交，**没动任何一行正文坐标** ✓。
  决策清单：`decision-lists/release-hardening-20261022.md`（第 5 份 ✓）。
- [2026-10-22 本轮·批 D 发布准备] **索引仓已备，推送待作者给账号**：
  新建 `%WORKSPACE%\forensics-learning-index`（`README.md` 索引 + `PUSH-CHECKLIST.md` 清单 +
  `LICENSE` ✓，3 件 ✓，首次提交 `df75d7d` ✓）。索引里写清三仓的接缝图、
  真值链三根轴与各品牌 P/Invoke 实数（58 = 钉扎 49 + 降级 9 ✓）、
  以及**还没接上的**（真机层未验证 ✓、接缝 3 未闭合 ✓、早期提交仍是自动化署名 ✓）——其中接缝 3 已于 2026-10-23 傍晚闭合 ✓（见下条 ✓）。
  推送清单逐项列出**推送前必须自己过的 10 项检查**（本地已跑过一遍 ✓，数字全部实测 ✓）
  与**推完之后的验证**（含「在干净克隆里跑一遍主命令」✓ ——
  干净克隆与本机工作树的差异，正是公开后读者实际拿到的东西 ✓）。
  **未推送** ✓：本机无 `gh` ✓、GitHub 账号未提供 ✓ → 由作者本机执行 ✓。
- [2026-10-23 上午·作者发布裁定] **可见性 / 分支 / 仓名三条落定**：
  ① 三个工程仓**全部公开** ✓；② 默认分支**统一 `main`** ✓
  （mcopilot `master`→`main` ✓、trae_factory `master`→`main` ✓、axiscope 本就是 `main` ✓；
  **改名不改历史、不改任何坐标** ✓——坐标锚的是 commit 而非分支名 ✓）；
  ③ trae_factory 的公开仓名改 **`forensics-code-factory`** ✓
  （作者原话：「trae 是专用的 IDE 开发工具，容易歧义」✓）。
  **项目内名 `trae_factory` 不改** ✓：mcopilot 脚本按「同级兄弟目录」发现它 ✓、
  书里也已按此名引用 ✓ → 改目录名会断发现逻辑、也会让书与仓对不上 ✓；
  只改 GitHub 公开名 ✓，并在仓内 README 写明**内部名 ↔ 公开名**的对应 ✓。
- [2026-10-23 上午·批 D 续] **新增发布硬门槛：干净克隆可跑** ✓：
  本机工作树绿 ≠ 公开后能用 ✓。实测（本地路径克隆 = GitHub 将提供的同一份内容 ✓）
  挖出**五个真发布缺陷** ✓，全部已修 ✓：
  ① mcopilot `.gitignore` 的 `*.log` 把 `samples/logs/*.log` 三个测试夹具扫掉 ✗
     → 克隆里 14 个测试因缺夹具而红 ✓（补 `!samples/logs/*.log` ✓）；
  ② axiscope 原始数据按 A-131 不入库 ✗ → 87 个测试函数 FileNotFoundError ✓
     （新增 `tests/conftest.py` ✓，按各文件 `REQUIRES_DATA` **显式声明** loud SKIP ✓）；
  ③ mcopilot 的 G5 与 G7/G12 缺件口径不一致 ✗ → G5 把「原件不在位」判成失败 ✓
     （改为与 G7/G12 同口径记 SKIP ✓）；
  ④ mcopilot 负向门禁 N1 在缺件时**假绿** ✗ —— 拒绝的是「规范文本缺失」，
     却记成「编造引文被拒」的检测力已证明 ✓
     （基线不可核 ⟹ 整条用例 SKIP 且**不执行注入** ✓；框架加 SKIP 三态 ✓）；
  ⑤ mcopilot 跨仓桥接用例缺跳过守卫 ✗ → CI 上（只有 mcopilot 一个仓）必红 ✓
     （补守卫 ✓）。
  固化：书仓新增门禁 `tools/verify_clean_clone.py` ✓——克隆三仓到临时目录 ✓，
  按各自 CI 步骤**逐条复演** ✓（三仓 16 步全绿 ✓），
  并把 SKIP 的条数与原因原样带出来 ✓（跳过 ≠ 通过 ✓）。
  索引仓另附 `push_to_github.ps1` ✓：建空仓 → 推四仓 → **从 GitHub 干净克隆复验** ✓；
  令牌只进进程环境 ✓，不落盘 ✓、不进 git config ✓。
  **推送仍未执行** ✓：2026-10-23 试过账号密码，三种鉴权头全 401 ✗
  → 需作者给一个可用 PAT（勾 `repo`）✓。
- [2026-10-23 中午·批 D 收官] **四仓已发布到 GitHub（公开）✓**：
  | 仓（GitHub） | 分支 | 发布时 HEAD |
  |---|---|---|
  | `JosephIvon/mcopilot` ✓ | `main` ✓ | `85e45d4` ✓ |
  | `JosephIvon/axiscope` ✓ | `main` ✓ | `3576c9c` ✓ |
  | `JosephIvon/forensics-code-factory` ✓ | `main` ✓ | `e651f3b` ✓ |
  | `JosephIvon/forensics-learning-index` ✓ | `main` ✓ | `6a8e9d2` ✓ |

  核验（**GitHub API 独立复核**，不只信推送脚本的回显 ✓）：
  四仓均 `public` ✓、默认分支 `main` ✓；四仓本地 HEAD 与远端 `refs/heads/main`
  **逐个一致** ✓；**中文名路径真实在位** ✓（mcopilot 30 条 ✓ / axiscope 49 条 ✓ /
  工厂 1 条 ✓ —— 这正是此前 `git ls-files` 加引号漏检的那批 ✓）；
  索引仓 README 的 `<账号>` 占位符已替换为真链接 ✓。
  从 GitHub **干净克隆**复验 ✓：mcopilot 376 passed/11 skipped ✓、门禁 10/12（SKIP 2）✓；
  axiscope 294 passed/110 skipped ✓、脱敏自检退出码 0 ✓；
  工厂全品牌再生退出码 0 ✓、单文件与 `gen/` 同源 ✓。
  坐标锚点**未动** ✓（mcopilot `b53ac62` / axiscope `7b0fd88` / trae `954c210` ✓）——
  锚点之后的提交在本书 `ASSETS.md` 登记 ✓，书里 697 个坐标一个没受影响 ✓。
  仍挂账的（不许抹掉 ✓）：真机层未验证 ✓、
  mcopilot 早期提交仍是自动化署名 ✓、协议标准原件外置 ✓（干净克隆时相关门禁记 SKIP ✓）。
- [2026-10-23 傍晚·**接缝 3 已闭合**] 共享行为评测集落地 ✓：
  接缝 3 原来是「计划过但没落地」——工厂侧断言内置在 `trae_factory` 的 `gen/core.js` 里活着 ✓，
  而 mcopilot 侧的评测集文件与对照脚本**从未入库** ✓ → 工厂端到端 PASS 里的每一步
  都指不回一条登记在案的断言 ✓；2026-10-20 那份矩阵里工厂侧对 6 条断言的「实测命中」
  还是**粗粒度匹配** ✗（只看 GlueDemo 整体 `RESULT: PASS` ✓，没逐条对上 ✓）。
  闭合的标志是三样东西**同时在仓里** ✓：
  ① `mcopilot knowledge/shared_eval.json` ✓ —— **唯一数据源** ✓：
     19 条行为断言（BEH-01…BEH-19 ✓）+ 3 条合法差异（DIV-01/02/03 ✓）✓，
     逐条给域 ✓、工厂侧验证点 ✓、mcopilot 侧验证点 ✓；
     5 条 `n/a` 逐条写明「工厂接口无此概念」✓（`HasRealFeedback` / `StopReason` /
     比较点与锁存端口在工厂 `IMotionController` 里确实没有 ✓ —— 不是嘴上说说 ✓）；
     `scope` 字段把「工厂独有」（BEH-16 ✓）与「单边」（BEH-17/18 ✓）分开 ✓
     ——**分类由数据说，脚本不猜** ✓。
  ② `mcopilot scripts/joint_eval.py` ✓ —— **真跑两边** ✓ 的对照脚本 ✓：
     侧 A 编译并跑 mcopilot 仿真器自检 ✓；侧 B 编译并跑工厂 GlueDemo 工艺流程 ✓；
     逐条按 BEH 编号对齐 ✓；BEH-19 另做 **SPC 机器比对** ✓ ——
     从工厂 `glue_report.csv` 的原始样本**独立重算** Cpk ✓ 再与工厂打印值比 ✓
     （不是抄工厂的数字 ✓）；`verdict` 只认本次实测 ✓；
     缺环境一律记 SKIP 并喊「当前不可自动复核」✓，不算通过 ✓。
  ③ `mcopilot scripts/gate_joint_eval.py` ✓ —— **门禁 G13**（域 22 ✓）：
     静态截（任何环境都能跑 ✓）核对两侧的 BEH 标签与评测集**双向**对齐 ✓
     （不许有没登记的标签 ✓，也不许登记了却没标签 ✓）；
     动态截真跑两侧逐条对齐 ✓；缺编译器或缺工厂兄弟仓 ⟹ 动态截 SKIP ✓，**不许记 PASS** ✓。
  外加两侧都打上了 BEH 编号 ✓（mcopilot 侧 15 条在 `knowledge/templates/SelfCheck.cs.tmpl` ✓，
  工厂侧 14 条在 `gen/core.js` ✓ —— 其中 6 条是**代码本来就在、只是没打编号** ✓，
  本轮补齐 ✓，行为逻辑一行未改 ✓）；工厂生成的 `out/mc_all/docs/JointEval.md`
  现给出 mcopilot 侧验证点 ✓（数据源实时读取 ✓，非复制 ✓）✓。
  实测：双方都验 11 ✓ · 工厂独有 1 ✓ · 单边/合法差异 7 ✓ · 空白清零 ✓ · 共 19 条 ✓。
  **干净克隆里可复核** ✓：三仓克隆到同一目录后，G13 真跑通过 ✓（不是 SKIP ✓）✓。
  清理克隆实测还抓到第 6 个隐式依赖 ✓：`compile_check.ps1` 要三个适配器都在才肯编译 ✓，
  而对照脚本只生成了一个 ✓ → 自检被 skip ✓ → 已改成按 `knowledge/sdks/` 清单全生成 ✓ ✓。
  坐标锚点**未动** ✓（`b53ac62` / `7b0fd88` / `954c210` ✓）：书中坐标按锚点 commit 读源文件 ✓，
  锚点之后的变更在本文件登记 ✓ —— 697 个坐标一个没受影响 ✓。

### 外部参照与缓写卷

- `%WORKSPACE%\hello-agents` — 形制参照（docs+code+习题+capstone），非证据层
- axiscope @ `ddd03af`（初始导入）——axiscope 卷素材，最终账本在彼侧
- trae_factory（71 变更活跃中）——等停机宣告后再登记

## 二、叙事素材（作者亲历，不设坐标）

- 审计全程自纠：v1→v4 测量修正、sig_match 假阳性、B9 归因更正 → 前言/第8章叙事
- 三次方法论纠偏：抛砖引玉（叙述≠标准）/ 前提不明拆可锚不可锚 / 确权先立标准 → 前言叙事
- CNC 真值选择的 L2（两年操机背书"图纸+NC"）→ 第2章叙事
- 134 分流现场经过 → 第7章叙事（耐久对照物：MANIFEST.txt）

## 三、登记规则

1. 新素材入书前先登记：路径 + 供章 + commit hash（仓库类）
2. 工件变更后引用失效的：登记表更新 hash，正文回查
3. 叙事素材不伪装成可引用证据——读者验证走耐久对照物
