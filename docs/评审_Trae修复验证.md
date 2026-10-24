# 评审_Trae修复验证 —— W1「上位机代码工厂」P/Invoke 修复的独立复核

> 复核时间：2026-10-20 15:20–15:35
> 复核对象：`<Trae-CN 会话工作区>\temp_20261019_01`（产物 `out/mc_*/`、生成器 `gen/`、单文件交付 `上位机代码工厂.html`）
> 被审报告：`mcopilot/docs/评审_Trae修复.md`（W1 自述）
> 被审工具：`mcopilot/scripts/verify_trae_pinvoke.py`（W1 的核对工具）
>
> **本复核没有使用 W1 的工具**。自写解析器（临时脚本，已删除），从 .cs 逐行正则抓 `[DllImport]`，再对三层外部真值做**精确匹配**（不用词边界正则），
> 并在此基础上追加了 W1 工具完全没做的三项核对：**参数表/返回类型逐条比对**、**结构体布局比对**、**文档里真值行号引用的回查**。
>
> 唯一外部真值（只读）：
> - `knowledge/sdks/official_api/dll_exports.csv`（PE 导出表；列：`DLL,位数,函数名,已导出,变体`）
> - `knowledge/sdks/official_api/zmotion.csv` / `zmotion_cpp.csv`（正运动官方 C# 绑定 / 官方 C 头文件）
> - `knowledge/sdks/official_api/gts.csv` / `gts_hdr.csv` / `gts_structs.csv` / `gts_hdr_macros.csv`（固高官方 C# 绑定 / C 头文件 / 结构体表 / 宏表）
> - `knowledge/sdks/official_api/leisai.csv` / `leisai_cpp.csv`（雷赛官方 C# 绑定 / 官方 C 头文件）
> - 补充：`gts_prototypes.csv`（固高官方 C 头文件原型，带默认值）

---

## 0. 一句话结论

**P/Invoke 修复本身：合格。** 58 条 DllImport 声明，我独立复算为 **58 条双绿、0 条需自证、0 条不存在**，与 W1 自述数字**完全一致**；
并且我额外做了 W1 工具没做的签名比对，**58/58 的参数个数、参数类型宽度、返回类型、结构体字段布局全部与官方原型一致**。
三个重点问题（正运动 DLL 名、8 个臆造正运动名、固高/雷赛 8 个臆造项）**全部处置正确**，没有出现"看起来像"的伪官方名。

但 W1 报告里有 **2 处事实性偏差**（一处引用行号引错、一处关于宏表的表述不成立），
另有 **3 项 W1 声称但本环境无法独立背书**（修复前基线、net8.0 构建路径、工具对参数表的覆盖能力）。详见 §5、§6。

---

## 1. 独立复算：总数与分类

| 项 | 我的独立复算 | W1 自述（`评审_Trae修复.md` §6） | 是否一致 |
|---|---|---|---|
| 声明总数（按 DLL+函数名去重） | **58** | 58 | ✅ 一致 |
| 双绿（PE 导出已导出=1 **且** 官方 C# 绑定有） | **58** | 58 | ✅ 一致 |
| 需自证（只在 PE 导出表，官方绑定/头文件没有） | **0** | 0 | ✅ 一致 |
| 不存在（PE 导出表与官方绑定/头文件都没有） | **0** | 0 | ✅ 一致 |
| 文件内出现次数（未去重） | 116 | — | — |

### 1.1 按品牌 / 按 DLL 分组

| 品牌 | 适配器文件 | DllImport 条数 | 双绿 | 需自证 | 不存在 |
|---|---|---|---|---|---|
| 固高 GTS/GTN | `out/mc_gts/src/Adapters/GoogolGtsController.cs` | 22 | 22 | 0 | 0 |
| 雷赛 DMC/EMC | `out/mc_leadshine/src/Adapters/LeadshineDmcController.cs` | 16 | 16 | 0 | 0 |
| 正运动 ZMC | `out/mc_zmotion/src/Adapters/ZMotionZmcController.cs` | 20 | 20 | 0 | 0 |
| 高川（骨架） | `out/mc_gaochuan/src/Adapters/GaoChuanController.cs` | 0 | — | — | — |
| 软赢（骨架） | `out/mc_softwin/src/Adapters/SoftWinController.cs` | 0 | — | — | — |
| **合计（去重）** | | **58** | **58** | **0** | **0** |

> 116 次出现 = 58 条 × 2 套件（单品牌套件 + `mc_all` 全品牌套件）。
> `out/mc_all/src/Adapters/` 下的 5 个适配器与单品牌套件**逐字节同源**（SHA256 一致），已核对。
> 高川/软赢两个骨架适配器 `DllImport` 计数为 0，**没有新增任何臆造签名**，符合预期。

### 1.2 DllImport 目标 DLL 全量统计（覆盖 `out/` 全部 .cs + 6 个 zip 包内的 .cs）

| 目标 DLL | 出现次数 | 说明 |
|---|---|---|
| `gts.dll` | 44 | 22 条 × 2 套件 |
| `LTDMC.dll` | 32 | 16 条 × 2 套件 |
| `zauxdll.dll` | 40 | 20 条 × 2 套件 |
| **其它** | **0** | 无 `zmcaux.dll`、无任何第四种 DLL |

---

## 2. 三个重点问题的独立核查

### 2.1 (a) 正运动是不是全改成 `zauxdll.dll`？还有没有残留 `zmcaux.dll`？

**结论：全部改完，无残留声明。**

- `out/mc_zmotion/src/Adapters/ZMotionZmcController.cs:53-92` 与 `out/mc_all/src/Adapters/ZMotionZmcController.cs:53-92`：
  20 条声明的 `[DllImport("...")]` **全部**是 `"zauxdll.dll"`。
- 真值侧：`dll_exports.csv` 里 DLL 名只有 4 个 —— `gts.dll`(3838 行) / `LTDMC.dll`(7580 行) / `zauxdll.dll`(423 行) / `zmotion.dll`(232 行)。
  **`zmcaux` 作为 DLL 名在 `dll_exports.csv` 中命中 0 次**（按 DLL 名字段精确匹配，不按函数名模糊搜）。
- 全仓库文本搜索 `zmcaux` 共 6 处，**全部是注释**（说明"官方是 zauxdll.dll，不存在 zmcaux.dll"）：
  `gen/adapters_kb.js:473,496`、`out/mc_zmotion/.../ZMotionZmcController.cs:51`、`out/mc_all/.../ZMotionZmcController.cs:51`、`上位机代码工厂.html:1994,2017`。
  **没有任何一处是 DllImport 目标。**
- 附带：`zauxdll.dll` 在 PE 导出表里 **423 行全部是 `位数=64`**，没有 32 位变体（`gts.dll`/`LTDMC.dll` 都有 32/64 两种）。
  csc 默认产出的 exe 是 `PE32 / 32BITPREFERRED=false`（64 位系统上按 64 位进程跑），当前能正常加载；
  但若部署到 32 位 Windows 或加 `/platform:x86`，`zauxdll.dll` 加载不了。**这一点 W1 报告没提**（见 §6 遗留问题 7）。

### 2.2 (b) 那 8 个臆造的正运动函数名是不是真的换掉了？换成的是不是官方真名？

**结论：8 个全部换掉，且换成的是官方真名，每条在「官方 C# 绑定 + 官方 C 头文件 + PE 导出表」三处同时精确命中。**

| 原臆造名（真值中查不到） | 现声明 | 官方 C# 绑定 | 官方 C 头文件 | PE 导出表（已导出=1） | 现声明位置 |
|---|---|---|---|---|---|
| `ZAux_Direct_Single_MoveRel` | `ZAux_Direct_Single_Move` | `zmotion.csv:327` | `zmotion_cpp.csv:337` | `dll_exports.csv:336` | `ZMotionZmcController.cs:68` |
| `ZAux_Direct_Cancel` | `ZAux_Direct_Single_Cancel` | `zmotion.csv:325` | `zmotion_cpp.csv:335` | `dll_exports.csv:334` | `:74` |
| `ZAux_Direct_Datum` | `ZAux_Direct_Single_Datum` | `zmotion.csv:326` | `zmotion_cpp.csv:336` | `dll_exports.csv:335` | `:76` |
| `ZAux_Direct_GetFpos` | `ZAux_Direct_GetDpos` | `zmotion.csv:82` | `zmotion_cpp.csv:86` | `dll_exports.csv:86` | `:80` |
| `ZAux_Direct_GetIdle` | **`ZAux_Direct_GetIfIdle`** | `zmotion.csv:106` | `zmotion_cpp.csv:110` | `dll_exports.csv:110` | `:82` |
| `ZAux_Direct_GetAd` | `ZAux_Direct_GetAD` | `zmotion.csv:59` | `zmotion_cpp.csv:63` | `dll_exports.csv:63` | `:88` |
| `ZAux_Direct_SetDa` | `ZAux_Direct_SetDA` | `zmotion.csv:265` | `zmotion_cpp.csv:275` | `dll_exports.csv:274` | `:90` |
| `ZAux_Direct_Servo` | `ZAux_Direct_SetAxisEnable` | `zmotion.csv:258` | `zmotion_cpp.csv:268` | `dll_exports.csv:267` | `:92` |

- 重点复核的两个名字**写法完全正确**：
  - `ZAux_Direct_GetIfIdle`（不是 `GetIdle`/`GetIfIdel`/`GetIsIdle`）—— `zmotion.csv:106` 就是这一行；
  - `ZAux_Direct_Single_Move`（不是 `Single_MoveRel`）—— `zmotion.csv:327` 就是这一行。
- 旧名 8 个经我在 `zmotion.csv` / `zmotion_cpp.csv` / `dll_exports.csv` 三张表里精确查证，**一个都不存在**（不是词边界误配，是真的没有）。
- 顺带：注释里原本引用的 `ZAux_Direct_MoveClockwise` / `CounterClockwise` 真值中同样不存在，W1 改成了官方
  `ZAux_Direct_MoveCircAbs`（`zmotion.csv:203`）/ `ZAux_Direct_MoveCirc`（`zmotion.csv:198`）—— 我也独立查证过，一致。

### 2.3 (c) 固高/雷赛那 8 个臆造项，是换成了官方等价物还是被删掉并标注未实现？

**结论：5 个换成官方等价物 + 3 个删除并标注「未实现」。没有出现"看起来像"的非官方名。** 判**合格**。

| # | 臆造名（真值中查不到） | 处置 | 落到哪个官方函数 | 三层真值出处 | 标注位置 |
|---|---|---|---|---|---|
| 1 | `GT_SetTrapPara` | **换成官方** | `GT_SetTrapPrm(short,ref TTrapPrm)` | `gts.csv:454` / `gts_hdr.csv:513` / `dll_exports.csv:10531` | `GoogolGtsController.cs:75` |
| 2 | `GT_SetJogPara` | **换成官方** | `GT_SetJogPrm(short,ref TJogPrm)` | `gts.csv:422` / `gts_hdr.csv:470` / `dll_exports.csv:10477` | `:79` |
| 3 | `GT_SetGoHomePara` | **换成官方** | `GT_GetStandardHomePrm(short,out TStandardHomePrm)` + `GT_ExecuteStandardHome(short,ref TStandardHomePrm)` | `gts.csv:241`/`119`；`gts_hdr.csv:264`/`128`；`dll_exports.csv:10183`/`9997` | `:81`、`:83` |
| 4 | `GT_GetAi` | **删除 + 标未实现** | — （官方无等价函数） | `gts.csv`/`gts_hdr.csv`/`dll_exports.csv` 三表均 0 命中 | `GoogolGtsController.cs:493-497`（`GetAi()` 返回 0 + 注释） |
| 5 | `GT_SetAo` | **删除 + 标未实现** | — （官方无等价函数） | 同上，三表均 0 命中 | `:506-509`（`SetAo()` 返回 `MotionResult.Fail(-300,"[未实现] ...")`） |
| 6 | `dmc_read_ad` | **换成官方** | `dmc_get_ad_input(ushort,ushort,ref double Vout)` | `leisai.csv:442` / `leisai_cpp.csv:319` / `dll_exports.csv:1858` | `LeadshineDmcController.cs:79` |
| 7 | `dmc_write_da` | **换成官方** | `dmc_set_da_output(ushort,ushort,double Vout)` | `leisai.csv:440` / `leisai_cpp.csv:981` / `dll_exports.csv:2666` | `:81` |
| 8 | `dmc_set_servo` | **删除 + 标未实现** | — （官方无软件使能接口） | `leisai.csv`/`leisai_cpp.csv`/`dll_exports.csv` 三表均 0 命中 | `LeadshineDmcController.cs:136-139`（`Enable()` 返回 `MotionResult.Fail(-300,"[未实现] ...")`） |

补充核查：
- 被删的 3 个臆造名在**全仓库**（`out/` + `gen/` + 单文件 HTML）里只剩注释与"未实现"提示文案，**没有任何 DllImport 残留**。
- 被删项的官方候选函数也如实留了档：`GT_GetAdc`（`gts.csv:129` / `gts_hdr.csv:137`）、`GT_SetDac`（`gts.csv:393`）、`GT_PtAo`（`gts.csv:336`）——
  我逐个回查了行号，**三处行号全部正确**。
- ⚠️ 一个 W1 报告没提的细节：`GT_GetStandardHomePrm` 与 `GT_ExecuteStandardHome` 在 `gts.dll` 的 5 个导出变体里，
  **"MCT2008工具" 变体是「已导出=0」**（`dll_exports.csv:11708` / `:11529`），另外 4 个变体（32bit_multi_card / 32bit_single_card /
  64bit_multi_card / 64bit_single_card）都是「已导出=1」。**不影响可用性**（正常 gts.dll 已导出），但报告只引 64bit 那行、不提这个例外，是不完整的。

---

## 3. W1 工具没做、我补做的三项核对

### 3.1 签名逐条比对（参数个数 + 参数类型宽度）—— 58/58 一致

W1 的 `verify_trae_pinvoke.py` 只判定**函数名**在不在真值里，**从不比对参数表**。我把每条 C# 声明的参数逐个拆开，
和官方 C# 绑定的原型做「参数个数 + 每个参数的整数宽度/浮点宽度」比对：

```
签名比对结果： MATCH 58 / ARITY_MISMATCH 0 / TYPE_MISMATCH 0 / NO_PROTO 0
```

抽样（全部通过）：

| 声明 | C# 声明 | 官方原型（出处） |
|---|---|---|
| `ZAux_Direct_GetAD` | `int (IntPtr, int, out float)` | `ZAux_Direct_GetAD(IntPtr,int,ref float)`（`zmotion.csv:59`） |
| `ZAux_Direct_SetDA` | `int (IntPtr, int, float)` | `ZAux_Direct_SetDA(IntPtr,int,float)`（`zmotion.csv:265`） |
| `ZAux_Direct_GetIn` | `int (IntPtr, int, out uint)` | `ZAux_Direct_GetIn(IntPtr,int,ref UInt32)`（`zmotion.csv:108`） |
| `ZAux_Direct_SetOp` | `int (IntPtr, int, uint)` | `ZAux_Direct_SetOp(IntPtr,int,UInt32)`（`zmotion.csv:297`） |
| `dmc_pmove` | `short (ushort, ushort, int, ushort)` | `dmc_pmove(UInt16,UInt16,Int32,UInt16)`（`leisai.csv:71`） |
| `dmc_set_homemode` | `short (ushort,ushort,ushort,double,ushort,ushort)` | `dmc_set_homemode(UInt16,UInt16,UInt16,double,UInt16,UInt16)`（`leisai.csv:115`） |
| `dmc_change_speed` | `short (ushort,ushort,double,double)` | `dmc_change_speed(UInt16,UInt16,double,double)`（`leisai.csv:76`） |
| `GT_ClrSts` | `short (short, short)` | `GT_ClrSts(short,short)`（`gts.csv:81`） |
| `GT_SetDoBit` | `short (short, short, short)` | `GT_SetDoBit(short,short,short)`（`gts.csv:396`） |

⇒ W1 报告 §3.1/§3.3 里"顺带按官方原型改的参数类型"这件事**确实做了，而且做对了**，只是它的工具覆盖不到这一层。

### 3.2 返回类型比对 —— 38/38 可核对项全部一致

`gts_hdr.csv` / `leisai_cpp.csv` 的官方 C 头文件原型带返回类型，我逐条比对：
固高 22 条（全部 `short`）、雷赛 16 条（14 条 `short`，`dmc_get_position`/`dmc_get_encoder` 为 `long`）—— **0 处不一致**。

⚠️ 20 条正运动 `ZAux_*` 的返回类型**无法核对**：`zmotion.csv` 与 `zmotion_cpp.csv` 的原型列**都没写返回类型**（例如
`zmotion_cpp.csv:38` = `ZAux_Close(ZMC_HANDLE handle)`，没有前缀返回类型）。代码里写的 `int` **在真值里没有依据**，
只能靠厂商手册确认。W1 报告的 §7「诚实边界」表里**没有列这一条**。

### 3.3 结构体布局比对 —— 与 `gts_structs.csv` 逐字段一致

| 结构体 | 代码位置 | 官方字段序（`gts_structs.csv`） | 结论 |
|---|---|---|---|
| `TTrapPrm` | `GoogolGtsController.cs:96-103` | acc(0,double) dec(8,double) velStart(16,double) smoothTime(24,short)，总长 32（`:194-197`） | ✅ 一致 |
| `TJogPrm` | `:104-110` | acc(0,double) dec(8,double) smooth(16,double)，总长 24（`:160-162`） | ✅ 一致 |
| `TStandardHomePrm` | `:111-125` | mode(0,short) highSpeed(8,double) lowSpeed(16,double) acc(24,double) offset(32,int) check(36,short) autoZeroPos(38,short) motorStopDelay(40,int) pad1(44,short) pad2(46,short) pad3(48,short)，总长 56（`:171-181`） | ✅ 一致 |

回零模式宏也核对过：`gts_hdr_macros.csv:163-169` = `HOME_MODE_LIMIT,10` / `HOME_MODE_LIMIT_HOME,11` / `HOME_MODE_LIMIT_INDEX,12` /
`HOME_MODE_LIMIT_HOME_INDEX,13` / `HOME_MODE_HOME,20` / `HOME_MODE_HOME_INDEX,22` / `HOME_MODE_INDEX,30`，
代码 `MapHomeModeToGtsStandard`（`GoogolGtsController.cs:526-536`）用的 10/20/22/30 **与真值完全一致**。

### 3.4 文档里真值行号引用的回查（我加的第四项）

- W1 报告里的 **62 处**真值行号引用 → **62/62 全部指向它所说的那个函数**。
- `out/mc_*/docs/ApiChecklist.md` + `gen/adapters_kb.js` 里的 **116 处**行号引用 → **115 处正确、1 处错误**（见 §5.1）。

---

## 4. 编译自检

**通过。** 6 个套件全部 **0 错误 0 警告**。

| 套件 | 源文件数 | csc 退出码 | 输出 |
|---|---|---|---|
| `mc_gts` | 11 | 0 | 0 错 0 警 |
| `mc_leadshine` | 11 | 0 | 0 错 0 警 |
| `mc_zmotion` | 11 | 0 | 0 错 0 警 |
| `mc_gaochuan` | 11 | 0 | 0 错 0 警 |
| `mc_softwin` | 11 | 0 | 0 错 0 警 |
| `mc_all` | 15 | 0 | 0 错 0 警 |

- 编译器：`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`（.NET Framework 4，**本机自带，无需安装**）。
- 命令与 `out/mc_*/build/build_net48.bat:6-7` **完全相同**，唯一差别是 `/out` 重定向到 `%TEMP%\indep_check\bin\`，
  **不在 Trae 仓库里落产物**（本次评审对仓库是只读的）。
- 额外跑了 `mc_gts_GlueDemo.exe`（默认 `Brand.Virtual`，不需要硬件）：`Open → ConfigureAxis → Enable → Home → WaitHomeDone` 全部 `[OK]`，流程可跑通。
- ⚠️ **`build/GlueDemo.csproj` 那条 net8.0 路径本机跑不了**：`dotnet build` 报 `No .NET SDKs were found`（本机只有 .NET 运行时，没有 SDK）。
  这条路径 W1 报告也没验证过（它只声称验证了 csc 那条），但 `csproj` 就在交付包里，属于**未覆盖的构建路径**。

---

## 5. 与 W1 自述的差异清单

### 5.1 差异 1（必须修）：`leisai.csv:12` 引用行号错误 —— 应为 `leisai.csv:10`

- 引用内容：`卡信息用官方 dmc_get_CardInfList(leisai.csv:12)`
- 实际：`leisai.csv:12` 是 `dmc_get_card_soft_version`（**不是** `dmc_get_CardInfList`）；`dmc_get_CardInfList` 在 **`leisai.csv:10`**。
- 出现位置（4 处，源头是 `gen/adapters_kb.js:315`）：
  - `gen/adapters_kb.js:315`
  - `out/mc_leadshine/docs/ApiChecklist.md:19`
  - `out/mc_all/docs/ApiChecklist.md:19`
  - `上位机代码工厂.html:1836`（单文件交付，同样内嵌）
- 影响面：只是**核对指引指错行**，不涉及任何 P/Invoke 声明或签名。按 `chk` 里的其它引用（`leisai.csv:4` / `leisai_cpp.csv:32`）来看，
  是手误（可能原本想引 `leisai_cpp.csv` 里的某行）。修法：把 `leisai.csv:12` 改成 `leisai.csv:10`。

### 5.2 差异 2（必须修）：「宏表里没有给出 diType/doType 宏值」这句表述不成立

- 代码/文档原话（`out/mc_gts/src/Adapters/GoogolGtsController.cs:551-552`、
  `gen/adapters_kb.js:121-122`、`out/mc_gts/docs/ApiChecklist.md:32`、`上位机代码工厂.html:1557,1642`）：
  > `diType/doType 的宏值(GT_DI_GPI / GT_DO_GPO 等)在官方头文件宏表 gts_hdr_macros.csv 里没有给出，这里保留原实现取值 1`
- 事实：`gts_hdr_macros.csv` **里有** `MC_GPI,4`（**第 17 行**）和 `MC_GPO,12`（**第 22 行**）。
  也就是说：宏表里确实没有名为 `GT_DI_GPI`/`GT_DO_GPO` 的宏（这部分原文没错），但**「diType/doType 的宏值在宏表里没有给出」这句是错的** ——
  真值文件里就有两个语义高度吻合的候选值（4 / 12）。
- 定性：**真值文件无法证明 `MC_GPI` 就是 `GT_GetDi(short diType,…)` 的 diType 取值**（宏表没有标注用途），
  所以代码保留 `1` 并打 `[核对]` 标记**是可接受的**（不构成臆造签名）。但"宏表里查不到"这句不成立，
  会让读代码的人以为再翻宏表也没用。建议改成："官方宏表里有 `MC_GPI=4`/`MC_GPO=12`（`gts_hdr_macros.csv:17,22`），
  但真值未标注其与 diType/doType 的对应关系，故仍取 1 并标 [核对] 待手册确认"。
- 公平起见说明：W1 报告 §7 的**字面**表述（`评审_Trae修复.md:218`）是"官方头文件宏表里没有 `GT_DI_GPI`/`GT_DO_GPO`"——
  这句**字面正确**（宏表里确实没有这两个名字的宏）；不准确的是**代码注释**与 **ApiChecklist 的 `chk` 文本**里那句
  "diType/doType 的宏值……在 gts_hdr_macros.csv 里没有给出 / 在官方宏表里查不到"（把范围从"宏名"扩大到了"宏值"）。
  也就是说：问题出在产物代码与清单文案，不在 W1 报告的措辞。

### 5.3 差异 3（工具覆盖能力）：W1 的核对工具不比对签名

- `mcopilot/scripts/verify_trae_pinvoke.py` 的判定逻辑是 `exported and binding`（行 321-334），
  **只比对函数名**；`signature` 相关的字样只出现在输出格式里（行 425-426 打印声明签名），**没有任何一步拿签名去撞官方原型**。
- 因此 W1 报告 §3.1/§3.3 声称的"顺带按官方原型改的参数类型 / 参数表"**没有工具背书**。
- 我的独立结论：这部分**实际做对了**（§3.1，58/58 一致）。但**报告与工具的能力边界对不上**，读者会误以为工具验过签名。
- 建议：在工具里加一层"参数个数 + 类型宽度"比对，或在报告里明写"参数表改动未经工具验证，系人工核对"。

### 5.4 差异 4（无法背书）：「修复前基线 61 / 33 / 0 / 28」无法独立复现

- 复核环境里 `<Trae-CN 会话工作区>\temp_20261019_01` **没有 `.git`**，`mcopilot` 也没有，
  `out/` 下**没有 `.bak/.orig/.old/~` 任何备份**。修复前的 .cs 已不存在。
- 我只能验证 W1 这组数字的**算术自洽性**：61 − 3(删 3 条臆造) = 58 ✅；固高 24 − 2 = 22 ✅；雷赛 17 − 1 = 16 ✅；
  不可用 28 = 正运动 20 + 固高 5 + 雷赛 3 ✅；双绿 33 = 固高 19 + 雷赛 14 + 正运动 0 ✅。
  并且 W1 列出的 8 个"修前臆造名"经我独立查证**确实在三层真值里都不存在** ✅。
- 结论：**"修复前"这组数字属 W1 单方陈述，我不背书**；能背书的是"修复后"这组数字（58/58/0/0，我独立复现）。

### 5.5 差异 5（口径）：PE 导出表的「变体」维度被 W1 简化了

- `dll_exports.csv` 里 `gts.dll` 同一函数有 5 行（32bit_multi_card / 32bit_single_card / 64bit_multi_card / 64bit_single_card / MCT2008工具），
  `LTDMC.dll` 有 2 行（32/64），`zauxdll.dll` 只有 1 行（64）。
- W1 报告 §3.2 只引 "PE 导出表(64位)" 一行，未说明变体；且 `GT_GetStandardHomePrm` / `GT_ExecuteStandardHome` 的
  **"MCT2008工具" 变体是「已导出=0」**（`dll_exports.csv:11708` / `:11529`），W1 未提。不影响可用性（其余 4 个变体已导出=1），
  但作为"可复核"的报告，应当写全。

### 5.6 差异 6（覆盖面）：W1 报告未覆盖的 3 个点

1. `build/GlueDemo.csproj`（net8.0 SDK-style）构建路径**未验证**（本机无 .NET SDK，无法验证；见 §4）。
2. 20 条正运动声明的**返回类型 `int` 在真值里无依据**（`zmotion.csv`/`zmotion_cpp.csv` 的原型列不给返回类型），W1 的 §7 诚实边界表未列。
3. `dmc_change_speed`（`LeadshineDmcController.cs:68-69`）**声明了但主体从未调用**（死声明）。不影响正确性，但属可清理项。

### 5.7 一致（无需差异）的部分

- 58 / 58 / 0 / 0 的总数与分类：**完全一致** ✅
- 6 个套件的 k/n（`mc_gts 14/15`、`mc_leadshine 12/13`、`mc_zmotion 13/13`、`mc_gaochuan 0/1`、`mc_softwin 0/1`、`mc_all 39/43`）：**完全一致** ✅
- 编译结果（csc，6 套件 0 错 0 警）：**完全一致** ✅
- `out/mc_all` 的 5 个适配器与单品牌套件同源：**一致**（SHA256 逐文件核对） ✅
- 6 个 zip 包与 `out/` 目录内容一致：抽包逐文件 SHA256 比对，**6/6 全部 0 处不一致** ✅
- 单文件交付 `上位机代码工厂.html` 与 `gen/` 源同源：按 `concat.js` 的拼接规则重算并逐字符比对，**完全一致** ✅
- W1 报告里 62 处真值行号引用：**62/62 正确** ✅

---

## 6. ApiChecklist 的 k/n 是否真实（不是硬编码）

**真实。**

- 计算逻辑在 `gen/core.js:812-827`：
  ```js
  var total = 0, totalOk = 0;
  for (var i = 0; i < adapters.length; i++) {
    var a = adapters[i];
    if (!a.api || a.id === 'virtual') continue;
    total += a.api.length;
    var ok = 0;
    for (var j = 0; j < a.api.length; j++) { if (a.api[j].ok === true) ok++; }
    totalOk += ok;
    s += '## ' + a.label + ' (' + a.dll + ') —— 已核对 ' + ok + ' / ' + a.api.length + ...
  }
  s += '## 总进度: 已核对 ' + totalOk + ' / ' + total + ...
  ```
  **k 是按 `api[j].ok === true` 实时统计的，n 是 `api.length`**，没有任何字面量。
- 口径与代码一致：`ok:false` 的「未实现」条目（固高 1 条、雷赛 1 条）计入 n、不计入 k；骨架品牌的 api 条目**没有 `ok` 字段**
  （`gen/adapters_kb.js:795-797`），`ok === true` 判定为 false ⇒ k=0/n=1。
- 我独立复算（直接 `require` `gen/adapters_kb.js` 读 api 数组，不看 .md）：

| 品牌 | KB 里 n | KB 里 k | 生成的 .md 段头 | 生成的 .md 表行 | 逐行一致 |
|---|---|---|---|---|---|
| gts | 15 | 14 | `已核对 14 / 15` | 15 行 | ✅ |
| leadshine | 13 | 12 | `已核对 12 / 13` | 13 行 | ✅ |
| zmotion | 13 | 13 | `已核对 13 / 13` | 13 行 | ✅ |
| acs | 9 | 0 | **未出现在任何套件** | — | —（ACS 不在全品牌套件内） |
| softwin | 1 | 0 | `已核对 0 / 1` | 1 行 | ✅ |
| gaochuan | 1 | 0 | `已核对 0 / 1` | 1 行 | ✅ |
| **mc_all 合计** | 43 | 39 | `已核对 39 / 43` | 43 行 | ✅ |

- 段头文本、**每一行表格的 `f` / `use` / `chk` 全文**、以及 `## 总进度` 数字，我按 KB 重算后与 6 份 `ApiChecklist.md` **逐字符一致** ⇒ .md 确实是 KB 现算生成的，没有手改、没有硬编码。
- 补充：ACS 在 `gen/adapters_kb.js:662-673` 有 9 条 api 且 k=0，但 **ACS 不包含在 `mc_all` 套件里**，所以不计入 39/43。这是设计如此，不是漏算。

---

## 7. 判定

### 判定：**合格**

### 理由

1. **核心目标达成且可复核**：58 条 DllImport，我用自写解析器（未用 W1 的工具）独立复算为 **58 双绿 / 0 需自证 / 0 不存在**，
   与 W1 自述数字完全一致；每条都能给出「PE 导出表行号 + 官方 C# 绑定行号 + 官方 C 头文件行号」三出处。
2. **W1 工具没查的那一层我也查了，结果也是干净**：参数表（58/58 匹配）、返回类型（38/38 可核对项一致）、
   结构体字段序/类型/偏移/总长（3 个结构体全一致）、回零模式宏（4 个值全一致）。**没有发现任何一处签名错误。**
3. **三个重点问题全部处置正确**：
   - (a) 正运动 20 条全改 `zauxdll.dll`，**零残留 `zmcaux.dll`** 声明；
   - (b) 8 个臆造正运动名**全部换成官方真名**，`ZAux_Direct_GetIfIdle` / `ZAux_Direct_Single_Move` 写法完全正确，每条三处真值同时命中；
   - (c) 固高/雷赛 8 个臆造项 **5 个换成官方等价物 + 3 个删除并标注「未实现」**，**没有一个「看起来像」的非官方名**。
4. **编译通过**：6 套件 csc 全部 0 错 0 警，demo 可跑通。
5. **k/n 真实**：`gen/core.js:817-819` 实时统计，我复算的 6 份清单与 KB 逐字符一致。
6. 遗留的 2 处偏差（`leisai.csv:12` 引错、宏表表述不成立）**都在文档/注释层，不触及任何 P/Invoke 声明与签名**，
   属可一处 sed 修完的量级，不构成"修复不成立"。

### 为什么不是「有条件合格」

「有条件合格」意味着核心结论有前提未满足。这里核心结论（58/58 双绿 + 签名全对 + 编译通过 + k/n 真实）**全部成立且我已独立复现**，
剩下的都是文档级小瑕疵与"报告没覆盖到的边角"。给一个技术验证全部通过的结果扣上"有条件"，反而不诚实。

### 为什么不是「不合格」

没有任何一条声明落在"不存在"或"只在导出表"里；没有臆造名残留；没有伪官方名；没有编译失败。

---

## 8. 遗留问题清单（按优先级）

| # | 级别 | 问题 | 位置 | 建议 |
|---|---|---|---|---|
| 1 | **必改** | `leisai.csv:12` 引错，`dmc_get_CardInfList` 实际在 `leisai.csv:10` | `gen/adapters_kb.js:315`、`out/mc_leadshine/docs/ApiChecklist.md:19`、`out/mc_all/docs/ApiChecklist.md:19`、`上位机代码工厂.html:1836` | 改成 `leisai.csv:10`；改完重跑 `node concat.js` |
| 2 | **必改** | 「diType/doType 宏值在官方宏表里没有给出」不成立（`MC_GPI=4` / `MC_GPO=12` 在 `gts_hdr_macros.csv:17,22`） | `out/mc_gts/src/Adapters/GoogolGtsController.cs:551-552`、`out/mc_all/.../GoogolGtsController.cs:551-552`、`gen/adapters_kb.js:36,121-122`、`out/mc_gts/docs/ApiChecklist.md:32`、`out/mc_all/docs/ApiChecklist.md:50`、`上位机代码工厂.html:1557,1642` | 改成"宏表有候选值但真值未标注对应关系，仍待手册确认"，别写"查不到" |
| 3 | 建议 | W1 报告 §7 诚实边界表未列「20 条正运动声明的返回类型 `int` 在真值里无依据」 | `评审_Trae修复.md:212-226` | 补一行（`zmotion.csv`/`zmotion_cpp.csv` 原型列无返回类型） |
| 4 | 建议 | 报告未提 `GT_GetStandardHomePrm`/`GT_ExecuteStandardHome` 的 "MCT2008工具" 变体是「已导出=0」 | `评审_Trae修复.md:100` | 补注 `dll_exports.csv:11708` / `:11529` |
| 5 | 建议 | 报告未提 `zauxdll.dll` 在 PE 导出表里**只有 64 位**（423 行全部 `位数=64`），32 位 Windows 部署会加载失败 | `评审_Trae修复.md` §7 | 补部署约束；或 csc 加 `/platform:x64` 明确目标 |
| 6 | 建议 | 核对工具不比对参数表/返回类型/结构体，报告口径与工具能力不匹配 | `mcopilot/scripts/verify_trae_pinvoke.py:321-334` | 给工具补一层签名比对，或在报告里注明"参数表系人工核对" |
| 7 | 建议 | `build/GlueDemo.csproj`（net8.0）构建路径未验证（本机无 .NET SDK） | `out/mc_*/build/GlueDemo.csproj` | 在有 SDK 的机器上补验一次；CI 里加 `dotnet build` |
| 8 | 可选 | `dmc_change_speed` 声明了但从未被调用（死声明） | `out/mc_leadshine/src/Adapters/LeadshineDmcController.cs:68-69` | 接到 `MoveJog` 的变速路径上，或删掉 |
| 9 | 说明 | 「修复前基线 61/33/0/28」无 VCS/无备份，**不可复现**，只能验算术自洽 | `评审_Trae修复.md` §2 | 下轮起把 `out/` 纳入版本库；报告里标注该基线为"单方陈述" |

---

## 9. 复现方式（本次复核用的方法，均可自行重跑）

1. 扫描：对 `out/mc_*/src/Adapters/*.cs` 逐行抓 `[DllImport("dll", ...)]`，在紧随其后的行里用
   `static extern <ret> <name>(<args>);` 模式取签名（**不用 `\b` 词边界正则**——下划线是单词字符，会漏配 `GT_SetTrapPrm`）。
2. 真值索引：`dll_exports.csv` 按 `(DLL小写, 规范化函数名)` 建索引，规范化 = 去前导 `_` + 去 `@N` 后缀（32 位 stdcall 装饰名）；
   `zmotion.csv`/`gts.csv`/`leisai.csv`（C# 绑定）与 `zmotion_cpp.csv`/`gts_hdr.csv`/`leisai_cpp.csv`（C 头文件）按 `(DLL小写, 函数名)` 建索引。
3. 三态判定：
   - 双绿 = PE 导出表有「已导出=1」**且** 官方 C# 绑定有（本批 58 条同时还命中了官方 C 头文件）；
   - 需自证 = 只在 PE 导出表（已导出=1），官方绑定/头文件都没有；
   - 不存在 = PE 导出表（已导出=1）与官方绑定/头文件都没有（含「符号在但已导出=0」与「DLL 名在 PE 表里根本没有」）。
4. 签名比对：把 C# 参数与官方原型参数各自剥掉参数名、`ref/out`、属性，按「整数宽度 / 浮点宽度」归一后逐位比。
5. 编译：`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:exe /out:<TEMP> src\Core\*.cs src\Virtual\*.cs src\Adapters\*.cs samples\*.cs`
   （**输出必须指向 TEMP**：仓库 `out/` 对本次评审是只读的，`build_net48.bat` 会往 `..\bin\` 落产物）。
6. k/n 复算：直接 `require('gen/adapters_kb.js')` 读 `kb.<brand>.api`，数 `ok === true`，再与 `out/mc_*/docs/ApiChecklist.md` 的段头/表行/总进度逐字符比对。
