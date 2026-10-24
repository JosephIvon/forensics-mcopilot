# 协议知识提取 SOP（协议无关标准作业程序）

> 落档日：2026-10-21。固化对象：本轮 Modbus / S7 / Focas 三次提取中**验证过的手工管道**。
> 动机：防方法流失——管道目前只存在于三个知识库的产出物和会话记忆里；下一个人（或下次会话）
> 点名新协议时，不应靠考古 modbus.json 的提交历史重新发明流程。
> 有效性的证据标准：本文只收三次提取中实际用过且被抓过错/防过错的步骤；没用过的一律不写。

## 一、铁律（任何一步不许豁免）

1. **无裸提取**：每条结论必须带 `spec_ref`（一手件名/章节/页码或 URL/逐字引文）+ `provenance`。
   引文**逐字**复制自提取文本（允许行折断点合并，不改动词句）；反查不过=条目不存在。
2. **判断显式化**：结论多于引文的部分必须降级为 `judgment` + `needs:manual_check` + 理由在档
   （见 §三）。judgment 不是耻辱，隐藏 judgment 才是。
3. **可执行退出码**：每条"全过了"的声明背后必须有一个检查器，退出码 0 才算数（铁律：可执行
   退出码、负向证明检测力——见 docs/项目回顾与收尾_20261021.md §八）。
4. **诚实边界**：来源档位（官方规范 / 官方手册影印 / 第三方复刻 / 逆向文档）、未覆盖缺口、
   judgment 计数，全部如实写进 `spec_version.nature` / `note` / 提取说明，不含糊不隐瞒。
5. **零依赖**：提取与校验工具只用 python 标准库（pdf2txt.py 用 re/sys/zlib；反查器用
   json/re/argparse），保证克隆仓库即可回归，不装环境。

## 二、八步管道

```
①来源获取 → ②文本化 → ③机械提取 → ④引文全量机器校验 → ⑤三源语义对账
                                                      ↓
            ⑧账本入账 ← ⑦锚点登记 ← ⑥源码取证升级（可选，有开源实现时）
```

### ① 来源获取

- **官方优先级三档，逐档降级并声明**：
  1. 官方规范（Modbus 三件套：modbus.org 现行地址）；
  2. 官方手册影印/第三方分发的官方副本（Focas：inventcom 复刻手册 + 影印 PDF，官方 B-63xx
     未获得 → 在 `focas.json` `spec_version.nature` 如实标注）；
  3. 逆向文档 + 诚实声明（S7：无官方公开协议规范 → Snap7 Reference Manual，性质在档）。
  **收费墙 = 断 provenance 链，不硬造**：SECS-GEM 因 SEMI 收费直接延期，这是先例不是遗憾。
- 每份一手件记录：`source_url`（现行地址）+ `original_url`（原始/规范地址，modbus.org 2026
  年改版后文件移至 /file/secure/，双地址都留）+ `sha256` + `pdf_pages`。
- 一手件原件落 `knowledge/protocols/specs/`（入库，不留在会话临时目录）。
- **验收门**：sha256 已记录且与在库文件一致（后续由 ⑦ 的锚点门持续复核）；来源档位已声明。
- **失败处置**：官方件不可得 → 降档并声明，禁止把第三方件冒充官方件；整体不可得 → 记延期。

### ② 文本化

- PDF：`knowledge/protocols/specs/pdf2txt.py`（纯标准库）产出 `===== [PAGE n] =====` 分页文本；
  HTML 手册（如 inventcom 逐函数页）：digest 脚本归并为 txt（`out/_protocols_focas/digest_all.txt`
  模式）。产物统一放 `out/_protocols_<proto>/`（gitignored、可再生；但**提取文本的哈希进锚点
  清单**，见 ⑦）。
- **验收门**：产物存在；锚点门（`scripts/gate_anchors.py`，G7）用 pdf2txt 对在库 PDF **再提取
  抽查**，哈希须等于在档 txt——证明提取链未被篡改。
- **失败处置**：表格列布局在提取文本中被截断/串列 → 引文忠实于提取文本照收，但该条目必须挂
  `needs:manual_check` 并写明截断位置。实例：V1.1b3 §7 表 06 行 "The server is engaged in
  processing a long" 在列边界截断（modbus.json exception_codes[5]）。

### ③ 机械提取

- 逐条产出：`spec_ref{doc, section, page(或 url), quote 逐字}` + `provenance: "mechanical"`。
- 表格/列表型引文用 quote **片段数组**（每个片段均逐字且取自同一页，按原文顺序排列——s7.json
  口径）。字段落盘 schema 对齐 `modbus_extract/1` 风格（协议换名不换骨）。
- **验收门**：条目无 `spec_ref.quote` 不许入库（walk 工具会跳过并让计数露馅）；schema 与
  同目录知识库一致。
- **失败处置**：引文写不出来 = 没读到原文 = 回 ②；页码 off-by-one（实例：mbap_header 页码
  错一位）靠 ④ 的"同页"强制约束兜住——引文必须在**同一物理页**命中，跨页命中也算错。

### ④ 引文全量机器校验（反查门）

- 工具：`scripts/check_modbus_quotes.py`（已参数化：`--json <路径>` `--txt-dir <目录>`，
  缺省=仓库 modbus.json + out/_protocols_extract/，向后兼容；提取文本缺失时自动跑一次
  pdf2txt，CI 干净检出也能跑）。
- **判等口径三层**（由宽到严各计一遍数）：
  1. 严格逐字：引文规范化后是页面文本的子串；
  2. 签名同源：去全部非字母数字后整串命中（容忍连字符断行 16 - bit→16bit、词中断行）；
  3. 噪声容错：引文签名从中点切两半、两半都在页签名中（提取器偶发词内插脏字符；
     编造引文两半恰好同页的概率可忽略——这是负向注入 N1 的靶子）。
- judgment/`needs:manual_check` 项**跳过并计数**（跳过数必须显式打出，不许静默吞）。
- **验收门**：退出码 0 = 全命中。当前基线：modbus 53/53（严格 36 / 签名 17 / 跳过 7）。
- **失败处置**：miss → 回 ③ 修引文，或降级 judgment（§三）；**不许改反查器放行**。
- S7/Focas 的同型工具在 `out/_protocols_s7/verify_quotes.py` 与
  `out/_protocols_focas/verify_quotes.py`（现路径即接口，未参数化，见 §四）。

### ⑤ 三源语义对账

- 三源：**实现（C# 模板/客户端）↔ 知识库条目 ↔ 规范原文**。逐条对，不是抽查。
- 本轮实绩：抓出异常码 SLAVE/SERVER 措辞分歧（V1.1b3 用 SERVER DEVICE BUSY/FAILURE，部分
  实现沿用旧 SLAVE DEVICE *——契约测试把两个同义异名都钉死，改名即翻红）与两处章节号错引。
- **验收门**：对账结论入册（`*_提取说明.md` / 评审记录）；措辞分歧必须显式处置（钉死+注释），
  不许各写各的。
- **失败处置**：知识库与原文冲突 → 修知识库（以原文为准）；实现与规范冲突 → 修实现；规范
  自身矛盾 → judgment 登记两说，needs:manual_check。

### ⑥ 源码取证升级（可选：有开源实现时）

- "手册没写"≠"不可证"：开源实现可作 `evidence_source`（如 `"snap7_source"`），条目加
  `src_ref{file, line, quote}`——file 为源码仓库相对路径、line 为 1-based 行号/行段、quote
  为该行段逐字内容（多行 \n 连接、行首缩进裁剪）。源码快照包（snap7-master.tar.gz）入库
  `out/` 并进锚点清单。
- 本轮实绩：Snap7 1.4.3 源码取证把 7 条 judgment 全部闭合，升级为
  `provenance: "mechanical-evidence"`（s7.json 判决项清零）。
- **验收门**：src_ref 行号在**登记时的快照**中可复核（快照哈希锚定）；升级须移除
  `needs:manual_check` 并在提取说明记录升级明细。
- **失败处置**：源码与手册冲突 → 手册条目挂 needs:manual_check，源码条目按 mechanical
  收录，两说并存待官方件。

### ⑦ 锚点登记

- 全部一手件与提取文本登记进 `knowledge/protocols/anchors.json`（文件→sha256，`protocol_anchors/1`）。
- **验收门**：`scripts/gate_anchors.py`（G7）重算比对 + 再提取抽查 + URL 存活（默认 WARN，
  `--strict` 计失败）。
- **失败处置**：哈希漂移 = 一手件被篡改/替换，先查人再查文件；URL 失效 → 找归档件并双地址
  登记。

### ⑧ 账本入账

- `knowledge/coverage_ledger.json`（entries + plan_v2 phases）+ `capability_matrix.{json,md}`
  特性格。**数字全部实算**（条目数、judgment 数、测试数），不许手抄旧数。
- **验收门**：`gate_docsync.ps1`（G8）从代码/知识库实算数字对文档断言；能力矩阵轻对账测试。
- **失败处置**：数字对不上 = 文档在说谎，修文档（或查出真回归）。

## 三、judgment 纪律

判定标准一句话：**这句话是否逐字出自一手件、且该引文足以支撑整条结论？**两者任一不成立，
就必须 `provenance: "judgment"` + `needs: "manual_check"` + 理由字段（`needs_note` /
`judgment_note`）在档。三种已验证的高发场景：

1. **错误码表推导（表中缺席的码）**——实例 EX07/EX09：V1.1b3 §7 异常码表 06→08 跳 07、
   08→0A 跳 09。"表中缺席"本身可机械证（quote 写作 "06 SERVER DEVICE BUSY ... 08 MEMORY
   PARITY ERROR（表中 06 与 08 之间无 07 条目）"式证据），但"07/09 在后续规范或实现中的
   名称与含义"**无法从本轮文本获得** → 整条 judgment + needs:manual_check，name 置 null，
   不从记忆里补全（补了就是编造）。
2. **聚合引用（跨节汇总）**——实例 `fc_quantity_limits_summary`：把 §6.1-6.18 各节请求表的
   上限汇成一张表，单条 quote 只能覆盖一行 → **不是逐字原文，必须 judgment**。该条
   2026-10-21 从 mechanical 降级（needs_note 记录降级理由），并声明"各项上限的逐字引文以
   function_codes 各条目为准"——聚合条目只做索引，不承载真值。
3. **手册未覆盖 / 仅示例值**——实例 Focas 端口 8193：手册正文仅在 cnc_allclibhndl3 的示例
   程序解说出现 "its port number of the Ethernet (TCP) is 8193"，**没有"默认端口"的规范
   陈述**；工业实践与第三方驱动（Kepware 等）通行 8193。处置：示例出现值照样收录
   （conn_port_8193_example，mechanical，引文=示例原文）；"默认端口 8193"单独立 judgment
   条目（judg_default_port_8193），judgment_note 写明"正式依据需 FANUC 官方以太网功能手册
   或 CNC 侧参数设定"。**示例值 ≠ 规范默认值，中间的推理步骤就是 judgment 本身。**

通用处置：judgment 项在反查门被跳过但**计数显式打出**；回归测试对关键 judgment 钉身份
（如 test_protocol_modbus 断言 EX-07/09 必须 `provenance=="judgment"`——降级状态也是受测状态）。

## 四、工具链现状与参数化

| 工具 | 现路径 | 接口 | 状态 |
|---|---|---|---|
| Modbus 引文反查 | `scripts/check_modbus_quotes.py` | 无参（缺省=仓库 KB+提取文本）或 `--json <路径>` `--txt-dir <目录>` | **已参数化**（2026-10-21）；缺省行为与历史版本逐字节等价，门禁/负向注入按无参调用不受影响；对真实 modbus.json 基线 53/53 退出码 0 |
| pdf2txt（文本化） | `knowledge/protocols/specs/pdf2txt.py` | `pdf2txt.py <outdir> <pdf...>`，产物带 `===== [PAGE n] =====` | 稳定；反查器缺文本时自动代跑 |
| S7 引文反查 | `out/_protocols_s7/verify_quotes.py` | 无参；单源 Snap7-refman.txt，quote 支持片段数组，全空白剥离判等 | **未参数化**（不在本轮写许可；产物在 out/ 可再生，现路径即接口） |
| Focas 引文反查 | `out/_protocols_focas/verify_quotes.py` | 无参；多源路由（INV→逐函数页 txt / F2LX / F2FL / HDR 头文件），报 NO LOCAL SOURCE | 同上未参数化 |
| 锚点门 | `scripts/gate_anchors.py` | 清单 sha256 重算 + 再提取抽查 + URL 存活 | 稳定（G7） |

统一接口的判断：三家反查器的 walk/判等核心同构，抽公共库技术上可行；但各协议脚本是
**一次性产物**（落在 out/，可再生、有锚点钉哈希），统一库的收益低于把它排进消费者里程碑——
按协议域冻结决定，不做提前抽象。低成本统一的前置条件：写许可覆盖对应 out/ 目录 + 至少
第四个协议入场复用（届时以 `check_modbus_quotes.py` 的 `--json/--txt-dir` 为接口蓝本，
抽 walk/norm/sig 三层判等为核心）。

## 五、与门禁体系衔接

- 本管道的 ④⑤⑦⑧ 分别由门禁 G5（quote 反查）/ 契约套件 / G7（锚点）/ G8（docsync）持续
  执行；负向检测力由 `gate_negative.ps1` 证明（N1：向 modbus.json 副本注入编造引文 → G5
  必须变红，52/53 拒收）。
- 新协议接入时的门禁扩展点：`gate_protocol.ps1` 增加对应 G 门（反查/契约/锚点），门清单
  自检与「每门必有负向用例」的纪律照走（门清单与退出码域在 `scripts/gate_protocol.ps1`，负向用例在 `scripts/gate_negative.ps1`）。
- forensics 衔接：现场日志契约 `knowledge/contracts/comm_log_contract.json`（comm_log/1）+
  `scripts/validate_comm_log.py`（契约裁判）+ `scripts/eval_forensics.py`（归因评测骨架）已
  落档；协议知识库（异常码语义/帧布局）就是归因层的判断依据——提取管道产出的真值链，
  最终在归因评测里被消费。

## 六、何时用

- **触发条件**：消费者点名新协议（真实项目需求，不是收藏驱动）。协议域有主动刹车：三个
  知识库后不再主动加协议（coverage_ledger plan_v2 P3 冻结决定），新协议=消费者里程碑的
  需求拉动的开工令。
- **执行方式**：按 §二 八步全链走一遍，不许跳步（跳过 ④ 等于零条引文可查，跳过 ① 等于
  provenance 从头就断）。工具按 §四 现状表取用。
- **交付清单（协议 X）**：`knowledge/protocols/<协议名>.json`（modbus_extract/1 风格 schema）+
  `specs/` 一手件（双 URL+sha256）+ `out/_protocols_x/` 提取与反查管道 + `*_提取说明.md`
  （方法与缺陷）+ anchors 登记 + coverage_ledger/能力矩阵入账 + 门禁扩展。
- **完成标准**：八步验收门全绿（退出码 0）+ judgment 全部显式 + 诚实边界章节随交付更新。
