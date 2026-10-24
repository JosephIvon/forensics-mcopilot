# samples/servo/ 真机样本：来源、许可与再获取

> 这份文件是**许可与来源说明**，不是数据的一部分。
>
> ⚠️ **不要修改 `samples/servo/` 下任何 CSV 的内容**（包括头部 `#` 注释行）。
> 每份 `.truth.json` 里都记着对应 CSV 的 `csv_sha256`，改一个字节哈希就对不上，
> 真值链（独立基线 ↔ 样本 ↔ 工具读数）当场断链。补说明只能加在**本文件**里。

---

## 1. 清单

| 文件 | provenance | 来源 | 许可 / 归属 | 权威锚点 | 独立基线 | 对应门禁 |
|---|---|---|---|---|---|---|
| `darus3252_prbs_pos_ppi.csv` | `real_record` | DaRUS-3252（斯图加特大学数据仓储）`Validation/FrequencyDomain/tracking_pos_PRBS/PRBS_PPI_s_0.mat`（滚珠丝杠试验台，PRBS 位置参考，位置环闭合） | **CC BY 4.0** | 数据集 DOI `10.18419/DARUS-3252`；论文 DOI `10.1016/j.conengprac.2023.105607`；源文件 `PRBS_PPI_s_0.mat` md5 `5abbac465808bf62d4b1aa8cedff66ca`；数据集自公开机械模型 ω₀=215.1584 rad/s | 复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核 | `darus3252`、`units` |
| `darus6114_x_prbs.csv` | `real_record` | DaRUS-6114 `P60_prbs.csv` 的 x 轴（位置指令 + 负载位置反馈 + 电机转矩；机器工具，x 轴转矩通道叠加 PRBS 扰动） | **CC BY 4.0** | 数据集 DOI `10.18419/DARUS-6114`；每轴 ω₀ / D 见数据集 `parameters.txt` | 复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核 | `darus6114`、`units` |
| `darus6114_x_velsweep.csv` | `real_record` | DaRUS-6114 `01_sysid_freq/x_velSweep_s0_p50_dir_pos.csv`（x 轴速度扫频记录） | **CC BY 4.0** | 数据集 DOI `10.18419/DARUS-6114`；x 轴 ω₀=489.3 rad/s | 复算脚本未入库（2026-10-22 按 git ls-files 复核：HEAD 无此文件）；当日一次性独立复算，数值不可自动复核 | `darus6114sweep`、`units` |
| `klipper_resonance_x.csv` | `real_record` | Klipper 论坛附件 `raw_data_x_20230409_173541.zip`（真机 `TEST_RESONANCES AXIS=X` 原始加速度计数据） | Klipper **GPLv3** 社区数据（见 §2.3） | zip sha256 `c9aa0b48416d47aab62dd2d300b8ba660a6da3ec98303448b8a7fb3aeeece859`；Klipper 公开源码 `klippy/extras/resonance_tester.py` 的默认扫频参数 | Welch+Kaiser 与自写 H1/FFT 两路线互证（复算脚本未入库，2026-10-22 按 git ls-files 复核：HEAD 无此文件；当日一次性独立复算） | `klipper`、`units` |
| `twincat_export10.csv` | `real_record` | Beckhoff **CODESYS Scope View (TwinCAT 3)** 导出，原始文件 `Export10_244531.csv`（9175989 字节，sha256 `070dc74f…`），导出时段 2023-05-24 11:27:40.879–11:27:59.529 | 厂商工具导出，厂商知识产权（只作内部测试夹具） | 厂商原始导出 + 上游解析管线 meta（`out/crossval_export10_meta.json`） | `scripts/verify_servo_spectrum.py`（HEAD 实存；独立复算频域口径，不 import mcopilot） | `units` |
| `case_a_normal.csv` / `case_b_resonance.csv` / `case_c_no_feedforward.csv` | `synthetic_fixture` | `make_samples.py` 按二阶模型**合成**（非真机记录） | 本仓库生成 | 同目录 `.truth.json`（与波形同源 → 属**自洽性验证**，不是外部证据） | — | `units` |

**外部证据 vs 自洽性**（habit 3，2026-10-19）：上表 5 份 `real_record` 是**外部证据**（有公开数据集 / 厂商导出可回查）；`case_*` 三份是**自洽性验证**（自己造的数据 + 自己的规则读），**不得**用来支撑任何准确率声明。

---

## 2. 许可与署名

### 2.1 DaRUS-3252 / DaRUS-6114 —— CC BY 4.0

斯图加特大学数据仓储发布，许可 **CC BY 4.0**，允许再分发，条件是署名。署名要素已随数据走：

- 数据集 DOI（两份各一）
- 论文 DOI（3252 有；6114 的论文题名写在 `darus6114_*.truth.json` 的 `paper` 字段）
- 原始文件名与 md5（3252）
- 数据集自己公开的机械模型参数（ω₀ / D）—— 这是**外部真值**，不是本仓库算的

对外发布本仓库时，请把本文件连同数据集 DOI 一起带上。

### 2.2 Beckhoff TwinCAT 导出 —— 厂商知识产权

`twincat_export10.csv` 是厂商工具的导出数据，厂商拥有知识产权；本仓库仅作**内部测试夹具**使用。对外发布前请确认授权范围。

### 2.3 Klipper —— GPLv3 社区数据（本条需注意）

- **来源**：Klipper 社区论坛附件 `raw_data_x_20230409_173541.zip`（zip sha256 见上表）。
- **许可**：Klipper 源码为 **GPLv3**。
- **本仓库做了什么**：`fb` 通道 = zip 里 `TEST_RESONANCES AXIS=X` 的**真机实测加速度**（ADXL345 的 `accel_x`，12 位）；`cmd` 通道 = 按 Klipper **开源源码 `klippy/extras/resonance_tester.py` 的公开默认参数重建**（扫频 5→135 Hz @ 1 Hz/s）——即指令通道是**重建的**，不是记录下来的。
- **定性**：测得的数据本身通常不被视为 GPL 源码的衍生作品；且 `cmd` 通道是依据公开参数重建的（与按公开规格实现的接口类似），**不是** Klipper 源码的复制。
- **仍然要记住的边界**（`klipper_resonance_x.truth.json` 的 `boundary` 字段原话）：响应通道是真机实测加速度（不是位置），指令通道是重建的；**这份数据只能验 FRF 估计器的数据通路与谐振频率读数，不能验伺服闭环位置带宽模型。**
- **建议**：对外发布前请法务/合规过一遍 Klipper 数据的再分发口径；若存疑，可只保留 zip sha256 与下载入口而不入库 CSV（此时 `klipper` 与 `units` 门禁需要改成 CI 下载步骤）。

---

## 3. 再获取路径

| 样本 | 再获取方式 |
|---|---|
| DaRUS-3252 | 数据仓储 DOI `10.18419/DARUS-3252` → `Validation/FrequencyDomain/tracking_pos_PRBS/PRBS_PPI_s_0.mat` → `scripts/` 下的抽取流程生成本目录 CSV |
| DaRUS-6114 | 数据仓储 DOI `10.18419/DARUS-6114` → `P60_prbs.csv`（x 轴）与 `01_sysid_freq/`（扫频）→ 同上 |
| Klipper | 社区附件 `raw_data_x_20230409_173541.zip`，**必须核对 zip sha256** `c9aa0b48…`（指纹不符即拒收，与 `darus3252` 门禁同一纪律） |
| Beckhoff Export10 | 厂商 CODESYS Scope View 导出，核对原始文件 sha256 `070dc74f…` |

原始下载件落在 `out/_dl/`（已被 `.gitignore` 忽略）；**入库的是派生后的规范 CSV + 独立复算出的 `.truth.json`**，两者靠 `csv_sha256` 绑定。

---

## 4. 这几份文件为什么必须在版本库里

**CI 与门禁入口的实况（2026-10-22 按 git ls-files 复核；公开前硬化后补记）**：本仓**已有 `.github/workflows/gates.yml`**（windows-latest + pytest + G1–G12 + 其余六门 ✓），**仍无 `scripts/run_gates.py`**——本文早前版本声称二者存在，已按 `.self-improving/lessons.md` 同日登记的教训条目更正。当前可跑的门禁是 `scripts/` 下 7 支（`gate_anchors.py`、`gate_corpus.ps1`、`gate_docsync.ps1`、`gate_farm.ps1`、`gate_negative.ps1`、`gate_onboard.ps1`、`gate_protocol.ps1`，门名 G1–G12 以 `Add-Gate` 注册），**不存在**名为 `units`/`darus3252`/`darus6114`/`darus6114sweep`/`klipper` 的独立门禁脚本（那 5 个名字是早期设计稿里的，未入库）。

这些文件一旦不在版本库里，**干净检出（fresh clone）上这 5 条门禁会直接 `FileNotFoundError` 退出 1**，CI 就是红的 —— 这不是「测试失败」，是「门禁没跑起来」，比红更糟。

已实测确认（2026-10-21，干净副本复现）：
- 缺这 4 个 CSV → `darus3252` / `darus6114` / `darus6114sweep` / `klipper` 四条门禁 `FileNotFoundError` 退出 1，`units`（整份 pytest）在第一个用例即 `FileNotFoundError`；
- 补齐后 → 12 条门禁中其余 7 条（`encoding` `compile` `docrefs` `sdktruth` `pinvoke` `smoke_modbus` `smoke_slmp`）不依赖任何真机数据即可全绿。

> 纪律沿用本仓库已有的一条：**静默 skip 也算绿 = 最危险的失败模式。** 这些门禁不许在缺数据时改成 skip，必须硬失败。
