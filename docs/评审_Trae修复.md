# 评审_Trae修复 —— 「上位机代码工厂」P/Invoke 签名修复评审

> 评审对象：`<Trae-CN 会话工作区>\temp_20261019_01`（生成器 gen/*.js、产物 out/mc_*/、单文件交付 上位机代码工厂.html）
> 评审时间：2026-10-20
> 唯一依据（只读外部真值，未做任何记忆断言）：
> - `knowledge/sdks/official_api/dll_exports.csv`（DLL PE 导出表；列：DLL, 位数, 函数名, 已导出, 变体）
> - `knowledge/sdks/official_api/zmotion.csv`（正运动官方 C# 绑定）/ `zmotion_cpp.csv`（正运动官方 C 头文件）
> - `knowledge/sdks/official_api/gts.csv`（固高官方 C# 绑定）/ `gts_hdr.csv`（固高官方 C 头文件）
> - `knowledge/sdks/official_api/leisai.csv`（雷赛官方 C# 绑定）
> 补充引用（同一 official_api 目录内的官方头文件派生表，用于结构体字段布局与宏值）：`gts_structs.csv`、`gts_hdr_macros.csv`、`leisai_cpp.csv`

---

## 0. 一句话结论

修复前 61 条 DllImport 声明里 28 条在官方真值中不可用（正运动 20 + 固高 5 + 雷赛 3），本轮全部处理完：
**修复后 58 条声明，58 条双绿（PE 导出表 + 官方绑定/头文件双命中），0 条需自证，0 条不可用**；
其中 3 条官方真值里根本没有等价函数的臆造声明**被删除**并把对应功能标注为「未实现」。

---

## 1. 新增核对工具（长期使用）

`mcopilot/scripts/verify_trae_pinvoke.py`

| 项 | 说明 |
|---|---|
| 扫描对象 | `<Trae>/out/mc_*/src/Adapters/*.cs` 的全部 `[DllImport]` 声明（正则解析，带文件名+行号） |
| 真值层 1 | `dll_exports.csv`（PE 导出表）。**只有「已导出=1」的符号算可 P/Invoke**；「已导出=0」单独判为不可用并说明原因 |
| 真值层 2 | 官方 C# 绑定：`zmotion.csv` / `gts.csv` / `leisai.csv` |
| 真值层 3 | 官方 C 头文件：`zmotion_cpp.csv` / `gts_hdr.csv` / `leisai_cpp.csv` |
| 匹配方式 | 规范化后**精确匹配**（32 位 stdcall 的 `_Func@12` 去前缀/去 `@N` 后匹配）。不用 `\b` 词边界正则（下划线是单词字符，词边界会漏配 `GT_SetTrapPrm`） |
| 三态判据 | `双绿 ok` = 导出表已导出 **且** 官方 C#/C 头文件有；`需自证 needs_proof` = 导出表有但官方绑定/头文件没有；`不可用 missing` = 导出表（已导出=1）没有且官方绑定/头文件也没有。判据只有一条：官方真值里存在 |
| 额外诊断 | DLL 名本身不在 PE 导出表 → 该 DLL 全部声明判不可用（正运动 `zmcaux.dll` 就是这种）；JSON 里给出每条声明的导出表行号/变体、绑定行号、C 头文件行号 |
| 输出 | 默认人读文本报告；`--json` 机器可读；`--strict` 有不可用时退出码 1（CI 用） |

用法：

```bash
python mcopilot/scripts/verify_trae_pinvoke.py            # 文本报告
python mcopilot/scripts/verify_trae_pinvoke.py --json     # 机器可读
python mcopilot/scripts/verify_trae_pinvoke.py --strict   # CI 门禁（有不可用 -> exit 1）
```

三态逻辑已用合成样例自测（`GT_SetTrapPrm`→双绿 / `GT_AddTask`→需自证 / `dmc_conti_da_curve_control`→不可用(已导出=0) / `GT_Fake_Name`→不可用）。

---

## 2. 修复前基线（工具独立复现，与口头结论一致）

```
声明总数(去重) : 61      双绿: 33      需自证: 0      不可用: 28
gts        24 条 (19 双绿 / 5 不可用)
leadshine  17 条 (14 双绿 / 3 不可用)
zmotion    20 条 ( 0 双绿 / 20 不可用)   ← DLL 名 zmcaux.dll 在 PE 导出表里 0 次命中
gaochuan    0 条（骨架，无 DllImport）
softwin     0 条（骨架，无 DllImport）
```

> `dll_exports.csv` 中 `zmcaux` 出现次数 = **0**；`zauxdll.dll` 共 423 行（422 已导出 + 1 未导出），正运动官方 DLL 名确为 `zauxdll.dll`。

---

## 3. 逐条修复清单

### 3.1 正运动 ZMC（20 条声明：20 条不可用 → 20 条双绿）

**DLL 名修正**：`zmcaux.dll` → **`zauxdll.dll`**（`dll_exports.csv` 中 zauxdll.dll 422 个已导出符号；zmcaux 0 次命中）。

8 个臆造函数名 → 官方真名（每条都在「官方 C# 绑定 + 官方 C 头文件 + PE 导出表」三处同时命中）：

| 原声明（不存在） | 改成（官方真名） | 官方 C# 绑定 | 官方 C 头文件 | PE 导出表(64位) |
|---|---|---|---|---|
| `ZAux_Direct_Single_MoveRel` | `ZAux_Direct_Single_Move` | `zmotion.csv:327` | `zmotion_cpp.csv:337` | `dll_exports.csv:336` |
| `ZAux_Direct_Cancel` | `ZAux_Direct_Single_Cancel` | `zmotion.csv:325` | `zmotion_cpp.csv:335` | `dll_exports.csv:334` |
| `ZAux_Direct_Datum` | `ZAux_Direct_Single_Datum` | `zmotion.csv:326` | `zmotion_cpp.csv:336` | `dll_exports.csv:335` |
| `ZAux_Direct_GetFpos` | `ZAux_Direct_GetDpos` | `zmotion.csv:82` | `zmotion_cpp.csv:86` | `dll_exports.csv:86` |
| `ZAux_Direct_GetIdle` | `ZAux_Direct_GetIfIdle` | `zmotion.csv:106` | `zmotion_cpp.csv:110` | `dll_exports.csv:110` |
| `ZAux_Direct_GetAd` | `ZAux_Direct_GetAD` | `zmotion.csv:59` | `zmotion_cpp.csv:63` | `dll_exports.csv:63` |
| `ZAux_Direct_SetDa` | `ZAux_Direct_SetDA` | `zmotion.csv:265` | `zmotion_cpp.csv:275` | `dll_exports.csv:274` |
| `ZAux_Direct_Servo` | `ZAux_Direct_SetAxisEnable` | `zmotion.csv:258` | `zmotion_cpp.csv:268` | `dll_exports.csv:267` |

顺带按官方原型改的参数类型（原声明与官方不符）：

| 声明 | 原类型 | 官方类型（出处） |
|---|---|---|
| `ZAux_Direct_GetAD` | `out int` | `out float pfValue`（`zmotion.csv:59`） |
| `ZAux_Direct_SetDA` | `int` | `float fValue`（`zmotion.csv:265`） |
| `ZAux_Direct_GetIn` | `out int` | `out uint piValue`（`zmotion.csv:108`） |
| `ZAux_Direct_SetOp` | `int` | `uint iValue`（`zmotion.csv:297`） |

注释里提到的 `ZAux_Direct_MoveClockwise/CounterClockwise`（真值里不存在）改为官方 `ZAux_Direct_MoveCircAbs / ZAux_Direct_MoveCirc`（`zmotion.csv:203/198`）。

### 3.2 固高 GTS/GTN（24 条声明：5 条不可用 → 22 条全双绿，2 条删除）

| 原声明 | 处理 | 官方真名 | 官方 C# 绑定 | 官方 C 头文件 | PE 导出表 |
|---|---|---|---|---|---|
| `GT_SetTrapPara` | 改名 | `GT_SetTrapPrm` | `gts.csv:454` | `gts_hdr.csv:513` | `dll_exports.csv:10531` |
| `GT_SetJogPara` | 改名 | `GT_SetJogPrm` | `gts.csv:422` | `gts_hdr.csv:470` | `dll_exports.csv:10477` |
| `GT_SetGoHomePara` + `GT_GoHome(axis)` | 换成官方标准回零 | `GT_GetStandardHomePrm` + `GT_ExecuteStandardHome` | `gts.csv:241` / `gts.csv:119` | `gts_hdr.csv:264` / `:128` | `dll_exports.csv:10183` / `:9997` |
| `GT_GetAi` | **删除 → 未实现** | 官方无等价物 | — | — | 0 次命中 |
| `GT_SetAo` | **删除 → 未实现** | 官方无等价物 | — | — | 0 次命中 |
| `GT_ClrSts(axis)` | 参数个数修正 | `GT_ClrSts(axis,count)` | `gts.csv:81` | `gts_hdr.csv:87` | `dll_exports.csv:9948` |
| `GT_SetDo(type,idx,val)` | 函数名修正 | `GT_SetDoBit(doType,doIndex,value)` | `gts.csv:396` | `gts_hdr.csv:442` | `dll_exports.csv:10438` |

结构体（原结构体字段序/类型全是臆造的，按官方头文件结构体表重建）：

| 原结构体 | 改为 | 官方字段序（`gts_structs.csv`） |
|---|---|---|
| `TTrapPrfPara` | `TTrapPrm` | acc(0) dec(8) velStart(16) smoothTime(24, short) 总长32 |
| `TJogPrfPara` | `TJogPrm` | acc(0) dec(8) smooth(16) 总长24 —— **官方没有速度字段**，Jog 速度改走 `GT_SetVel`（速度符号即方向） |
| `TGoHomePara` | `TStandardHomePrm` | mode(0) highSpeed(8) lowSpeed(16) acc(24) offset(32) check(36) autoZeroPos(38) motorStopDelay(40) pad1..3(44/46/48) 总长56 |

回零模式号用官方头文件宏表（`gts_hdr_macros.csv:163-169`）：`HOME_MODE_LIMIT=10` / `HOME_MODE_HOME=20` / `HOME_MODE_HOME_INDEX=22` / `HOME_MODE_INDEX=30`，取代原来自造的 0/1/2/3。

### 3.3 雷赛 DMC/EMC（17 条声明：3 条不可用 → 16 条全双绿，1 条删除）

| 原声明 | 处理 | 官方真名 | 官方 C# 绑定 | 官方 C 头文件 | PE 导出表(64位) |
|---|---|---|---|---|---|
| `dmc_read_ad` | 改名 | `dmc_get_ad_input(CardNo,channel,ref double Vout)` | `leisai.csv:442` | `leisai_cpp.csv:319` | `dll_exports.csv:1858` |
| `dmc_write_da` | 改名 | `dmc_set_da_output(CardNo,channel,double Vout)` | `leisai.csv:440` | `leisai_cpp.csv:981` | `dll_exports.csv:2666` |
| `dmc_set_servo` | **删除 → 未实现** | 官方无等价物（脉冲卡为硬线使能） | — | — | 0 次命中 |

> 雷赛这两个模拟量官方输出参数名就是 `Vout`（电压），所以**不再做 12 位码值换算**，直接透传电压；这与 GTS 的情况不同（见 §4）。

顺带按官方原型修的参数表（原声明参数个数/顺序/类型都不对）：

| 声明 | 原声明 | 官方原型（出处） |
|---|---|---|
| `dmc_pmove` | `long pos` | `dmc_pmove(UInt16 CardNo,UInt16 axis,Int32 Dist,UInt16 posi_mode)`（`leisai.csv:71` / `leisai_cpp.csv:816`） |
| `dmc_change_speed` | 3 参 | `dmc_change_speed(UInt16 CardNo,UInt16 axis,double Curr_Vel,double Taccdec)` 4 参（`leisai.csv:76` / `leisai_cpp.csv:56`） |
| `dmc_set_homemode` | 8 参且顺序错 | `dmc_set_homemode(UInt16 CardNo,UInt16 axis,UInt16 home_dir,double vel,UInt16 mode,UInt16 EZ_count)` 6 参（`leisai.csv:115` / `leisai_cpp.csv:1041`） |

### 3.4 未动的部分

- **高川 / 软赢**：仍是骨架，**0 条 DllImport**（未新增任何臆造签名），api 条目 1 条且标 `ok:false`（k=0/1）。
- **ACS**：未动（独立整机，无卡驱动可 P/Invoke）。
- `out/mc_all` 里的 5 个适配器与单品牌套件同源（同一份 KB 生成），无独立改动。

---

## 4. 删除的臆造条目（3 条）与「未实现」标注

| 臆造声明 | 处置 | 连带功能标注 | 官方候选（供后续接手册后补齐） |
|---|---|---|---|
| `GT_GetAi` | 删除 DllImport | 固高 `GetAi()` 返回 0 + 注释说明 | `GT_GetAdc(short adc,out double pValue,short count,out uint pClock)`（`gts.csv:129` / `gts_hdr.csv:137`） |
| `GT_SetAo` | 删除 DllImport | 固高 `SetAo()` 返回 `MotionResult.Fail(-300,"[未实现] ...")` | `GT_SetDac`（`gts.csv:393`）、`GT_PtAo`（`gts.csv:336`） |
| `dmc_set_servo` | 删除 DllImport | 雷赛 `Enable()` 返回 `MotionResult.Fail(-300,"[未实现] 雷赛软件使能...")` | 无（脉冲卡硬线使能；总线卡使能接口须按型号手册确认） |

**为什么固高 AI/AO 选「删除+未实现」而不是接 `GT_GetAdc/GT_SetDac`**：
这两个官方函数确实存在（不是臆造），但官方原型里 `GT_GetAdc` 的输出参数只叫 `pValue`、**真值文件没给值域/单位换算**（且另有名字带 Voltage 的 `GT_GetExtAdVoltage`），`GT_SetDac` 收的是 `short` 码值而不是电压。适配层的 `GetAi/SetAo` 契约是**电压**（`core.js` 接口注释 `// V`）。在没有手册值域的前提下接上去＝把未知换算比例写进代码，属于另一种形式的臆造，所以按规则「官方没有等价物的就删掉并标注未实现」，并把官方候选函数与其出处写进 ApiChecklist 的核对要点，留给拿到手册后按官方值域接入。
雷赛则不同：官方原型参数名就是 `Vout`（电压），语义与适配层契约一致，所以**接官方函数**（`dmc_get_ad_input` / `dmc_set_da_output`），不删除。

---

## 5. 顺带修掉的问题（同属「签名错误/产物不一致」）

1. **ApiChecklist 的 k/n 恒为 0** → 改为按 api 条目的 `ok` 标记统计的真实数字（`gen/core.js:apiChecklist`）。头部「持久化警告：重新生成会整表覆盖…」原样保留，并补了「k 的口径」说明（未实现项计入 n、不计入 k）。
2. **清单格式回退风险**：`gen/core.js` 的 apiChecklist 比单文件 HTML 里的版本旧（少「核对记录」列与 k/n）。已把 `gen/core.js` 补齐到与 HTML 一致（列 + k/n + 持久化警告），再用 `node concat.js` 重建 `上位机代码工厂.html`，保证单文件交付与 gen/ 源码同源。
3. **全品牌套件清单只覆盖一个品牌**：`gen/index.js` 原来 `docFiles(cfg,[kb])` 只传目标品牌，`out/mc_all/docs/ApiChecklist.md` 里只有雷赛。已改为全品牌套件传入套件内全部品牌。
4. **README 抬头恒为 "undefined"**：`core.js:readme` 读 `cfg.brandLabel`，而 `index.js` 传的是第二个参数。已修（全品牌套件抬头为「全品牌套件（固高/雷赛/正运动 + 软赢/高川骨架）」）。
5. **SDK 形态表里的 `zmcaux.dll`** → `zauxdll.dll`（`core.js` 的 CapabilityMatrix 与 `Brand` 枚举注释）。
6. **适配器注释里引用不存在的函数**：GTS `GT_SetCrdPrf/GT_CrdLine/GT_CrdArc`（真值里没有）→ 官方 `GT_CrdData/GT_CrdDataCircle/GT_CrdStart/GT_ArcXYR`；雷赛 `dmc_arc_unit`（不存在）→ 官方 `dmc_arc_move_radius_unit / dmc_arc_move_center_unit / dmc_arc_move_3points_unit`；正运动 `ZAux_Direct_MoveClockwise/CounterClockwise` → `ZAux_Direct_MoveCircAbs / ZAux_Direct_MoveCirc`。
7. **能力矩阵里「SDK 签名来自生成器内置知识，未经厂商手册比对，可能有错」** 的表述已更新为当前事实（已对官方真值核对，仍带 [核对] 标记项须按手册确认）；`factory_ui.html` 的诚实边界段落同步更新，并 `node concat.js` 重建单文件 HTML。

---

## 6. 修复后状态（工具实测）

```
声明总数(去重) : 58      双绿: 58      需自证: 0      不可用: 0      (--strict 退出码 0)
gts        22 条 (22 双绿 / 0 / 0)
leadshine  16 条 (16 双绿 / 0 / 0)
zmotion    20 条 (20 双绿 / 0 / 0)
gaochuan    0 条（骨架）
softwin     0 条（骨架）
```

声明数 61 → 58 的差 = 删除的 3 条臆造声明（GT_GetAi / GT_SetAo / dmc_set_servo）。

**ApiChecklist 的 k/n（重生成后）**

| 套件 | 品牌 | 已核对 k / 总 n |
|---|---|---|
| mc_gts | 固高 GTS/GTN | 14 / 15 |
| mc_leadshine | 雷赛 DMC/EMC | 12 / 13 |
| mc_zmotion | 正运动 ZMC | 13 / 13 |
| mc_gaochuan | 高川（骨架） | 0 / 1 |
| mc_softwin | 软赢（骨架） | 0 / 1 |
| mc_all | 合计 | 39 / 43 |

k = 该品牌实际能对上官方真值的条数（`ok:true` 的条目）；标注「未实现」的条目计入 n 不计入 k —— 所以固高是 14/15、雷赛是 12/13（各 1 条为「未实现」），骨架品牌 0/1。

**编译级验证**（`csc` .NET Framework 4，0 错误 0 警告）：gts / leadshine / zmotion / gaochuan / softwin / all 六套件全部 BUILD OK。
（过程中修掉 1 个自己引入的编译错：雷赛 `getAi` 里 `double v;` 传给 `ref` 未赋值 → 改成 `double v = 0;`。）

**重生成产物**

| 文件 | 大小 | 时间 |
|---|---|---|
| `out/mc_gts/` + `out/MotionControlKit_gts.zip` | 68 KB | 2026-10-20 15:15:57 |
| `out/mc_leadshine/` + `out/MotionControlKit_leadshine.zip` | 61 KB | 同上 |
| `out/mc_zmotion/` + `out/MotionControlKit_zmotion.zip` | 61 KB | 同上 |
| `out/mc_gaochuan/` + `out/MotionControlKit_gaochuan.zip` | 50 KB | 同上 |
| `out/mc_softwin/` + `out/MotionControlKit_softwin.zip` | 50 KB | 同上 |
| `out/mc_all/` + `out/MotionControlKit_all.zip` | 140 KB | 同上 |
| `out/mb_temp/` + `out/ModbusDeviceKit.zip` | 18 KB | 同上（test_gen.js 每次都会重出 Modbus 样例包） |
| `上位机代码工厂.html`（单文件交付，concat.js 重建） | 180 KB | 2026-10-20 15:16:30 |

---

## 7. 诚实边界：本轮**没有**验证的东西

以下项真值文件里没有给出，代码里保留 `[核对]` 标记，必须按厂商手册确认后才能上真机：

| 项 | 品牌 | 缺什么 |
|---|---|---|
| `GT_ClrSts`/`GT_SetDoBit` 的 diType/doType 宏值 | 固高 | 官方头文件宏表里没有 `GT_DI_GPI`/`GT_DO_GPO`，代码沿用原取值 1 并标 [核对] |
| `TTrapPrm.smoothTime`（S 曲线平滑时间）量纲/范围 | 固高 | 官方结构体只给 `short` 类型；代码一律填 0（=梯形），**S 曲线当前实际未生效** |
| `TStandardHomePrm.mode` 与 `HOME_MODE_*` 的对应关系 | 固高 | 宏值来自官方头文件宏表，但 mode 取值语义需手册确认 |
| `GT_GetSts` 位定义（使能/运动/报警/限位 bit） | 固高 | 真值只给原型，位表在手册里；代码沿用原 bit 并标 [核对] |
| 固高模拟量 AI/AO 值域/单位换算 | 固高 | 真值未给出；本轮标注未实现 |
| `dmc_set_homemode` 的 mode/home_dir 编号、`dmc_pmove` 的 posi_mode、DI/DO 低有效极性、tacc/tdec 单位 | 雷赛 | 真值只给原型，语义在手册里；代码沿用原取值并标 [核对] |
| 雷赛软件使能 | 雷赛 | 官方无接口，标注未实现 |
| ZMotion `ZAux_Direct_GetAD/SetDA` 量程换算、DATUM 模式号、`Single_Cancel` 的 imode | 正运动 | 真值只给原型；代码沿用原换算/模式号并标 [核对] |
| 全部品牌的 P/Invoke 运行期行为 | 全部 | 只做了编译级验证 + 静态对撞，**从未在真机跑过**（无硬件） |

---

## 8. 复现命令

```bash
# 1) 核对（修复前应为 61/33/0/28，修复后应为 58/58/0/0）
python mcopilot/scripts/verify_trae_pinvoke.py
python mcopilot/scripts/verify_trae_pinvoke.py --json
python mcopilot/scripts/verify_trae_pinvoke.py --strict   # exit 1 = 还有不可用声明

# 2) 重生成六套件
cd <Trae-CN 会话工作区>/temp_20261019_01
node test_gen.js gts
node test_gen.js leadshine
node test_gen.js zmotion
node test_gen.js gaochuan
node test_gen.js softwin
node test_gen.js all        # 全品牌套件（test_gen.js 原本不支持 all，本次已加）
node concat.js              # 重建单文件交付 上位机代码工厂.html

# 3) 编译级验证（每套件 0 错误 0 警告）
cd out/mc_gts && %WINDIR%/Microsoft.NET/Framework64/v4.0.30319/csc.exe /nologo /target:exe /out:%TEMP%/GlueDemo.exe src/Core/*.cs src/Virtual/*.cs src/Adapters/*.cs samples/*.cs
```

---

## 9. 改动的文件清单

| 文件 | 改动 |
|---|---|
| `mcopilot/scripts/verify_trae_pinvoke.py` | **新增**：P/Invoke ↔ 官方真值核对工具（长期使用） |
| `mcopilot/docs/评审_Trae修复.md` | **新增**：本报告 |
| `Trae/gen/adapters_kb.js` | 正运动/固高/雷赛三块品牌 KB 重写（函数名、参数表、结构体布局、api 条目 chk 与 ok 标记） |
| `Trae/gen/core.js` | apiChecklist 补 k/n 统计与核对记录列；README 抬头 bug 修复；CapabilityMatrix 的 DLL 名与 B 级说明更新 |
| `Trae/gen/index.js` | 全品牌套件的 ApiChecklist 覆盖全部品牌；README 抬头传参修正 |
| `Trae/test_gen.js` | 支持 `all` 套件参数（全品牌套件）；其余行为不变 |
| `Trae/factory_ui.html` | 诚实边界/外部证据表述与现状对齐（签名已对官方真值核对） |
| `Trae/上位机代码工厂.html` | 由 `node concat.js` 重建（内嵌上述 gen/ 全部改动） |
| `Trae/out/mc_*/`、`Trae/out/MotionControlKit_*.zip` | 六套件全部重生成 |
