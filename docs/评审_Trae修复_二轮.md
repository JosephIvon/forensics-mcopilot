# 评审_Trae修复_二轮 —— 主控亲自复核 + 两处必改项落地 + 工具补签名比对

> 时间：2026-10-20 15:40–16:00
> 上一轮：`docs/评审_Trae修复验证.md`（W2 独立复核，判定「合格」，并列出 2 处必改 + 9 项遗留）
> 本轮：处理上一轮的必改项、补齐工具能力、并由主控独立复算一遍。

---

## 0. 一句话结论

上一轮判定的 **2 处必改项已全部修掉并重新生成**；核对工具按上一轮第 6 号建议补上了**参数表/返回类型比对**层，
**新工具当场查出上一轮漏掉的一个真实缺陷**：雷赛 `dmc_get_position` / `dmc_get_encoder` 的返回类型
被声明成 C# `long`（64 位），而官方 C# 绑定是 **`Int32`**——**已修**。

修完后独立复算：**58/58 双绿、58/58 参数签名 MATCH、返回类型一致 38 + 无真值依据 20 + 不一致 0**，
6 个套件 csc 编译 **0 错 0 警**，demo 实跑通过。

---

## 一、上一轮 2 处必改项：已修

### 1.1 `leisai.csv:12` → `leisai.csv:10`（引用指错行）

**核验（修前）**：`leisai.csv:10` = `dmc_get_CardInfList`；`:12` = `dmc_get_card_soft_version`。
上一轮判定属实。

**处置**：改源头 `gen/adapters_kb.js`（第 317 行 api 条目的 `chk` 文本），
再 `node test_gen.js` 重新生成 6 个套件 + `node concat.js` 重生成单文件交付。

**修后全仓库检索**：`leisai.csv:12` 命中 **0 处**；`leisai.csv:10` 命中 4 处
（`gen/adapters_kb.js` / `out/mc_leadshine/docs/ApiChecklist.md` / `out/mc_all/docs/ApiChecklist.md` / `上位机代码工厂.html`）。

### 1.2 「diType/doType 宏值在官方宏表里查不到」不成立

**核验（修前）**：`gts_hdr_macros.csv:17` = `MC_GPI,4`；`:22` = `MC_GPO,12`。
上一轮判定属实——原句把「宏名查不到」扩大成了「宏值查不到」。

**处置**：改两处文案（`gen/adapters_kb.js:36` 的 `chk` 文本与 `:121-122` 的代码注释），改为：

> 官方头文件宏表里没有名为 `GT_DI_GPI`/`GT_DO_GPO` 的宏，
> 但有语义接近的候选值 `MC_GPI=4` / `MC_GPO=12`（`gts_hdr_macros.csv:17,22`）——
> 真值未标注它们与 `diType`/`doType` 的对应关系，故仍取 1，
> 必须按《GTN系列运动控制卡用户手册》确认后再上真机。

**取值仍保留 1**：真值无法证明 `MC_GPI` 就是 `GT_GetDi` 的 `diType` 取值（宏表不标用途），
`[核对]` 标记保留。**这是口径修正，不是把不确定改成确定。**

**修后全仓库检索**：`在官方宏表里查不到` 命中 0 处、`没有给出` 命中 0 处、`MC_GPI=4` 命中 8 处。

---

## 二、核对工具补签名比对（上一轮第 6 号遗留项）

上一轮指出：`verify_trae_pinvoke.py` 的判定逻辑是 `exported and binding`，**只比对函数名**，
而 W1 报告却声称「顺带按官方原型改了参数表」——**报告口径与工具能力不匹配**。

### 2.1 补了什么

新增三层比对（`scripts/verify_trae_pinvoke.py`）：

| 层 | 真值来源 | 比对内容 |
|---|---|---|
| 参数个数 | 官方 C# 绑定原型 | 声明实参个数 vs 官方原型参数个数 |
| 参数宽度 | 官方 C# 绑定原型 | 逐位比「整数宽度/浮点宽度」，非标量（指针/结构体/string）只核个数 |
| 返回类型 | 官方 C 头文件原型 | 声明返回类型 vs C 头文件返回类型的宽度 |

**为什么参数用绑定、返回类型用头文件**：
- `leisai.csv` / `gts.csv` / `zmotion.csv` 的「官方原型」列**只有参数、没有返回类型**
  （例：`dmc_get_position(UInt16 CardNo, UInt16 axis)`）——参数是 C# 类型语言，与 C# 声明同语言，可直接比；
- `gts_hdr.csv` / `leisai_cpp.csv` 的 C 头文件原型**带返回类型**
  （例：`long dmc_get_position(WORD CardNo,WORD axis)`）——只有它能核返回类型；
- `zmotion_cpp.csv` 的正运动原型**连返回类型都没有**（例：`ZAux_Close(ZMC_HANDLE handle)`），
  所以正运动的返回类型**在真值里没有依据**——这正是上一轮第 5.6.2 条指出的问题，**现在由工具自动报出来**。

**关键口径**：C 的 `long` 在 Windows(LLP64) 是 **32 位**。雷赛官方 C# 绑定把
`dmc_pmove` 的 `long dist` 写成 `Int32`，与本口径一致。

### 2.2 修前的工具输出 vs 修后

| 指标 | 修前（只比函数名） | 修后 |
|---|---|---|
| 声明总数(去重) | 58 | 58 |
| 双绿 / 需自证 / 不可用 | 58 / 0 / 0 | 58 / 0 / 0 |
| 参数签名 MATCH | *（不测）* | **58** |
| 参数个数不一致 | *（不测）* | **0** |
| 参数宽度不一致 | *（不测）* | **0** |
| 返回类型一致 | *（不测）* | **38** |
| 返回类型无真值依据 | *（不测）* | **20**（全部是正运动） |
| **返回类型不一致** | *（不测）* | **2 → 已修 → 0** |

---

## 三、★ 新查出的真实缺陷（上一轮漏掉）

### 3.1 现象

上一轮把雷赛那两条记作「`dmc_get_position`/`dmc_get_encoder` 为 `long`」并**判为与 C 头文件一致**。
本轮工具做**返回类型宽度比对**时把它标成 `MISMATCH`。追查后确认：**上一轮那一条的口径错了，缺陷是真的。**

### 3.2 三层证据

1. **官方 C 头文件**（`leisai_cpp.csv:552` / `:406`）：
   `long dmc_get_position(WORD CardNo,WORD axis)`、`long dmc_get_encoder(WORD CardNo,WORD axis)`
2. **官方 C# 绑定原文**（`vendor_docs\EMC系列开发头文件\C#\LTDMC.cs`，GBK 编码）：
   ```
   L891: public static extern Int32 dmc_get_position(UInt16 CardNo, UInt16 axis);
   L859: public static extern Int32 dmc_get_encoder(UInt16 CardNo, UInt16 axis);
   ```
   → 厂商自己把 C 的 `long` 映射成 C# **`Int32`**，与 Windows LLP64 口径一致。
3. **Trae 产物**（修前 `gen/adapters_kb.js:346,348`）：
   ```csharp
   private static extern long dmc_get_position(ushort card, ushort axis);
   private static extern long dmc_get_encoder(ushort card, ushort axis);
   ```
   → 用了 C# `long` = **Int64**。

### 3.3 为什么这是真缺陷（不是风格问题）

该 DLL 里的函数返回的是 32 位整数。按 x64 Windows 调用约定，返回值在 `RAX`，
**`RAX` 的高 32 位对 32 位返回值是未定义的**。C# 按 `long` 读取会把那 32 位未定义位一起读进来
→ **指令位置/反馈位置可能出现随机的高位垃圾值**。

这类错误**不会抛异常、不会编译报错**，现场表现为「位置偶尔多出 4 294 967 296 的整数倍」——
正是最难查的一类 bug。上一轮之所以漏，是因为它把 C# 声明**只和 C 头文件**比（两边都写 `long` → 通过），
而**没有和官方 C# 绑定比**——而 C# 声明该对标的是 C# 绑定。

### 3.4 处置

- `gen/adapters_kb.js:346,348`：`long` → `int`
- 对应两条 api 条目的 `chk` 文本改写为**引用官方 C# 绑定的返回类型 + 源文件行号 + LLP64 理由**：

  > 官方C头文件 `long dmc_get_position(WORD CardNo,WORD axis)`（`leisai_cpp.csv:552`）；
  > 官方C#绑定返回 `Int32`（`EMC系列开发头文件\C#\LTDMC.cs:891`）——
  > Windows LLP64 下 C 的 `long` 是 32 位，故 C# 侧必须用 `int` 而不是 `long`
  > （用 `long` 会读到 RAX 未定义的高 32 位）；参数表 `leisai.csv:314`；单位脉冲

- 重新生成 6 个套件 + 单文件交付。

**行为影响**：使用处是 `dmc_get_position(Card, axis) / _ppu[axis]`，
`_ppu` 非整型时两边都走浮点除法、整型时两边都是整除——**除法截断行为不变**，改动只影响封送层。

---

## 四、修后独立复算（主控亲自跑）

### 4.1 核对工具

```
声明总数(去重) : 58   (文件内出现次数 116)
双绿(ok)        : 58
需自证(导出表有) : 0
不可用(missing) : 0
参数签名 MATCH  : 58      参数个数不一致: 0    参数宽度不一致: 0    无原型可比对: 0
返回类型一致    : 38      返回类型无真值依据: 20（正运动）   返回类型不一致: 0
```

按品牌：gts 22/22、leadshine 16/16、zmotion 20/20、gaochuan 0（骨架）、softwin 0（骨架）。

### 4.2 编译自检

`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`（.NET Framework 4，本机自带）：

| 套件 | 源文件数 | 错误 | 警告 |
|---|---|---|---|
| mc_gts / mc_leadshine / mc_zmotion / mc_gaochuan / mc_softwin | 各 11 | 0 | 0 |
| mc_all | 15 | 0 | 0 |

产物输出到 `%TEMP%`，**不在 Trae 仓库里落编译产物**。

### 4.3 Demo 实跑

`mc_leadshine.exe`（默认 `Brand.Virtual`，不需硬件）：
`Open → ConfigureAxis ×3 → Enable ×3 → Home ×3 → WaitHomeDone ×3 → MoveLine → 到位 → 点胶高度跟随` 全程 `[OK]`。

### 4.4 单文件交付完整性

`上位机代码工厂.html` 重生成后抽查 9 个标记全部在位：
`MCKb` / `googol` / `leadshine` / `zmotion` / `gts.dll` / `zauxdll.dll` / `LTDMC.dll` / `MC_GPI=4` / `leisai.csv:10`。

> 体积说明：`concat.js` 打印的是**字符数**（160K chars），文件实际 **176.3 KB（UTF-8 字节）**。
> 比重生成前**增加**约 7.8 KB，增量来自本轮与 W1 加入的核对注记，**无内容丢失**。

---

## 五、判定

**合格。**

理由：

1. 上一轮 2 处必改项已修，检索确认旧文案 0 残留；
2. 工具补齐签名比对层后，58/58 参数签名 MATCH、返回类型不一致 0；
3. **新查出的真实缺陷（`long`→`int`）已修并有官方 C# 绑定原文佐证**；
4. 6 套件编译 0 错 0 警、demo 实跑通过、单文件交付完整。

---

## 六、仍未闭合的遗留项（沿用上一轮清单，状态更新）

| # | 级别 | 问题 | 本轮状态 |
|---|---|---|---|
| 1 | 必改 | `leisai.csv:12` 引错 | ✅ **已修** |
| 2 | 必改 | 宏表表述不成立 | ✅ **已修**（取值仍保留 1 并标 `[核对]`） |
| 3 | 建议 | 诚实边界表未列「20 条正运动返回类型 `int` 在真值里无依据」 | ✅ **工具已自动报出**（`返回类型无真值依据: 20`），报告可据此补一行 |
| 4 | 建议 | 未提 `GT_GetStandardHomePrm`/`GT_ExecuteStandardHome` 的「MCT2008工具」变体是「已导出=0」 | ⬜ 未处理（不影响可用性，报告可补注 `dll_exports.csv:11708`/`:11529`） |
| 5 | 建议 | `zauxdll.dll` 在 PE 导出表里**只有 64 位**（423 行全部 `位数=64`），32 位 Windows 部署会加载失败 | ⬜ 未处理（**建议 csc 加 `/platform:x64` 明确目标**） |
| 6 | 建议 | 核对工具不比对参数表/返回类型/结构体 | ✅ **已补参数表 + 返回类型两层**；结构体布局仍未纳入工具（`gts_structs.csv` 有真值，可后续补） |
| 7 | 建议 | `build/GlueDemo.csproj`（net8.0）构建路径未验证（本机无 .NET SDK） | ⬜ 无法在本环境验证 |
| 8 | 可选 | `dmc_change_speed` 声明了但从未调用（死声明） | ⬜ 未处理 |
| 9 | 说明 | 「修复前基线 61/33/0/28」无 VCS/无备份，不可复现 | ⬜ **建议把 Trae 目录纳入版本库** |

**新增建议**：

| # | 级别 | 问题 | 建议 |
|---|---|---|---|
| 10 | 建议 | 官方 C# 绑定 CSV 的「官方原型」列**不带返回类型**，导致返回类型只能回头查 C 头文件 | ✅ **已做**（见第六节） |
| 11 | 建议 | 工具未覆盖结构体布局（上一轮是人工核对的 `TTrapPrm`/`TJogPrm`/`TStandardHomePrm` 三个） | `gts_structs.csv` 已有字段序/偏移/总长真值，可加第三层比对 |
| 12 | **新发现·必改** | Trae 固高套件用**单卡库**签名，但**没有任何变体约束标注**；多卡版 `gts.dll` 同名同导出符号、每个 API 多一个 `cardNum` 首参 → 混用会让参数整体错位 | ✅ **已修**（见第七节） |
| 13 | **新发现·口径** | 上一轮第 5.6.2 条「20 条正运动返回类型无真值依据」**其实有据可查**——正运动官方 C# 绑定（`Zmcaux.cs`）的 402 条声明**全部返回 `Int32`** | ✅ **已补真值层**，返回类型由 0 无依据变成 58/58 全部有据可查（见第六节） |

---

## 六、补第四层真值：厂商官方 C# 绑定的返回类型与变体

### 6.1 为什么要补这一层

上一轮第 5.6.2 条说「20 条正运动声明的返回类型 `int` 在真值里无依据」。
本轮查清：**它有依据，只是不在 C 头文件里，而在厂商自己的 C# 绑定里。**

| 真值层 | 语言 | 有返回类型？ | 对 C# 声明的适用性 |
|---|---|---|---|
| PE 导出表 | 符号名 | ✗ | 只能证明「函数存在」 |
| `official_api/{gts,leisai,zmotion}.csv` | C# | **✗**（原型列只给参数） | 参数可比，返回类型比不了 |
| `official_api/*_cpp.csv` / `gts_hdr.csv` | C | ✓（但 C 的 `long` 在 Windows(LLP64) 是 32 位） | 返回类型可比，但**口径与 C# 的 `long` 错位** |
| **厂商官方 C# 绑定源码** | **C#** | **✓** | **C# 声明该对标的就是这一层** |

### 6.2 做法：新增可复现的抽取器

`scripts/extract_binding_returns.py` —— 从厂商原始 C# 绑定源码抽取，产出
`knowledge/sdks/official_api/binding_returns.csv`（**3105 条**）：

| 源文件 | 变体 | 条数 |
|---|---|---|
| `正运动_ZMotion/SDK_头文件/Zmcaux.cs` | zauxdll | 402 |
| `gts_sdk/固高GTS资料/02_CSharp封装/64bit_single_card/gts.cs` | 64bit_single_card | 475 |
| `gts_sdk/固高GTS资料/02_CSharp封装/64bit_multi_card/gts.cs` | 64bit_multi_card | 474 |
| `gts_sdk/固高GTS资料/02_CSharp封装/32bit_single_card/gts.cs` | 32bit_single_card | 475 |
| `gts_sdk/固高GTS资料/02_CSharp封装/32bit_multi_card/gts.cs` | 32bit_multi_card | 474 |
| `EMC系列开发头文件/C#/LTDMC.cs`（GBK） | LTDMC | 806 |

CSV 列：`DLL, 函数名, C#方法名, 返回类型, 参数表, 变体, 源文件, 重复次数`。
脚本自动做**变体一致性检查**并在不一致时报出来（见 6.4）。

返回类型分布：`short 2685 / Int32 408 / UInt32 9 / uint 2 / double 1`。

### 6.3 工具升级后的结果

`verify_trae_pinvoke.py` 的返回类型比对改为**优先用厂商官方 C# 绑定**（同一层语言），
C 头文件降为兜底：

```
声明总数(去重) : 58
双绿(ok)        : 58      需自证 0      不可用 0
参数签名 MATCH  : 58      参数个数不一致 0   参数宽度不一致 0
返回类型一致    : 58      ← 修前是 38 一致 + 20 无依据 + 2 不一致
返回类型无真值依据: 0
返回类型不一致  : 0
⚠ 变体间参数表冲突(单卡/多卡同DLL同符号) : 22 条
```

### 6.4 变体冲突：474 个函数的参数表在单卡/多卡之间不同

抽取器自动报出：

```
⚠ 变体间参数表不一致的函数 474 个（同名 DLL + 同名导出符号，混用会导致参数错位）：
   gts.dll!GT_Open:
      - short cardNum,short channel,short param      ← 多卡库
      - short channel,short param                      ← 单卡库
```

这与 mcopilot 知识层已有的记录一致（`knowledge/sdks/gts.json`：
`dll_variant: 64bit_single_card`、note「单卡库与多卡库函数同名，多卡库多一个 cardNum 参数」、
手册 PDF p15 佐证）。**本轮把这条约束从"mcopilot 内部知道"推进到"Trae 交付物上也写明"**（见第七节）。

---

## 七、Trae 固高套件的变体约束：已补

**问题**：Trae 的固高适配器声明的是**单卡库**签名
（`GT_Open(short channel, short param)`），但套件里**没有任何地方说明**这个前提。
用户若把**多卡版 `gts.dll`**（同名、同导出符号、每个 API 多一个 `cardNum` 首参）放进输出目录，
x64 调用约定下参数会整体错位——**打开到错误的卡、参数全乱，而且不抛异常**。

**处置**（改 `gen/adapters_kb.js` 源头后重新生成 6 套件 + 单文件）：

1. **固高 `buildNote`** 追加【重要】段：说明本套件是单卡库口径、多卡库同名同符号但多一个 `cardNum`、
   混用会参数错位、插多卡时怎么办。
2. **`GT_Open` 的 `chk` 核对要点**追加变体口径，并写明多卡库的对照签名。
3. **适配器 P/Invoke 段的注释**新增 `[变体口径·必读]` 五行，写清单卡/多卡差异与后果。
4. 全部条目进入 `ApiChecklist.md` 与单文件交付。

**修后检索**：`单卡库` 12 处 / `cardNum` 20 处 / `变体口径` 8 处
（覆盖 `gen/adapters_kb.js`、6 套件的适配器与 `ApiChecklist.md`、`上位机代码工厂.html`）。

**口径纪律**：变体约束是**部署前提**，不是不确定项——
单卡/多卡的差异有厂商手册 PDF p15 与 4 份 C# 封装源码双重佐证，所以写明；
而 `diType/doType` 的宏值仍取 1 并保留 `[核对]`，因为真值无法证明（宏表不标用途）。
**两者的处理方式不同，依据不同。**
