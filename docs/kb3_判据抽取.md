# KB3 判据抽取 —— 把 axiscope 的 C3 输出契约缝进 mcopilot servo

> **来源（只读，权威）**
> `AX\docs\contracts\C3-diagnosis.md`（17 条不可协商规则）、`AX\docs\contracts\C2-features.md`（特征内核）、
> `AX\docs\kb\KB0-conventions.md`（命名/归因族/slug 全集/裁决台账）、`AX\docs\kb\KB3-tuning-rules.md`（R-01…R-30 判据）、
> `AX\docs\kb\KB4-attribution-model.md`（归因树、置信度公式、反事实自检）。
> **本文是抽取记录，不是新知识源。** 每一个 slug、每一条阈值、每一个公式都能在上述文件里指到出处。
>
> **落地目标**：`mcopilot` 的 servo 智能体（`src/mcopilot/agents/servo.py` + `knowledge/servo_rules.json`）
> 输出的诊断，达到「可被追问到底」的等级：每条结论带 slug、每条结论带 ≥2 条证据、每条结论有反证、
> 每个说不清的故障模式都被显式登记为「不可评估」、改进量必须挂在依据层级上。

---

## 0. 口径核对：slug 全集到底是 22 个还是 23 个

**结论：以 KB0 §2 为准，共 22 个 fault_mode slug。**

任务书写的是「23 个」，但权威源不是 23：

| 出处 | 原文 | slug 数 |
|---|---|---|
| `KB0-conventions.md` §2 | 「归因三大族（C3 硬性规则 8）」逐个列出 `mechanical_*` 8 个、`electrical_*` 7 个、`software_induced_*` 7 个 | **22** |
| `KB4-attribution-model.md` §首段 | 「叶子集合 = KB0 §2 的 **22** 个 slug」 | 22 |
| `KB4-attribution-model.md` §6 检查 3 | 「叶集合 = §2 的 **22** 个 slug」 | 22 |

按硬规则 3「**不许臆造 slug**：fault_mode 必须取自 KB0 的 slug 原样字符串」，本文与代码一律用 **22 个**。
多出来的第 23 个如果真存在，只能是编的 —— 所以不编。

AX 文档里还出现过 3 个**不是 KB0 §2 fault_mode** 的字符串，一并登记在此，避免以后被误当成合法 slug：

| 字符串 | 出现位置 | 为什么不进 slug 全集 |
|---|---|---|
| `software_induced_error` | KB3 R-30、KB4 §1.5 | **族级标签**，A-18/A-51 已裁：只能出现在 `family` 键上，**禁入 `fault_mode`** |
| `mechanical_axis_straightness_error` | KB6 §（耦合/寻光）、C7 § | 龙门/标定域的横摆解释项，KB6 明确落 `considered` + `not_evaluable`，不在 KB0 §2 |
| `mechanical_pitch_yaw_wobble` | KB6 §、C7 § | 同上，角度侧解释项 |

**因此：mcopilot 的 `fault_mode` 取值域 = 下面 §1 的 22 个字符串，逐字相同，代码里不写死（存在 `knowledge/servo_rules.json` 的 `fault_modes` 段）。**

---

## 1. 22 个 fault_mode slug 全表

列含义：
- **slug**：KB0 §2 原样字符串（`fault_mode` 字段唯一合法取值）
- **显示名**：人读名（`display_name` / 报告用）
- **一句话定义**：KB3 对应规则的「断言」压缩
- **可判定的信号特征**：axiscope 侧的 C2 路径 / mcopilot 侧的真实波形量
- **AX 锚点**：KB3 规则号 / KB4 归因树节点
- **需要的 C2 特征**：判定所依赖的 C2 路径（mcopilot 侧给出能否算出）

| # | slug | 显示名 | 一句话定义 | 可判定的信号特征（C2 路径 / mcopilot 等价量） | AX 锚点 | 需要的 C2 特征 | mcopilot 可算性 |
|---|---|---|---|---|---|---|---|
| 1 | `mechanical_resonance` | 机械谐振（结构模态被瞬态激励） | 阶跃/加减速瞬态激励结构模态，能量集中在窄带、与指令节律无关 | `resonance.candidates[].{freq_hz, amplitude_ratio_vs_broadband, quality_factor_estimate, present_in_rest}`；mcopilot：`ringing.freq_hz`（过零法）、`freq.freq_hz`+`freq.prominence`（尾段误差谱峰） | KB3 R-03/R-04/R-10；KB4 N-共振节点、CP-1/CP-2 | `resonance.candidates[]`、`spectral.fe`、`step_response[]` | **可算（低频段）**；kHz 段（≥1 kHz）受频带门禁阻塞 → `not_evaluable` |
| 2 | `mechanical_backlash` | 反向间隙 / 失动（lost motion） | 方向反转时出现与行程无关的固定死区，每次反向重复 | `global.backlash_estimate_counts`、`global.reversal_error_counts`；mcopilot：指令速度换向点处的误差平台 `backlash_estimate` | KB3 R-08；KB4 CP-3、CP-5；R-27 仲裁 | `global.*`、`segment_coverage.move` | **可算**（cmd 速度换向 + fb） |
| 3 | `mechanical_friction_stiction` | 静摩擦突破（stiction） | 每次由静止起动出现超出稳态摩擦的转矩尖峰 | `global.friction_stiction_ratio`；`cur_q` 起步窗内局部峰 | KB3 R-06；KB4 CP-3 | `cur_q`、`global.cur_q_rms_pct` | **不可算**（无 `cur_q`）→ `not_evaluable` |
| 4 | `mechanical_crawling` | 低速爬行（粘滑极限环） | 恒低速下速度呈周期性锯齿并完全停止，频率几乎不随速度变化 | `crawling.low_speed_segments[].{is_sawtooth, sawtooth_freq_hz, vel_min_ratio, stall_count}` | KB3 R-05；KB4 CP-4 | `vel_fb`（非派生）、`cur_q`、`encoder.per_rev_periodic_present` | **不可算**（无 `vel_fb`/`cur_q`）→ `not_evaluable` |
| 5 | `mechanical_encoder_periodic_error` | 编码器每转一转周期误差 | 位置误差含锁定于电机轴/标尺旋转周期的周期分量，频率与速度成正比 | `encoder.{per_rev_periodic_present, per_rev_amplitude_counts, detrended_r2}`、`ripple.probing[].dominant_order_per_rev` | KB3 R-07；KB4 CP-4 | `encoder.*`、`meta.axis.motor_rev_counts` | **部分可算**（f∝v 可测；阶次 k 需 CPR 不可算）→ 命中时 basis=`unverified` |
| 6 | `mechanical_loose_structure` | 结构松动 | 反向瞬态重复冲击尖峰，尖峰与反向时刻相关但幅值散布大 | `global.fe_p999_counts / global.fe_rms_counts`、反向尖峰幅值 CV | KB3 R-02；KB4 CP-6 | `global.*`、`event_context.fe_spike_count` | **可算**（p999/rms + 反向尖峰散布） |
| 7 | `mechanical_thermal_drift` | 热漂移 | 保持位置随温度单调漂移，而非高频误差恶化 | `global.thermal_drift_counts_per_min`、`global.thermal_fe_correlation_r` | KB3 R-01；A-64（结构性真空） | `temp` 通道 | **不可算**（无 `temp`）→ `not_evaluable` |
| 8 | `mechanical_double_inertia` | 低频传动链双惯性（皮带/绳/减速器） | <400 Hz 存在谐振-反谐振对（极点零点交替） | `resonance.candidates[].{is_double_inertia_pair, antiresonance_freq_hz}` | KB3 R-09；KB4 CP-1 | `cur_q`（相干）、`vel_fb` | **不可算**（无 `cur_q`）→ `not_evaluable` |
| 9 | `electrical_current_loop_bandwidth` | 电流环带宽不足 | 电流环交越相对速度环过低，转矩指令跟踪滞后 | `meta.drive.current_loop_bandwidth_hz` vs `velocity_loop_gain_hz`；支路 B：`ff_mismatch.fe_vs_accel_corr` + `spectral.cur_q.tonality_index` | KB3 R-12；KB4 CP-8 | `cur_cmd`、`cur_q`、`drive.*` | **不可算**（无 `cur_q`/`cur_cmd`/drive 参数）→ `not_evaluable` |
| 10 | `electrical_velocity_pi_detune` | 速度环 PI 失谐 | 速度环交越/相位裕度落在稳定裕度之外，谐振峰低频、衰减慢 | `bandwidth.{phase_margin_deg, gain_margin_db}`、`step_response[].damping_ratio_estimate` | KB3 R-13；KB4 §1.1 速度环节点 | `bandwidth.*`（实测扫频） | **不可算**（无扫频/频响）→ `not_evaluable` |
| 11 | `electrical_position_pi_detune` | 位置环 PI 失谐 / 增益过高自激（hunting） | 保持位置时出现窄带极限环，频率与位置环带宽相当 | `step_response[].{limit_cycle_present, limit_cycle_freq_hz, limit_cycle_amplitude_counts}` | KB3 R-14；KB4 CP-9 | `step_response[]`、`bandwidth.*` | **部分可算**（极限环频率/幅值可测；实测交越频率不可得 ⟹ 封顶 0.6、basis=`unverified`） |
| 12 | `electrical_feedforward_mismatch` | 加速度前馈失配（加/减速段跟随误差不对称） | 加速段跟随误差显著大于减速段（或反之），误差与指令加速度强相关 | `ff_mismatch.{asymmetry_ratio, fe_vs_accel_corr, residual_slope_vs_jerk_corr}`；mcopilot：`accel_rms / decel_rms` | KB3 R-15/R-26；KB4 CP-1/CP-7/CP-8（**头号混淆对**） | `pos_cmd`、`fe`、`vel_cmd` | **可算** |
| 13 | `electrical_torque_ripple` | 转矩纹波 | `cur_q` 窄带峰 + 整数/半整数阶次结构，位置侧未响应 | `spectral.cur_q.{dominant_freq_hz, tonality_index, harmonic_ratios}` | KB3 R-11；KB4 CP-2 | `cur_q` | **不可算**（无 `cur_q`）→ `not_evaluable` |
| 14 | `electrical_motor_heating` | 电机发热 / 转矩常数漂移 | 温升使 `k_t` 漂移，同等位移指令下电流需求上升 | `global.{cur_q_rms_pct, cur_q_saturation_ratio, thermal_fe_correlation_r}` | KB3 R-16；A-64（结构性真空） | `temp` + 冷/热机配对 | **不可算** → `not_evaluable` |
| 15 | `electrical_resolution_quantization` | 分辨率 / 量化噪声主导 | 位置测量量化台阶相对容差过大，误差呈台阶 + 小幅极限环 | `quality_ref.quantization_step_counts`、`global.fe_sign_change_rate_hz`、`spectral.fe.tonality_index` | KB3 R-17 | `quality_ref.*`、`meta.encoder_lines` | **可算**（反馈量化台阶 + 误差符号翻转率可测） |
| 16 | `software_induced_host_thread_jitter` | 上位机线程调度抖动造成跟随误差尖峰 | 误差尖峰与上位机停顿事件以优于同步不确定度的精度相关 | `event_context.{fe_spike_aligned_to_host_pause, host_pause_max_ms, alignment_residual_ms}` | KB3 R-18；KB4 CP-6/CP-10 | `events.jsonl` | **不可算**（无事件流）→ `not_evaluable` |
| 17 | `software_induced_interp_buffer_underrun` | 插补缓冲区欠载 | 路径段误差阶跃与 `interp` 欠载事件对齐 | `event_context.interp_underrun_during_path`、`tracking.path_segments[]` | KB3 R-19；KB4 算例 B | `events.jsonl` | **不可算** → `not_evaluable` |
| 18 | `software_induced_bus_cycle_miss` | 现场总线丢周期 / WKC 异常 | 指令单周期保持、反馈跳变，与 `network` 事件对齐 | `event_context.{bus_cycle_hold_max_ms, fe_spike_aligned_to_network_miss}` | KB3 R-20/A-45 三条件；KB4 CP-10 | `events.jsonl` + 驱动器 WKC | **不可算** → `not_evaluable` |
| 19 | `software_induced_late_vision_result` | 视觉测量结果迟到 | 视觉结果到达晚于轴消费它的需要时刻，误差呈「等后突进」 | `event_context.vision_result_latency_p95_ms` | KB3 R-21 | `events.jsonl` + 视觉通道 | **不可算** → `not_evaluable` |
| 20 | `software_induced_pulse_eq_overwritten` | 换型流程覆盖脉冲当量 / 标定系数 | 同一运动在不同 recipe 下呈比例性位置偏差，与方向无关、无每转周期 | `event_context.step_labels[].recipe` + 误差/行程回归斜率 | KB3 R-22/R-27；KB4 CP-5 | `events.jsonl`（recipe）、`meta.counts_per_mm` | **部分可算**（比例偏差 β 可测；recipe 阶跃不可测）→ 按 R-27 落 `considered` + `not_evaluable` |
| 21 | `software_induced_settle_window_too_short` | 到位判定窗口过短 | 「到位」判定窗短于实际整定需要，报告到位时轴仍在振铃 | `median(settling_time_ms) ≥ 1.2 × (t_done − t_start)` | KB3 R-23；KB4 CP-9 | `events.jsonl`（`move_started`/`move_done`） | **不可算** → `not_evaluable` |
| 22 | `software_induced_polling_latency` | 到位判定靠轮询带来的叠加误差 | 到位状态由上位机按固定周期轮询读取，误差预算被 `T_poll × vel` 截断 | `T_poll`（motion 事件间隔中位数）、到位时刻散布 | KB3 R-24；KB4 CP-9 | `events.jsonl` | **不可算** → `not_evaluable` |

### 1.1 三族在 mcopilot 的落点

| 族 | mcopilot 现状 | 本次落地 |
|---|---|---|
| `mechanical_*` | 有（SRV-02 振铃），但无 slug | 8 个 slug 全部登记：4 个可命中（SRV-08/09/10/11），4 个进 `not_evaluable` |
| `electrical_*` | **完全没有** | 7 个 slug 全部登记：3 个可命中（SRV-12/13/14），4 个进 `not_evaluable` |
| `software_induced_*` | **完全没有** | 7 个 slug 全部登记：**全部 `not_evaluable`**（无 `events.jsonl` / recipe 上下文，R-30 登记义务） |

> **软件族为什么一条都命中不了（重要且必须说清）**
> KB3 的族级纪律 + KB4 INV-5/INV-6 + CAP-2 规定：没有 `events.jsonl`（`event_context.available == false`）时，
> `software_induced_*` 7 个叶**全部不可达**，只允许「时间共现」表述，且**必须**逐条登记进 `differential.not_evaluable`。
> mcopilot 的 servo 目前**没有事件流输入通道**（CSV 只有波形列），因此软件族在本版本里
> **只能整族 `not_evaluable`**——这是契约要求的结果，不是偷懒。
> 解锁路径写在每条 `not_evaluable` 的 `unlocks` 里：导出 `events.jsonl`（C6 §1 词表）+ 给出同步证据
> ⟹ 解锁 R-18…R-24、R-28（软件族内互斥仲裁）。
>
> **这一条是本报告与 axiscope 的最大结构差异**，如实记录在文末「关键取舍」。

---

## 2. 要新增到 mcopilot 的规则清单（SRV-08 起）

### 2.1 命名与冲突检查

- 现有规则：`SRV-01`…`SRV-07`（判定逻辑与数值**不动**，只加 slug 映射与证据层）。
- 新规则从 `SRV-08` 排到 `SRV-29`，与现有 id 无冲突。
- **规则 id ↔ AX 规则号**：`SRV-nn` 的 `ax_rules` 字段指向 KB3 的 `R-xx`；两者不是同一套编号体系，
  报告里同时出现（`SRV-12` / `R-15`），避免"看着像同一套、其实不是"。
- **知识与代码分离**：所有 slug、阈值、判据（条件 + 比较符 + 阈值）都在 `knowledge/servo_rules.json`；
  `servo.py` 里只放**信号计算**（特征提取，等价于 C2 的角色）与**通用求值器**（按 JSON 条件表逐条比对）。

### 2.2 新规则总表

| 规则 id | fault_mode | 族 | AX 锚点 | 能否在真实数据上命中 | 缺特征时的落点 |
|---|---|---|---|---|---|
| SRV-08 | `mechanical_resonance` | mechanical | R-02/R-10 | **能**（低频段） | 缺 `fb`/`cmd` → `not_evaluable`；kHz 段 → 频带门禁 `not_evaluable` |
| SRV-09 | `mechanical_backlash` | mechanical | R-08/R-27 | **能** | 无换向点 → 判据不成立（**未命中**，不是不可评估） |
| SRV-10 | `mechanical_loose_structure` | mechanical | R-02 | **能** | 同上 |
| SRV-11 | `mechanical_encoder_periodic_error` | mechanical | R-07 | **能（受限）** | 速度档位 < 2 → 未命中；无 CPR → 结论 basis=`unverified` + 列入待补数据 |
| SRV-12 | `electrical_feedforward_mismatch` | electrical | R-15/R-26 | **能** | 无 `cmd` → `not_evaluable` |
| SRV-13 | `electrical_position_pi_detune` | electrical | R-14 | **能（受限）** | 无保持段 → 未命中；无实测交越频率 → 封顶 0.6、`unverified` |
| SRV-14 | `electrical_resolution_quantization` | electrical | R-17 | **能** | 反馈非量化 → 未命中 |
| SRV-15 | `mechanical_friction_stiction` | mechanical | R-06 | 否 | **必 `not_evaluable`**（`absent_torque_channel`） |
| SRV-16 | `mechanical_crawling` | mechanical | R-05 | 否 | **必 `not_evaluable`**（`absent_torque_channel` + `absent_velocity_feedback`） |
| SRV-17 | `electrical_torque_ripple` | electrical | R-11 | 否 | **必 `not_evaluable`**（`absent_torque_channel`） |
| SRV-18 | `electrical_current_loop_bandwidth` | electrical | R-12 | 否 | **必 `not_evaluable`**（`absent_torque_channel`） |
| SRV-19 | `electrical_velocity_pi_detune` | electrical | R-13 | 否 | **必 `not_evaluable`**（`absent_frequency_response`） |
| SRV-20 | `mechanical_double_inertia` | mechanical | R-09 | 否 | **必 `not_evaluable`**（`absent_torque_channel`） |
| SRV-21 | `mechanical_thermal_drift` | mechanical | R-01 | 否 | **必 `not_evaluable`**（`absent_temp_channel`） |
| SRV-22 | `electrical_motor_heating` | electrical | R-16 | 否 | **必 `not_evaluable`**（`absent_temp_channel`） |
| SRV-23 | `software_induced_host_thread_jitter` | software_induced | R-18 | 否 | **必 `not_evaluable`**（`absent_events_jsonl`） |
| SRV-24 | `software_induced_interp_buffer_underrun` | software_induced | R-19 | 否 | **必 `not_evaluable`**（`absent_events_jsonl`） |
| SRV-25 | `software_induced_bus_cycle_miss` | software_induced | R-20 | 否 | **必 `not_evaluable`**（`absent_events_jsonl`） |
| SRV-26 | `software_induced_late_vision_result` | software_induced | R-21 | 否 | **必 `not_evaluable`**（`absent_events_jsonl`） |
| SRV-27 | `software_induced_pulse_eq_overwritten` | software_induced | R-22/R-27 | 否 | **必 `not_evaluable`**（`absent_recipe_context`） |
| SRV-28 | `software_induced_settle_window_too_short` | software_induced | R-23 | 否 | **必 `not_evaluable`**（`absent_recipe_context`） |
| SRV-29 | `software_induced_polling_latency` | software_induced | R-24 | 否 | **必 `not_evaluable`**（`absent_events_jsonl`） |

**新增规则数 = 22（SRV-08…SRV-29）**；其中 **7 条可命中**（SRV-08…SRV-14），**15 条结构性地进 `not_evaluable`**。

### 2.3 可编码的判定公式与阈值（Python 伪码）

> 变量名对齐 mcopilot 现有波形量：
> `w.t`（秒）、`w.cmd`（指令位置）、`w.fb`（反馈位置）、`w.err`（误差列，可为 None）、`w.vel`（速度列）、`w.torque`（转矩/电流列）、
> `w.fs`（采样率）、`m = step_metrics(w)`、`so = second_order`、`ea = error_analysis(w)`、`ringing`、`freq`（尾段误差谱）。
> **所有数字阈值都在 `servo_rules.json` 的 `thresholds` 段**，伪码里写的是阈值**键名**。

#### SRV-08 `mechanical_resonance` —— 振铃频率与误差谱主频一致 → 结构模态

```python
# 前置：单次阶跃（m["is_step"]），有 fb/err
ring_f = ringing["freq_hz"]                 # 过零法振铃频率
tail_f = freq["freq_hz"]                    # 尾段误差 DFT 主频
match  = abs(ring_f - tail_f) / tail_f      # 两个独立估计器的一致性
prom   = freq["prominence"]                 # 主峰幅值 / 其余 bin 中位数

命中 ⟺ ring_f >= th["osc_freq_min_hz"]              # 12.0
       AND ring_f <= th["osc_freq_max_hz"]          # 120.0
       AND match <= th["resonance_freq_match_max"]  # 0.08（两估计器差 ≤8%）
       AND prom  >= th["resonance_prominence_min"]  # 8.0（窄带，峰/其余中位 ≥8）
```

- 证据：`ringing.freq_hz`（条件）、`spectral.fe_tail.freq_hz`（条件）、`spectral.fe_tail.freq_match_ratio`（条件）、`spectral.fe_tail.prominence`（条件）。
- 降级：`w.fb` 或 `w.err` 缺失 ⟹ `not_evaluable`（`absent_feedback_channel`）；`m["is_step"]` 为假 ⟹ **未命中**（阶跃类指标不适用，登记 `rules_skipped`）。
- **频带门禁**：kHz 级结构模态（R-03，band⊥=2000 Hz）在 `fs < 8 kHz` 时**物理不可观测** ⟹ 登记 `not_evaluable`
  （`blocked_by = band_gate_fs_1k`，`scope = "R-03 的 kHz 分支"`），**禁止**写"未发现谐振"。

#### SRV-09 `mechanical_backlash` —— 反向失动

```python
# 反向点：指令速度换向且换向前后速度幅值 ≥ th["backlash_min_speed"]
v_cmd   = diff(cmd) / dt
rev_idx = [i for i in 换向点]
# 每个反向点的失动量 = 反向后 |err| 的平台值 − 基线 |err|
baseline_rms = rms(|err| 在远离反向点的样本)
backlash_est  = mean_over_reversals(plateau_i - baseline_rms)
backlash_cv   = stdev(plateau_i) / mean(plateau_i)

命中 ⟺ len(rev_idx) >= th["backlash_reversal_min_count"]   # 2
       AND backlash_est / ea["rms"] >= th["backlash_ratio_min"]  # 3.0（R-08: ≥3·fe_rms）
       AND backlash_cv <= th["backlash_cv_max"]              # 0.30（R-08 重复性）
       AND baseline_rms / backlash_est <= th["backlash_baseline_ratio_max"]  # 0.30（只在反向出现）
```

- 证据：反向点数、失动量/fe_rms 比、失动量 CV、基线占比。
- 降级：无 `cmd` ⟹ `not_evaluable`；换向点 < 2 ⟹ **未命中**（无反向语境，判据不成立，不是"没有间隙"）。

#### SRV-10 `mechanical_loose_structure` —— 反向冲击幅值散布大

```python
spike_i = max|err| 在反向点后 th["loose_spike_window_s"] 窗口内
spike_cv = stdev(spike_i) / mean(spike_i)

命中 ⟺ len(rev_idx) >= th["backlash_reversal_min_count"]        # 2
       AND fe_p999 / ea["rms"] >= th["loose_p999_over_rms_min"]  # 4.0（R-02#2）
       AND spike_cv > th["loose_spike_cv_min"]                   # 0.40（R-02 vs R-08 的区分量）
```

- **与 SRV-09 互斥**：R-02/R-08 用"重复性"区分 —— 间隙是**平台**（CV ≤ 0.3），松动是**冲击**（CV > 0.4）。
  代码里两个规则的 `excludes` 互相声明，命中一个就把另一个写进 `ruled_out_alternatives`。
- 降级：同 SRV-09。

#### SRV-11 `mechanical_encoder_periodic_error` —— 误差主频随速度线性变化

```python
# 恒速档位：把指令切成 |v_cmd| 近似恒定且 ≥ th["encoder_min_speed"] 的段
levels = [(v_mean_i, dom_freq_i)]        # 段内误差谱主频
if len(levels) >= th["encoder_min_speed_levels"]:   # 2
    pred = f1 * v2 / v1                  # f ∝ v
    err_ratio = abs(f2 - pred) / pred
命中 ⟺ err_ratio <= th["encoder_freq_speed_tol"]      # 0.15
       AND prom_i >= th["encoder_prominence_min"]      # 8.0（窄带）
```

- 判据来自 R-07 的**可算子集**：R-07 要求 `encoder.per_rev_periodic_present`、`phase_locked_to_pos_modulo`、主阶次 k 与 CPR 成整分数 ——
  这些都要 `meta.axis.motor_rev_counts`（CPR），mcopilot **没有元数据输入** ⟹ 命中时 basis 只能是 `unverified`，
  且必须写进 `next_data_to_collect`：「提供电机每转 counts（CPR）+ ≥2 整转匀速段，确认主阶次 k」。
- **与 SRV-16 爬行的区分量**（KB3 R-05/R-07 的排除项）：爬行 f ≈ 常数，编码器周期误差 f ∝ v。代码按此互斥声明。

#### SRV-12 `electrical_feedforward_mismatch` —— 加/减速段误差不对称

```python
a_cmd = diff(cmd) / dt
accel_rms = rms(|err| where a_cmd > th["ff_accel_min_accel"])   # 加速段
decel_rms = rms(|err| where a_cmd < -th["ff_accel_min_accel"])  # 减速段
asymmetry_ratio = accel_rms / decel_rms          # C2 定义：有向量
A_s = asymmetry_ratio if asymmetry_ratio >= 1 else -1/asymmetry_ratio   # A-26 镜像
fe_vs_accel_corr = pearson(|err|, |a_cmd|)

命中 ⟺ (A_s >= th["ff_asymmetry_min"])            # 1.5（分支①：欠补偿，加速段占优）
       OR (A_s <= -th["ff_asymmetry_min"])         # -1.5（分支②：过补偿，减速段占优）
       AND fe_vs_accel_corr >= th["ff_accel_corr_min"]   # 0.6（R-15）
       AND accel_rms > 0 AND decel_rms > 0         # 两侧都要有样本
```

- **分支②必须实现**（A-26）：`kff > 1` 与 `kff < 1` 严格镜像，否则会系统性漏判"减速段占优"那一侧。
- 证据：`ff_mismatch.asymmetry_ratio`、有符号 `A_s`、`ff_mismatch.fe_vs_accel_corr`、`ff_mismatch.accel_regime_rms`、`ff_mismatch.decel_regime_rms`。
- 降级：无 `cmd` ⟹ `not_evaluable`；只有单侧加减速样本 ⟹ **未命中**。

#### SRV-13 `electrical_position_pi_detune` —— 保持段窄带极限环

```python
# 保持段：尾部 |v_cmd| ≈ 0 且持续 ≥ th["dwell_min_samples"] 样本
dwell_samples = 尾段静止样本数
lc_freq  = freq["freq_hz"]                 # 尾段主频（保持段上的窄带振荡）
lc_amp   = max|err - median(err)| 在尾段
settle_band_counts = 0.02 * m["span"]

命中 ⟺ dwell_samples >= th["dwell_min_samples"]        # 50
       AND lc_freq >= th["limit_cycle_freq_min"]        # 20.0（R-14）
       AND lc_freq <= f_b                                # 可靠频带内
       AND lc_amp >= th["limit_cycle_over_band_min"] * settle_band_counts  # 0.5（R-14）
       AND prom >= th["limit_cycle_prominence_min"]      # 8.0
```

- **封顶**：判据里用了等效带宽（估计值，不是实测）⟹ 按 KB4 CAP-1，置信封顶 **0.60**；
  实测交越频率缺失 ⟹ `basis = unverified`，`next_data_to_collect` 写「补 0–2×带宽扫频」。
- 降级：无保持段 ⟹ **未命中**（没有 hunting 语境）。

#### SRV-14 `electrical_resolution_quantization` —— 量化台阶主导

```python
# 量化台阶：反馈相邻可读值的最小正间隔（仅当反馈为整数/离散计数时成立）
deltas = [abs(fb[i+1]-fb[i]) for i in range(n-1)]
quant_step = min(d for d in deltas if d > 0)   # None ⟹ 反馈非离散
# 误差符号翻转率（近零乱翻 ⟹ 白噪声型抖动）
sc = 符号翻转次数 / 时长 → fe_sign_change_rate_hz

命中 ⟺ quant_step is not None
       AND quant_step >= th["quant_step_over_band_min"] * settle_band_counts  # 0.3（R-17）
       AND fe_sign_change_rate_hz >= th["quant_sign_change_rate_min"] * w.fs  # 0.25（R-17）
       AND prom <= th["quant_tonality_max"]             # 25.0（谱平坦，用峰突出度的倒数口径近似）
```

- `prom`（峰/其余中位）越小说明谱越平坦，用它做 R-17 `tonality_index ≤ 0.25` 的**代理**，阈值单独放 JSON 并在证据 `note` 里写明是代理量。
- 降级：反馈为连续量（无离散台阶）⟹ **未命中**（不是量化主导）。

#### SRV-15…SRV-29 —— 结构性不可评估

这 15 条**不写求值代码**，只写「所需输入清单 + 不可评估登记」。
通用求值器发现 `requires` 里的输入缺失 ⟹ 直接产出 `not_evaluable` 条目：

```python
# 通用（对 SRV-15…SRV-29 生效）
缺 = [k for k in rule["requires"] if k not in present_inputs]
命中 ⟺ 缺 == []
not_evaluable ⟺ 缺 != []  ⟹ {fault_mode, blocked_by, why: 缺什么, unlocks: 补上能解锁哪条判据}
```

`present_inputs` 由波形实际列决定：`cmd` / `fb` / `err` / `vel` / `torque` / `vel_fb`（+ 非波形输入 `temp` / `events` / `sweep` / `recipe` / `cpr` / `drive_params`）。
**mcopilot 永远缺的**：`torque`（除非 CSV 里有电流列）、`temp`、`events`、`recipe`、`sweep`、`cpr`、`drive_params`。

### 2.4 现有 SRV-01…SRV-07 → slug 映射表

> 一条规则可对应多个 slug：给**主 slug**（结论归属）+ **备选 slug**（同一现象的其他解释，进 `differential.considered`）。

| 规则 | 现象 | 主 slug | 备选 slug | 备注 |
|---|---|---|---|---|
| SRV-01 | 超调量偏大 | `electrical_position_pi_detune` | `mechanical_resonance`、`electrical_velocity_pi_detune` | 增益过高/阻尼不足优先归电气族 |
| SRV-02 | 位置响应周期性振铃 | `mechanical_resonance` | `electrical_position_pi_detune`、`mechanical_double_inertia` | 与新规则 SRV-08 是"现象 vs 证据链"两级 |
| SRV-03 | 实测跟随误差远大于二阶预测 | `electrical_feedforward_mismatch` | `mechanical_resonance`、`electrical_velocity_pi_detune` | 等效模型没覆盖真实行为 |
| SRV-04 | 实测明显小于理论值 | `electrical_feedforward_mismatch` | — | **反向/良性结论**（说明前馈在起作用），不进故障假设，只作反证来源 |
| SRV-05 | 误差与速度高度相关、比值恒定（type-1） | `electrical_feedforward_mismatch` | `electrical_velocity_pi_detune`、`mechanical_resonance` | 缺速度前馈 |
| SRV-06 | 整定时间远长于二阶预测 | `electrical_velocity_pi_detune` | `mechanical_resonance`、`mechanical_loose_structure` | 实际带宽低于设定值 |
| SRV-07 | 到位后误差不收敛 | `mechanical_resonance` | `electrical_position_pi_detune`、`electrical_resolution_quantization` | 持续余振 |

映射表放在 `knowledge/servo_rules.json` 的 `legacy_rule_slugs` 段，代码不写死。

### 2.5 频域判据的四个前提（追加裁决：指令刷新成分 / 稳态窗 / 判据分母 / 措辞）

> 这一节是**追加裁决**，来源是 2026-10-20 复核交叉验证数据时发现的三处硬伤：
> 「cmd/fb/err 上有一条 99.6 Hz 的线」被不同口径读成了三件完全不同的事。
> 下面每一条都写明「为什么」和「代码里怎么落」，避免以后再被改回去。

#### 2.5.1 谱线是真是假：按**绝对幅值相对误差动态量级**判，不看频带能量占比

| 口径 | 结论 | 处置 |
|---|---|---|
| 频带能量占比（cmd 12~120 Hz 占 65.71%） | **错**：整条 cmd 都在动，低频（爬行）能量占绝大部分，与「有没有窄带线」无关 | 作废，不进代码 |
| 相对突出度（该谱峰比邻频高多少） | **不够**：只说「这根线很尖」，不说「这根线有多大」 | 报告里**不再单独作为判据**，只作为辅助信息 |
| **谱线绝对幅值 ÷ 误差动态量级** | ✅ 唯一可比的口径：回答「这根线相对误差自身的大小可不可忽略」 | 进代码，阈值 `spectral_line_over_dynamic_min = 0.05` |

- 判据：**`line_over_dynamic < 0.05` ⟹ 该谱峰不作为物理现象** ⟹ 依赖它的判据降级为
  `not_evaluable`（`blocked_by = spectral_line_below_dynamic_floor`），**不进 `hypotheses[]`**。
- **分母用「同一稳态窗内」误差的去偏置动态 std**（`err_dynamic_std_window`），
  全记录口径（`err_dynamic_std`）**一并报出**但不作为判据分母。
  理由：阶跃响应的全记录 std 被阶跃瞬间的尖峰抬高一个量级，拿它当分母会把
  **真实谐振**判成「幅值可忽略」（`case_b_resonance` 的 35 Hz 线就是这么被抹掉的）。
  频谱讲的是「这一段里有没有一个相对误差自身量级不可忽略的窄带成分」，
  分母必须来自**同一段**。
- 报告必须同时给出：谱线**绝对幅值**、误差动态 std（两个口径）、两者比值、频率分辨率 `fs/nfft`。
  **只报无量纲「突出度」是误导**（突出度不随幅值变化）。

#### 2.5.2 指令刷新率：可测量的量，谱线与它重合 ⟹ 「指令刷新成分」，**不是伪谱线**

上位机按固定周期刷新指令 ⟹ `cmd` 上带一个固定周期的成分 ⟹ 轴跟着指令走 ⟹
`fb`/`err` 上**真实地**出现同周期的谱线。这条线：

- **是真实的**（不是数值噪声，也不是 DFT 假峰）⟹ **禁止**使用「伪谱线」这个词；
- 但它属于**指令刷新成分**，**不是被控对象的响应** ⟹ **禁止**进 `hypotheses[]`，
  也**禁止**当成机械谐振的证据。

| 项 | 落点 |
|---|---|
| 测量方法 | `command_refresh_rate()`：**整段记录**上 `cmd` 跳变间隔的**中位数**；跳变阈值 `cmd_jump_min_ratio × cmd 幅值跨度`；`rate ≥ 0.5·fs` 判为「测到的是采样而不是刷新」并作废 |
| 为什么量整段记录 | 刷新率是**指令流本身**的属性，与当前在不在动无关。只量稳态窗会踩坑：Export10 的稳态窗正好落在指令完全静止的空窗里，跳变次数为 0、刷新率测不出来 —— 而那恰恰是最容易把刷新线当成对象响应的场景 |
| 互斥登记 | 谱线频率落在 `k × refresh_rate`（`k ≥ 1`，相对差 ≤ `refresh_harmonic_tol = 5%`）⟹ 判为「指令刷新成分，非被控对象响应」 |
| 登记方式 | **不进假设**，进 `differential.not_evaluable`，`blocked_by = spectral_line_at_command_refresh_rate`，`why` 里写明「谱线 xx.xx Hz 与指令刷新率 xx.xx Hz（k 次谐波）重合，属指令刷新成分，非被控对象响应」 |
| 可复用信号 | `refresh_rate_hz` 写进 `knowledge/servo_rules.json` 的 `signals` 段（含 unit/how/why），**不写死在代码里**；阈值 `refresh_harmonic_tol`、`refresh_max_rate_ratio`、`cmd_jump_min_ratio` 同理 |

#### 2.5.3 频谱窗口必须落在**真稳态段**，否则整条判据不适用

- 判稳态的办法：**指令在窗内能被一条直线拟合**（直线拟合残差 RMS ≤ 5% × 窗内幅值）。
  直线 ⟹ 指令要么不动、要么等速；跨加减速/启停事件时残差立刻变大 ⟹ 判据不适用
  （降级为 `not_evaluable`，`blocked_by = no_steady_segment`），**不许**硬报一个主频。
  - 这个判据是**比例**，不受「这段跑得快还是慢」影响。用绝对速度阈值去卡会出错：
    Export10 的慢速斜坡（2 mm/s）会被「峰值速度的 10%」这种相对门槛筛掉，
    而它恰恰是唯一有诊断价值的一段。
- 候选窗之间**选信息量最大**的一段（窗内误差动态量取各窗的中位数，并列取靠后的一段）：
  「指令一动不动的空窗」对诊断没有价值 —— 它的误差谱只有噪声，看着「很干净」，其实什么都没测到。
- 极限环（SRV-13）必须在**指令保持不动**的段里量：等速段里的周期波动是跟随误差，不是自激。
- 极限环的**幅值**要在保持段**稳定下来之后**量（取最后 1/4，均值也取这一段自己的均值）：
  整段量到的是阶跃瞬间那个尖峰（case_b 的衰减振铃会被量成 97 mm 的「极限环」）。
- 极限环还必须是**持续**的（AX R-14：「静止时也持续、幅值收敛于极限环」）：
  `limit_cycle_sustain_ratio` = 保持段后 1/4 段的振荡幅值 ÷ 前 1/4 段的振荡幅值，
  `< limit_cycle_sustain_min (0.7)` ⟹ 在收敛，不是自激 ⟹ SRV-13 不命中。
  不加这两条，**任何**欠阻尼阶跃响应都会被误报成「位置环增益过高自激」。

#### 2.5.4 频率分辨率与边界 bin

- 谱线频率落在**最低/最高 bin** 时，报告必须给提示：「谱峰落在最低/最高 bin（k=1 即 `fs/nfft`），
  不是可分辨的谱线，不能作为频点使用」。
- 频率分辨率 = `fs / nfft`，报告里必须显式给出（`nfft = 1024`，与旧口径的 2048 不同，两处都写明）。

#### 2.5.5 跟随误差的**常数偏置分解**（P0-3）

`cmd − fb` 差一大截常数时，那**不是跟随误差**（常见于跨轴错配、坐标系没对齐）。
`error_analysis()` 增报：

| 量 | 含义 |
|---|---|
| `mean` | 误差均值（常数偏置） |
| `std` | 误差标准差 |
| `offset_ratio` | `std / peak` |
| `mean_over_std` | `|mean| / std` |
| `offset_suspect` | `|mean| ≥ 3·std` **且** `std ≤ 0.05·peak` ⟹ 判定「疑似两通道不同轴或存在常数偏置，**不作为跟随误差读**」 |
| `dynamic_peak/dynamic_rms/dynamic_std` | 去偏置后的动态部分（判据用的就是这套数） |

`offset_suspect` 成立时：**所有依赖误差的判据降级为 `not_evaluable`**
（`blocked_by = offset_dominated_error`），报告里所有误差类指标都标注「只反映去偏置后的动态部分」。

### 2.6 判据状态必须三选一（`audit` 完整性，F-12 扩展）

每条判据在一次诊断里必须落到**且仅落到**一个状态：

| 状态 | 含义 | 落在哪 |
|---|---|---|
| `rules_fired` | 命中 | `audit.rules_fired` |
| `rules_not_hit` | 执行了，条件不成立 | `audit.rules_not_hit` |
| `rules_skipped` | **因前提不满足没执行** | `audit.rules_skipped`（带 `why` 与「补齐后解锁」） |

> 旧实现只记了「命中」与「没执行」两档，**「执行了但没命中」这一档是空的** ——
> 于是 SRV-01…SRV-07 在正常样例上凭空消失。既有判据也必须进这张台账
> （`diagnose()` 里的 `legacy_status`）。
>
> 「没执行」与「没命中」在报告里必须分开说：
> **「没命中」≠「已排除」**，而**「没执行」更是连测都没测**。

另：**没有判据条件的规则**（SRV-15…SRV-29，它们等的是 mcopilot 没有的输入通道）
**绝不能因为「条件为空 ⟹ 全部成立」就算命中**（空集真值陷阱）。
它们在 `evaluate_rules()` 里直接判 `not_evaluable`，`blocked_by` 取规则自己写的那个。

### 2.7 同一 slug 的多条判据 ⟹ **一条假设、多条证据**

C3 契约里 `hypotheses[]` 是「**候选故障模式**」列表，不是「规则命中列表」。
旧判据（按过零频率判谐振，SRV-02）与新判据（按谱线判谐振，SRV-08）指向同一个 slug 时，
必须合并成**一条假设、两条证据**（`rule_ids = ["SRV-02","SRV-08"]`），
而不是两条同 slug 的假设。合并后：

- 支持证据取并集，反证取并集，`next_data_to_collect` 取并集（按内容去重）；
- 严重度取最大；
- **反事实自检取最保守的那个**（任一规则判 UNRESOLVED ⟹ 整条假设 UNRESOLVED）。

### 2.8 既有判据也必须有反事实自检与「还要补什么数据」

- 既有判据（SRV-01…SRV-07）的竞争解释 = `legacy_rule_slugs` 里的 `alternates`：
  若**另一条已命中的判据**指向同一个竞争 slug ⟹ 两种解释同时成立 ⟹
  本结论判 **UNRESOLVED**（不许独占）。
- `next_data_to_collect` 与 `expected_effect.basis` 写进 `knowledge/servo_rules.json` 的
  `legacy_rules` 段（新增字段，**不改动既有判据的判定逻辑与阈值**），
  满足契约「置信度 < 0.6 的结论必须写明还缺什么数据」。

---

## 3. C3 字段清单（mcopilot 侧落点）

> 字段名沿用 axiscope C3 的语义；mcopilot 不做 C1/C2 的完整实现，只保证**诊断输出层**的字段齐全与可判定。
> 类型：`(类型)`；必填条件：`always` / `cond:<条件>`；取值域。

### 3.1 顶层

| 字段 | 类型 | 必填 | 取值域 | mcopilot 里对应什么 |
|---|---|---|---|---|
| `schema` | str | always | `"mcopilot.servo.diagnosis/1"` | 新增 |
| `case_id` | str | always | 文件名派生 | `Path(csv).stem` |
| `generated_at` | str | always | ISO8601 | 生成时刻 |
| `engine_version` | str | always | 语义版本 | `servo_rules.json.version` |
| `inputs.sample_path` | str | always | 路径 | `w.source` |
| `inputs.present_channels` | list[str] | always | 通道名子集 | 实际命中的列别名键 |
| `inputs.missing_channels` | list[str] | always | 通道名子集 | 未命中的列别名键 |
| `inputs.fs_hz` | float | always | >0 | `w.fs` |
| `inputs.n_samples` | int | always | ≥0 | `w.n` |
| `inputs.freq_limits.fs_hz` | float | always | >0 | `w.fs` |
| `inputs.freq_limits.nyquist_hz` | float | always | >0 | `fs/2` |
| `inputs.freq_limits.reliable_band_hz` | float | always | >0 | `nyquist/1.25`（C2 规则 7） |
| `inputs.freq_limits.blocked_rules` | list[str] | always | AX 规则号 | 频带门禁阻塞的 AX 规则号 |
| `verdict.primary` | str\|null | always | 假设 id 或 null | 排序后第一条假设的 id |
| `verdict.summary` | str | always | 文本 | 面向工程师的一段话（频点/量级/动作/依据层级） |
| `verdict.overall_confidence` | float | always | [0,1] | KB4 §2.2 公式，见 §3.4 |
| `verdict.confidence_note` | str | always | 文本 | 逐格可重算的算式说明 |
| `verdict.actionable` | bool | always | bool | 有假设且最高置信 ≥ 阈值 |

### 3.2 `hypotheses[]`

| 字段 | 类型 | 必填 | 取值域 | mcopilot 里对应什么 |
|---|---|---|---|---|
| `id` | str | always | `H1`… | 排序后编号 |
| `fault_mode` | str | always | **22 slug 全集** | 规则表里的 slug |
| `display_name` | str | always | 文本 | `fault_modes[slug].display_name` |
| `rank` | int | always | ≥1 | 排序位次（严重度优先、置信次之） |
| `confidence` | float | always | [0,1] | KB4 §2.2 公式 |
| `severity` | int | always | 1–5 | 高=3 / 中=2 / 低=1 |
| `rule_ids` | list[str] | always | `SRV-xx` | 命中的规则 id |
| `ax_rules` | list[str] | always | `R-xx` | 对应的 AX 规则号 |
| `supporting_evidence[]` | list[obj] | always | **≥2 条** | 见 §3.3 |
| `contradicting_evidence[]` | list[obj] | always | **可为空数组，但字段必须存在** | 见 §3.3 |
| `ruled_out_alternatives[]` | list[obj] | always | 可为空数组 | `[{fault_mode, reason, measured}]`，必须是 22 slug 内的其它 slug |
| `expected_effect.basis` | str | always | `simulation_validated` \| `rule_heuristic` \| `unverified` | **mcopilot 无仿真器 ⟹ 只可能是后两者** |
| `expected_effect.direction` | str | always | 文本 | 方向（不给数字） |
| `expected_effect.note` | str | always | 文本 | 「本工具无仿真器，改进量不给数字」等 |
| `next_data_to_collect[]` | list[obj] | cond:`confidence < 0.6` | **不得为空** | `[{ask, why, unlocks}]` |
| `counterfactual` | obj | always | `{check, result, note}` | KB4 §4 反事实自检（RESOLVED / UNRESOLVED） |

### 3.3 证据条目

`supporting_evidence[]` 每条：

| 字段 | 类型 | 必填 | 取值域 | 说明 |
|---|---|---|---|---|
| `feature` | str | always | 特征路径 | mcopilot 侧命名空间 `servo.*`（如 `servo.step.ringing_freq_hz`） |
| `value` | float\|bool | always | 实测值 | **必须来自真实计算** |
| `operator` | str | always | `>=` `>` `<=` `<` `==` `!=` `in` | 判据的比较符 |
| `threshold` | float\|bool | always | 阈值 | 来自 `servo_rules.json` |
| `strength` | float | always | [0,1] | KB4 §2.1 的 `S(e)` |
| `rule_id` | str | always | `SRV-xx` | 证据来源规则 |
| `source` | str | always | 文本 | 规则出处（含 AX `R-xx`） |
| `note` | str | always | 文本 | 同源证据 / 代理量等必须写明 |

`contradicting_evidence[]` 每条：

| 字段 | 类型 | 必填 | 取值域 | 说明 |
|---|---|---|---|---|
| `feature` / `value` / `operator` / `threshold` | — | always | — | 同上 |
| `rho_prime` | float | always | >0 | 裕度倍数 |
| `penalty` | float | always | {0.20, 0.10, 0.05, 0.00} | **档位值**，只能由 `rho_prime` 推出（KB4 §2.4） |
| `rule_id` | str | always | `SRV-xx` | — |
| `note` | str | always | 文本 | — |

### 3.4 `differential`

| 字段 | 类型 | 必填 | 取值域 | 说明 |
|---|---|---|---|---|
| `considered` | list[str] | always | slug 或显示名 | 考虑过但没进假设的 slug |
| `not_evaluable` | list[obj] | **不得为空（除非真的全部可评估）** | — | 每条见下 |
| `not_evaluable[].fault_mode` | str | always | 22 slug | 逐模式登记 |
| `not_evaluable[].blocked_by` | str | always | 稳定键名 | 如 `absent_torque_channel`、`absent_events_jsonl`、`band_gate_fs_1k` |
| `not_evaluable[].why` | str | always | 文本 | 缺什么 / 为什么不可评估 |
| `not_evaluable[].unlocks` | list[str] | always | 判据标识 | 补上能解锁哪条判据（`SRV-xx` / `R-xx`） |
| `not_evaluable[].scope` | str | cond:同 slug 另有已评估分支 | 文本 | 标明只是哪一段频带/分支不可评估 |
| `not_evaluable[].family` | str | cond:整族不可评 | 族名 | 族级登记（`software_induced_error` 只出现在这里） |

**缺席扣减口径**（C3 规则 16 / A-73）：`verdict.overall_confidence = C(H_primary) × (1 − 0.05 × min(4, |distinct blocked_by|))`。
**按独立缺席原因计，不按行数** —— 族级标签与它覆盖的叶同源，只扣一次。

### 3.5 `audit`

| 字段 | 类型 | 必填 | 取值域 | 说明 |
|---|---|---|---|---|
| `rules_fired` | list[str] | always | 规则 id | 命中的规则 |
| `rules_skipped` | list[obj] | always | `[{rule_id, reason}]` | **因前提不满足而未执行的规则编号**（F-12 要求显式列出） |
| `rules_not_hit` | list[obj] | always | `[{rule_id, reason}]` | 执行了但未命中（与 skipped 严格区分） |
| `assumptions` | list[str] | always | 文本 | 退化假设（如"反馈为派生速度"） |

---

## 4. 报告新增章节（沿用 `core/report.py` 风格）

| 章节 | 内容 | callout 级别 |
|---|---|---|
| 结论行 | 每条结论带 `fault_mode` slug 与 `basis` | 按原严重度 |
| **不可评估清单** | 逐条 `not_evaluable`，**开头明写「不是没发现问题，是没法评」** | 中（信息缺失是重要事实） |
| **反证与已排除** | 逐条 `contradicting_evidence` + `ruled_out_alternatives` | 提示 |
| **还缺什么数据** | 逐条 `next_data_to_collect`（置信 < 0.6 时不得为空） | 提示 |
| 置信度算式 | `verdict.overall_confidence` + 逐格算式 | 提示 |

### 4.1 报告里的「不许说没发现问题」

现有实现（`build_report`）在 `findings` 为空时写「🟢 低 未发现异常特征」。
按 C3 规则 9 与 axiscope 频带门禁纪律，这句话**只有在本轮确实把所有判据都执行过且都未命中**时才允许出现；
只要有规则因前提不满足未执行，报告必须写成「**N 条判据因前提不满足未执行**」，
并把「未发现异常特征」改成「**在已执行的 M 条判据内未发现异常特征**」。

---

## 5. 交叉验证数据（`samples/servo/twincat_export10.csv`）上的预期行为

真值（`out/crossval_export10_meta.json`）：`fs = 1000 Hz`、18651 点、`cmd_pos`/`fb_pos`/`vel` 四路规范列、
**无电流/转矩通道**、**无 err 列**（误差是派生的 `cmd−fb`）、
`cmd−fb` 的 mean=179.81 / std=0.270（**常数偏置主导，两通道跨轴错配**）。

> 2026-10-20 实跑复核后的**实际行为**（`out/export10.md`）：

| 项 | 预期 | 实测 |
|---|---|---|
| `fs = 1000 Hz` ⟹ `nyquist = 500 Hz`、`reliable_band = 400 Hz` | R-03（kHz）**阻塞** ⟹ `mechanical_resonance` 的 kHz 分支进 `not_evaluable`（`band_gate_fs_1k`） | ✅ 可靠频带 400 Hz |
| 无 `cur_q` | `absent_torque_channel` ⟹ SRV-15/16/17/18/20 全部 `not_evaluable` | ✅ 5 条 |
| 无 `temp` | `absent_temp_channel` ⟹ SRV-21/22 `not_evaluable` | ✅ 2 条 |
| 无 `events.jsonl` | `absent_events_jsonl` ⟹ SRV-23/24/25/26/28/29 + 族级 `software_induced_error` `not_evaluable` | ✅ 6 条 + 1 条族级 |
| 无 recipe 上下文 | `absent_recipe_context` ⟹ SRV-27 `not_evaluable` | ✅ |
| 无扫频 | `absent_frequency_response` ⟹ SRV-19 `not_evaluable` | ✅ |
| `cmd−fb` 常数偏置 179.81 | 误差分解：mean 179.81293 / std 0.27038（std/peak = 0.15%）⟹ 标「**疑似两通道不同轴或存在常数偏置，不作为跟随误差读**」；依赖误差的判据全部 `not_evaluable`（`offset_dominated_error`） | ✅ |
| 指令刷新率 | 实测 `cmd` 跳变间隔中位数 **10.000 ms ⟹ 100.00 Hz**（845 次跳变） | ✅ |
| 稳态窗 | 指令在 10.125~18.624 s 是**等速斜坡**（直线拟合残差 0.7% ≪ 5%）⟹ 取这一段 | ✅（`kind = constant_velocity`） |
| 误差谱窄带线 | 99.609 Hz（bin 102，分辨率 `fs/nfft` = 0.9766 Hz），**绝对幅值 0.005838 mm** | ✅ |
| 该谱线的归属 | 窗内误差动态 std 0.007227 mm ⟹ 比值 80.77%（全记录口径 2.16%）；但它与刷新率 100.00 Hz（1 次谐波，相对差 0.39%）重合 ⟹ **指令刷新成分，非被控对象响应** ⟹ 不进假设，进 `not_evaluable`（`spectral_line_at_command_refresh_rate`） | ✅ |
| 非单次阶跃（多运动段连续轨迹） | 阶跃类判据（SRV-01/02/06/07）与对照类（SRV-03/04）**未执行**，登记 `rules_skipped` 并写明补齐条件 | ✅ 6 条（既有判据）+ 22 条新判据也全部登记 |
| 结论 | **不给结论**（`verdict.primary = null`、`overall_confidence = 0`）：28 条判据因前提不满足未执行（29 条判据里只有 SRV-05 执行了没命中）；`not_evaluable` 27 行 / **8 个独立缺席原因** | ✅ |

> **注意**：Export10 的 `cmd` 是「按 10 ms 刷新的阶梯」——
> 相邻差分算出来的速度是脉冲串（0,0,…,14 mm/s），会把整段轨迹误判成「静止」。
> 指令速度必须用**跨样本差分**（跨过至少一个刷新周期），
> 否则「指令动没动」「加减速段在哪」全判错（已修）。

---

## 6. 落点清单（文件级）

| 文件 | 改动 |
|---|---|
| `knowledge/servo_rules.json` | 新增 `fault_modes`（22 slug 全表）、`family_labels`、`rules`（SRV-08…SRV-29 判据表）、`legacy_rule_slugs`、`legacy_rules`（既有判据的 `next_data`/`expected_effect`/`severity` 元数据，**判定逻辑与阈值一字未改**）、`confidence_model`、`caps`、`signals`（含 `refresh_rate_hz`）、`not_evaluable_asks`；`thresholds` **只增不改** |
| `src/mcopilot/agents/servo.py` | 新增信号层（特征提取）、通用规则求值器、C3 契约层构造、报告新章节；修 P0-1…P0-4 与 F-09/F-12；**修 3 个自查出来的硬伤**：时间列被当成电流列（单字母别名子串匹配）、空条件判据被判命中（空集真值）、稳态窗选段把整段轨迹当静止 |
| `tests/test_mcopilot.py` | 追加 39 条 C3 契约回归（每条新规则的状态、slug 全集、`not_evaluable` 非空、无 basis 百分比、刷新率与刷新成分排除、偏置分解、阶跃优先、判据状态三选一、衰减振铃不许被当自激、P0-1/P0-4 行为） |
| `docs/kb3_判据抽取.md` | 本文件 |

**不动**：`SRV-01…SRV-07` 的判定逻辑与阈值数值（`thresholds` 里原键值一字不改）、其它任何源文件。

> ⚠ **需要上游确认的一处越界**：P0-1 要求在 `core/chart.py` 的画图入口加一条
> 「误差序列长度必须等于样本数」的断言。`core/chart.py` **不在**本任务的可写文件清单里，
> 因此本实现改为在 `servo.py` 侧用 `w.error_signal()` 取误差并在调用前显式断言长度，
> 并在 `servo.py` 末尾注释里写明原因。**上游若已在自己那份 `chart.py` 里加了同样的守卫，
> 本实现可以回退成直接调用**（两处并存不会重复出错）。

### 6.1 关键取舍（需要上游拍板的）

| # | 取舍 | 理由 |
|---|---|---|
| 1 | 谱线判据的分母用**窗内**误差动态 std（全记录口径同时报出） | 阶跃响应的全记录 std 被阶跃尖峰抬高一个量级，用它会把真实谐振判成「幅值可忽略」 |
| 2 | `software_induced_*` 整族（7 条 + 族级标签）**恒为不可评估** | mcopilot 没有事件流输入。契约上这是「诚实的不可评估」，代价是这一族在本工具里永远给不出结论 |
| 3 | 既有判据（SRV-01…07）的 `expected_effect.direction` **留空** | AX 文档里没有逐条的改进方向，编方向就是编知识；只给 `basis` 与「怎么验证」的指向 |
| 4 | 15 条「等数据」规则（SRV-15…29）在本工具里**永不命中** | 它们等的输入（电流/温度/事件流/recipe/扫频）mcopilot 拿不到；写成可求值判据就是假装 |


---

## 7. 附录（v3）：转矩/电流通道 + 事件流 —— 取舍 #2/#4 的部分取代

> 本文 6.1 节的两条取舍在本版**部分失效**，以本附录为准：
>
> - 取舍 #2（软件族恒不可评估）：**失效**。事件流输入落地后，软件族六条可评
>   （SRV-24/25/26/29 无条件可评；SRV-23/28 在同步验证通过后可评）。
>   「整族缺席」只在 `--events` 缺席时出现。
> - 取舍 #4（15 条等数据规则永不命中）：**部分失效**。11 条已可命中
>   （SRV-15/16/17/20/23/24/25/26/28/29 + SRV-18 的拒答原因改指
>   `absent_drive_params`）；仍不可评的是 SRV-18/19/21/22/27。

### 7.1 新输入与求值口径

| 输入 | 形态 | 解锁 |
|---|---|---|
| 转矩/电流列 `cur_q` | CSV 列（`torque`/`current`/`转矩`/`电流`） | SRV-15/16/17/20 |
| 事件流 `events.jsonl` | C6：每行 `{t, source, code, level?, axis?, detail?}`，`t` 为**波形时间轴**秒 | SRV-23/24/25/26/28/29 |

事件证据分两级：

1. **事件侧统计**（次数/时长/间隔/p95）——不需要同步即可评：SRV-24/25/26/29。
   欠载是否落在路径期内用事件流**内部**的 move_started→move_done 括号判断，不碰波形。
2. **因果级信号**（暂停对齐误差尖峰、done 后误差未收敛）——把事件对到波形上，
   只在**同步验证通过**时计算。验证方法 `anchor_matching`：波形侧取**指令跳变
   时刻**（阶梯指令每簇第一个跳变 = 起动沿；不用指令速度阈值穿越——居中差分
   天生带半窗超前，阶梯颗粒度又会抖 ±刷新周期），事件侧取 `move_started`，
   扣除至多一个刷新周期的系统性滞后后，配对中位 |Δt| ≤ `sync_uncertainty_ms`
   （默认 5 ms）才置 `causal_claims_permitted`。**没算出残差不算残差合格**：
   配不上、锚点不足、事件缺沿，一律拒答（SRV-23/28 → `events_sync_unverified`）。

### 7.2 信号基线的五个决定（都踩过实测坑）

| 决定 | 取代的做法 | 坑 |
|---|---|---|
| 巡航分段基准速度用 **p99(|v_cmd|)** | max | 一条回原点的指令瞬跳把 max 抬高 40 倍，分段全军覆没 |
| 派生反馈速度用**跨样本中心差分** | 相邻差分+5 ms 平滑 | 阶梯反馈差出脉冲串，刷新纹波被数成 315 次「失速」 |
| host 尖峰基线用**局部环（±150 ms 去中心窗）最大波动 ×3** | 全局动态 std ×3 | 全局量级被最暴力段抬上天，安静段真尖峰永远够不着 |
| 到位判定基线用**其它 done 的自参照中位数** | 全局动态 std | 同上，且「比正常到位慢一个量级」本就是自参照语义 |
| 谱线配对（SRV-20）误差侧用**幅值最大的窄带线**且先过**刷新线门** | `narrowband_line`（按邻 bin 突出度选） | 突出度是比值：小而尖的刷新梳齿线会赢过幅值大的物理正弦；Hann 主瓣 ±2 bin 又让邻 bin 门槛杀掉一切真线 |

### 7.3 新增阈值（knowledge/servo_rules.json，v2→v3 共 29 项，删 1 项）

`cruise_moving_ratio`、`stiction_breakaway_window_s`、`stiction_breakaway_ratio_min`、
`crawl_stall_speed_ratio`、`crawl_stall_min_samples`、`crawl_stall_count_min`、
`crawl_stall_time_ratio_min`、`ti_res_freq_min_hz`、`ti_pair_ratio_min`、
`ti_pair_ratio_max`、`host_pause_max_ms`、`host_pause_count_min`、`host_err_spike_k`、
`causal_window_ms`、`causal_ring_ms`、`underrun_count_min`、`wkc_count_min`、
`vision_latency_p95_max_ms`、`vision_count_min`、`settle_check_window_ms`、
`settle_err_ratio_max`、`move_count_min`、`polling_interval_max_ms`、
`polling_regular_cv_max`、`sync_uncertainty_ms`、`sync_match_window_ms`、
`sync_min_anchor_pairs`、`sync_cluster_gap_s`、`cmd_jump_min_ratio`（沿用既有键）；
删除 `sync_onset_ratio`（锚点改用指令跳变时刻，速度阈值不再参与）。

新 `blocked_by` 值：`absent_drive_params`、`events_sync_unverified`、
`spectral_line_blocked_or_absent`（各配 ask/why，进 `not_evaluable_asks`）。

### 7.4 反事实（counterfactual）与封顶

10 条可命中判据全部登记了 `next_data`（补什么数据）与 `counterfactual`
（竞争解释的形态判据）。竞争解释同形态成立 ⟹ `UNRESOLVED` ⟹ 置信封顶 0.6
（CAP-9）。速度反馈一律由 fb 差分**派生**（本工具读不到编码器速度直采），
爬行类结论封顶 0.7（CAP-10）。测试用合成夹具把两条封顶都锁住了。

### 7.5 测试与效力边界

`tests/test_torque_events.py`（16 例）：症状齐全夹具（突破峰/爬行/纹波/host 尖峰/
欠载/丢周期/视觉迟到/规整轮询 + 同刻事件流）、移位事件夹具（因果门禁拒答 + 不触发
族级缺席）、干净夹具（配对成立、因果判据不误报）、刷新线主导夹具（配对必须缺位）、
坏行上报、无输入回归（11 条全部不可评且原因逐条对上）。

边界照旧诚实：转矩纹波（SRV-17）只能给「存在窄带成分+频率」，**没有 cpr 就做不了
谐波阶次归因**（1×/6× 转频），条目 note 里写明；SRV-18 的反谐振核对仍需驱动器
电流环参数——机器上下文契约里没有这个入口，不要硬造。

### 7.6 附录（v4）：轴铭牌侧车 axis.json —— SRV-17 从「有窄带成分」升级到「阶次归因」

**输入**：`--axis axis.json`，字段 `cpr`（编码器每转 counts）、`pole_pairs`（极对数）、
`screw_pitch_mm`（丝杠导程）。属 C1 样本包文件——C6 全文没有 cpr 字段
（只有 `counts_per_mm` 且标 L3 待确认），不冒充契约对象，等上游版本化再收编。

**换算**：机械频率 = |v|（mm/s）÷ 导程（mm/rev）；电频率 = 机械频率 × 极对数；
阶次 = 谱线频率 ÷ 参考频率。纹波线距最近整数 ≤ `order_integer_tol`（0.2）才算
「整数阶」，取残差小的那个参考（电/机械）挂 `hypotheses[].attribution`：
6× 电频率 → 逆变器/死区特征（典型阶次 1/2/6×）；每转整数阶 → 机械周期误差特征。

**纪律**：归因不是新证据，不进置信度数学；没有侧车时 `attribution` 字段缺位
——缺位就是「未做归因」。载入纪律与事件流一致：坏字段上报不静默
（非正/非有限数置 0 并点名，依赖它的归因自动缺位）。

**顺带**：SRV-17 的 next_data 注明「已提供 axis.json 侧车时此项视为已满足」；
条件注释里「本工具没有 cpr 输入」的旧说法已订正。

### 7.7 附录（v5）：搁置判据批次 A1/A3/B1/B2 —— 温度、配方、驱动器参数、扫频

**A1 温度列（SRV-21/22）**：CSV 加 `temp` 列（temp/temperature/电机温度）。
1 s 块中位数滤控制纹波，块序列上做温度-误差回归：相关 ≥0.6 且每 K 漂移
≥2 µm 判热漂移（SRV-21）；温升 ≥0.3 K/min 且温度-转矩RMS 相关 ≥0.5 判电机
发热（SRV-22）。单段记录给不了冷/热机配对——next_data 注明要两段同轨迹。

**A3 配方事件（SRV-27）**：事件流埋 `recipe_change`（source=recipe|host）——
C6 契约 L114/L116 本来就定义了配方对齐特征，「契约没入口」是 KB 旧说法的错误。
事件边界切段，段间位移比例（Σ|Δfb|/Σ|Δcmd|）跳变 ≥5% 判当量改写；
段内漂移与边界跳变同量级时反证成立（缓变主导，不是阶跃）。
不打算埋点的用户：本判据转介 SPC（配方语境是它的活）。

**B1 驱动器参数侧车（SRV-18）**：`drive_params.json`
（current_loop_bandwidth_hz 消费；velocity_loop_gain_hz/notch_hz 只登记）。
谐振频率 ÷ 电流环带宽 ≥1.0 判「电流环压不住」；≤0.7 反证成立
（环有裕量，纯机械谐振解释更省）。C6 无此对象，走文件入口，
等上游把 axis.drive_params 版本化后再收编。

**B2 扫频（SRV-19）**：不新增输入文件——cmd 本身是 chirp/扫频即自动检测
（局部基线过零 → 簇窗口 ≥2 s）。相干 H1 估计闭环带宽（γ²<0.8 的 bin 不
参与读数），带宽/ωn ≤0.5 判 PI 失整定。三个实测坑：
① 扫频激励骑在位置保持值上，减全局均值永不过零——基线要用 0.5 s 块中位数；
② 过零密度在高频端过采样，f_lo 按样本取分位会把 2 Hz 起步的扫频抬到
13.5 Hz（sqrt 偏置），bin 网格整个错过通带——瞬时频率要线性插值到均匀
时间网格再按时间取分位（2%/98%）；
③ FRF 只能吃扫频簇窗口——阶跃段的能量会淹没 chirp 频响。
**闭环扫频给不了开环相位裕度，结论只到「带宽实测 + 与 ωn 比值」，不冒充裕度。**

**bug 修复**：SRV-23 反事实竞争 slug 笔误（mechanical_loose_mechanical →
mechanical_loose_structure）；契约测试新增「反事实竞争必须在 fault_modes
枚举里」「inputs_present 的 kind 必须有实现」，堵住这一类静默失效。

**is_step 语义收紧（向更准确的方向）**：moving_samples 从「全记录动样本数」
改为「阶跃响应窗口内（step±0.05/0.5 s）动样本数」——旧行为把「阶跃标定 +
扫频段」的混合记录一律打成非阶跃，ωn 永远出不来；楼梯刷新记录窗口里全是
刷新 tick，判定不变。
