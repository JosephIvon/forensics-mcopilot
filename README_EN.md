# mcopilot — An Industrial-Engineering AI Assistant Suite for Motion-Control Upper Computers

> From the **industrial requirements baseline of motion-control upper-computer software**,
> take the part that AI can carry — and whose output can be verified by machine —
> and turn it into tools that fit a production process, not a demo.

[中文](README.md) · [Ebook: Forensics-First Learning](book/README.md) · [License: MIT](LICENSE) · [Third-party material inventory: NOTICE.md](NOTICE.md)

---

## 1. Why this exists

**What actually slows engineers down on a factory floor is never "I can't write the code". It is these four things:**

1. **Evidence is scattered** — one intermittent positioning deviation means digging through logs, waveforms and parameter-write history, with no traceable conclusion.
2. **Everyone measures differently** — production, R&D and process engineering each compute their own yield; when the numbers don't match, the discussion is over.
3. **Changing the card means rewriting the code** — "swapping the card doesn't touch business code" stays a slogan because no regression test watches it.
4. **Specs live in people's heads** — a vendor function's parameter count, return width or IO terminal bit gets mistyped, nothing raises an error, and the machine only explodes on the floor.

Quantify the **industrial requirements baseline** (20 items: 11 engineering responsibility domains + 9 engineering capability requirements) item by item, and one conclusion is unambiguous:

**AI can absorb the "engineering burden". It cannot absorb "process judgement".**

The items where AI share is highest share one property:
**① the deliverable is a file, not a feel; ② it can be verified by rule or by number; ③ a machine can catch it when it is wrong.**

| Priority | Requirement | AI share | Tool |
|---|---|---|---|
| ★★★ | R-03 Motion-card adapter layer and brand capability matrix | 85% | `adapter` |
| ★★★ | R-09 Field troubleshooting (intermittent deviation / packet loss / yield drift) | 80% | `forensics` |
| ★★★ | R-10 Software engineering discipline and documentation | 85% | `review` |
| ★★☆ | R-08 SPC statistics, utilization and reporting | 75% | `spc` |
| ★★☆ | **Q-06b Offline diagnosis of servo waveforms** (measured waveform → parameters → root cause) | **75%** | `servo` |
| ★★☆ | R-04 / Q-05 Multi-axis synchronisation and interpolation, algorithm layer | 45~50% | `motion` |
| ★☆☆ | R-05~R-07 Process parameter mining (die attach / dispensing / coupling) | 35~50% | `spc` + phase 2 |
| — | **Q-06a Online servo auto-tuning / inertia identification**, force-control feel, line acceptance sign-off | ~0~15% | **Explicitly not automated** |

**Q-06 is split in two**, because they are often collapsed into one sentence — "servo tuning is hard to automate" — and that loses a whole block:

- **Q-06a Online auto-tuning / inertia identification / resonance avoidance (closed-loop operation on the machine)** — needs an oscilloscope and the real machine; AI stays out of the closed loop, **a human keeps it**.
- **Q-06b Offline waveform diagnosis (read the waveform → back out equivalent parameters → candidate root causes and how to verify them)** — purely offline, numerically verifiable, **AI can carry it**.

**Four things are explicitly left to humans and never touched**: online servo auto-tuning and inertia identification, safety interlocks and E-stop parameters, process-window sign-off, and line acceptance sign-off.
One sentence for the principle: **AI produces drafts and checklists, humans make decisions and sign; anything whose failure could hurt equipment or people is never automated.**

### What the requirements baseline is, and where it comes from

`knowledge/requirements_map.json` is the **single source of truth for requirements** in this toolkit. Its unit of definition is the **engineering deliverable**, not a job posting:

- **11 engineering responsibility domains (R-01 ~ R-11)**: full upper-computer delivery lifecycle, layered architecture and device abstraction, motion-card adapter layer, multi-axis synchronisation and process motion, die-attach / dispensing / coupling processes, device interfacing and data acquisition, field troubleshooting, software engineering discipline and technical mentoring;
- **9 engineering capability requirements (Q-03 ~ Q-10, with Q-06 split into a/b)**: C#/C++ engineering, multi-brand motion-card SDKs, multi-axis synchronisation and electronic cams, online servo tuning vs. offline diagnosis, vision calibration, data and communication capability, cross-discipline technical output.

**How it was compiled**: from the **actual deliverable inventory** of motion-control upper-computer software engineering. Along the way it was **cross-checked once** against a corpus of publicly posted industry roles (`docs/requirements_provenance_20261021/`) — and that corpus was used **only** to confirm the baseline had not missed capabilities the industry universally requires, never to decide what the baseline says.
**Hiring-screening conditions such as degree and years of experience are not engineering deliverables and are explicitly excluded** (see `meta.excluded_from_baseline`).

The full breakdown lives in `out/requirements_map.md` (run `mcopilot requirements report` to generate it); the machine-readable version is `knowledge/requirements_map.json`.

---

## 2. Six minutes to a full run

```bat
:: Windows
mcopilot.bat all --out out

:: or any Python environment
set PYTHONPATH=src
python -m mcopilot all --out out
```

You get the full set of artifacts:

```
out/
├─ requirements_map.md / .html      Industrial requirements baseline and tool-coverage audit
├─ card_capability.md / .html       Motion-card brand capability matrix (incl. the "must ask the vendor" list)
├─ csharp/
│  ├─ IMotionController.cs           Unified abstraction layer (business code sees only mm)
│  ├─ SimulatedMotionController.cs   Offline simulator (runs in CI)
│  ├─ MotionSelfCheck.cs              Simulator self-check (no xUnit needed, runs after compiling)
│  ├─ MotionContractTests.cs         Cross-brand contract test base class (xUnit)
│  ├─ DmcMotionController.cs         Leadshine adapter
│  ├─ ZMotionMotionController.cs     ZMotion adapter
│  └─ GoogolMotionController.cs      Googol adapter
├─ forensics_sample.md / .html     Log forensics report
├─ probe_sample.md / .html         Log-format health report (quantifies format coupling cost)
├─ threshold_sample.md / .html     Threshold sensitivity and false-positive boundary report (which thresholds are brittle, which never fire)
├─ spc_sample.md / .html + *.png   SPC control charts and yield analysis
├─ servo_sample.md / .html + *.png Servo waveform offline diagnosis report
└─ review_sample.md / .html        Code review report
```

**Requirements**: Python 3.9+. The core has **zero third-party dependencies**; matplotlib only adds charts, and its absence does not stop report generation.
The generated C# has been **compiled for real with Roslyn** (`scripts/compile_check.ps1`), and the **simulator self-check actually ran green** (15/15).

---

## 3. Eight agents (nine modules)

### 1. `adapter` — Motion-card adapter layer and capability matrix
> Requirements: R-03, Q-04, Q-03, R-02

Vendor function manuals → C# adapters + P/Invoke declarations + cross-brand contract tests + a brand capability matrix.

```bat
mcopilot adapter gen --sdk dmc --out out
mcopilot adapter matrix --out out
```

> `--out out` means the **artifact root**; the C# sources always land in `out\csharp\` (writing `--out out\csharp` adds an extra directory level).

**The real problems it solves**:
- The unified abstraction layer turns "business code may only use mm / mm·s⁻¹" into a hard constraint — pulse conversion may only appear inside the adapter layer → swapping the card does not change business code.
- The capability matrix puts the **position/velocity unit conventions** side by side. Key differences already recorded: Leadshine uses `pulse/s`, ZMotion uses `units/second` (determined by `UNITS`), and **Googol uses `pulse/ms` (1000× smaller than `pulse/s`)** — **copying a velocity parameter across can be off by 1000×, and the machine will not complain.**
- Contract tests turn "swapping the card doesn't touch business code" into something that goes red and green in CI, instead of relying on people's discipline.
- **Feedback authenticity is declared honestly by the adapter** (`HasRealFeedback(axis)`): on a ZMotion ATYPE=1/7 pulse axis, MPOS is only a copy of DPOS, so following error is **necessarily** always 0 — contract tests therefore mark it as not applicable, do not raise a false "feedback is fake data" alarm on open-loop axes, and do not push engineers to change code that was already correct.

**The tool does not guess vendor behaviour**: functions it cannot find are marked `TODO[verify against the vendor manual]` in the generated code and listed as a to-do in the matrix.
Failing explicitly (throwing `NotSupportedException`) is better than shipping a wrong implementation — and **servo enable on a bus axis is exactly that case**: the CiA402 sequence and SDO entry points are verified, but while "does the controller enable internally, or does the host write the PDO" is undecided, we do not make that decision for the vendor (writing a control word is a machine-safety action that can make the motor move suddenly).

**Every P/Invoke is checked line by line against the vendor's official SDK bindings** (`knowledge/sdks/official_api/*.csv`, exported from the official C# bindings: 402 functions for ZMotion, **1466 declarations / 1463 function names** for Leadshine). Regression tests check **that the function name exists, that the DLL name matches, and that the parameter count matches** — this is not a style check:
before the official bindings were in hand, **ZMotion's `ZAux_Direct_SetAxisParam` and Leadshine's `dmc_set_home_profile` did not exist in the official API at all**, and on real hardware they respectively mean "crashes on connect" and "crashes on homing".
Declaring a function that does not exist is more dangerous than missing an implementation: it does not error, it only explodes on the machine.

**Third vendor: Googol GTS (official-binding grade, all three truth layers present)**. After the official Googol SDK package arrived on 2026-10-20, Googol moved from "degraded bindings, manual PDF only" to **the same tier as Leadshine/ZMotion**:
the official C# binding `gts.cs` (473 DllImport declarations / 30 structs), the official C header `gts.h` (535 `GT_API` declarations, 200 macros), and the **PE export tables** of the 4 `gts.dll` copies plus the one shipped with MCT2008 — all exported into `knowledge/sdks/official_api/gts.csv` / `gts_hdr.csv` / `gts_structs.csv` / `gts_hdr_macros.csv` / `gts_io_terminals.csv` (121-row terminal table), and folded into `dll_exports.csv`.
All 34 bindings were checked item by item: **function name, parameter count, parameter types, ref/out modifiers, field order and byte offsets** all agree, and all 34 functions are exported by the 5 DLL variants (`verified` raised from `needs-manual-check` to `official-binding`).
The calling convention is no longer a guess: line 3 of the official `gts.h` says `#define GT_API extern "C" short __stdcall` → `StdCall`.
This round of ground truth caught three real problems:

- **`GtsHomePrm` is 8 bytes short = out-of-bounds write**: the official C# binding's `THomePrm` has 23 fields (88 bytes), while the official C header's C form uses `long pad3[2]` (80 bytes) — **the vendor's own two artifacts differ by 8 bytes**.
  The adapter must call `GT_GetHomePrm` to read the structure back before modifying fields, and **the DLL writes 88 bytes into our struct**; implementing it at 80 bytes is an out-of-bounds write. It is implemented at 88 bytes (the official C# binding).
- **The reserved-field numbering base was inverted**: the manual uses 0-based (`pad1[0]`, `pad2[1]`), the official C# binding uses 1-based (`pad1_1`, `pad2_2`).
  The manual's "check limit / origin at power-on" flag is `pad2[1]` (**the second slot**); it was originally placed in the first → the enable check never took effect.
- **`GT_GantryHoming` is not exported by the shipped DLLs** even though the official `gts.cs` declares it → copying the official binding gives you `EntryPointNotFound` (same class of issue as ZMotion's `ZAux_Direct_GetNtype`). **This is why the third layer — the DLL export table — cannot be dropped.**

Also established along the way: **GEN (`GTN_`) is not in this SDK package** — there is not a single `GTN_` symbol in `gts.h` / `gts.cs` / the 5 DLLs.
GEN is a separate product line (with its own user manual and basic function manual); the `#include "gts.h"` in its samples is merely a file with the same name.
Supporting GEN requires asking for the GEN SDK package separately.
Googol has **no** `SetPulsePerMm`/`GetPulsePerMm` — the scale is a fractional ratio in `GT_ProfileScale` and the manual gives neither the formula nor its direction, so the adapter **does not push** a scale transform and requires the controller to stay at the default 1:1.

**Leadshine also rose to "manual-grade, four truth layers"**. Reading the *DMC3000 Series Card User Manual V2.0* (334 pages) from §1.4 ordering information all the way to appendix 13 and checking item by item **overturned three of our own implementations that conflicted with the manual**:

- **Latch channels are not selected by a parameter**: `triger_chunnel` of `dmc_set_latch_mode` is a **reserved parameter fixed at 0**; **the channel is determined by the axis number** (LTC0 latches axes 0~3, LTC1 latches axes 4~7); the trigger input is **IN14/LTC0, IN15/LTC1** (table 8.3), **not the "IN4~IN7" previously written**. `ltc_mode`/`filter` of `dmc_set_ltc_mode` are **also reserved parameters fixed at 0** (we had passed invented values thinking they meant "AB phase / latch signal" and "debounce time"). The latch-debounce configuration item was removed (reserved parameter — configuring it does nothing, i.e. a dead config).
- **`IsEnabled` was reading a function the vendor marks "internal use (reserved)"**: `dmc_get_sevon_enable` sits under "//内部使用（保留）" in the official `LTDMC.cs` and its return semantics are unpublished → replaced with **`dmc_read_sevon_pin`**, whose semantics manual §8.13 states explicitly (returns the SEVON terminal level 0/1, indexed **by axis**, on a dedicated terminal, not consuming a general output bit), plus a new `ServoOnActiveLevel` configuration item (the active level depends on how the drive is wired, so it cannot be hard-coded).
- **Pulse cards have no axis-state-machine function at all**: `GetState` used to call `nmc_get_axis_state_machine` — that is an **EtherCAT bus-axis-only** function; calling it on a pulse card only fails or returns bus-axis semantics.
  It now maps the state itself from manual §8.7's `dmc_axis_io_status` bit map (ALM/EL±/EMG/ORG/SL±/INP/EZ/RDY/DSTP) plus `dmc_check_done`.
- Also established: the **pulse ceiling is 4 MHz** (table 1.1 — the previously written 5 MHz was wrong); high-speed compare `hcmp` 0~3 map **one-to-one onto CMP0~CMP3** (previously recorded as "varies by series, must not be reused across models"); and the **reserved parameters of `dmc_set_ltc_mode` and friends are always passed as 0**.

The ground truth exported this round for Leadshine: `leisai.csv` (official C# binding, **1466 declarations / 1463 function names**) / `leisai_cpp.csv` (1513 prototypes from the official C header, **with the real return types**: 15 `long`, 11 `DWORD`, 2 `double`) / `leisai_manual_index.csv` (the manual's appendix 11 function index: 169 entries with chapter and page) / `leisai_io_bits.csv` (the 64-row IO bit map of table 8.3) / `leisai_io_terminals.csv` (the 88-row terminal table of appendix 1, ACC-X400) / `leisai_model_kits.csv` (10 rows of card↔junction-box pairings from §1.4) / `leisai_pdo.csv` (23 CiA402 PDO objects from the DMC-E and EMC appendices, **with a "as the manual states" vs. "as convention dictates" column pair**) / `leisai_dmce_index.csv` (201 function indices from DMC-E appendix 4) / `leisai_emc_index.csv` (174 function indices from EMC appendix 4, **with the manual's own spelling and a verdict column**) / `leisai_dmce_terminals.csv` (the 72-row local interface terminal table from DMC-E appendix 1).
**The IO terminal tables, the card↔junction-box pairings and the pulse frequency — things we used to have to ask the vendor for — now ship with the manual; we copy them ourselves.**
(One more find this round: **an omission in the manual itself** — appendix 11's function index is missing `dmc_get_stop_reason` / `dmc_clear_stop_reason`; it has been raised in the document-request list.)

### 1b. Leadshine bus cards / standalone controllers (DMC-E / EMC) — the scale model is the **exact opposite** of a pulse card
After reading the *Leadshine EtherCAT Bus Card User Manual V2.0/2024.11* (350 pages) and the *EMC Series Bus Standalone Controller User Manual V2.0/2024.1* (271 pages), **two earlier conclusions were overturned**:

- **The scale model is inverted**. A pulse card (DMC3000) divides the pulse scale **on the software side**; a bus card / standalone controller does it **on the controller side** via `dmc_set_equiv(CardNo, axis, equiv)` (set 100 → the controller emits 100 position units = 1 mm, **and the velocity unit becomes mm/s**), **so there is no software-side conversion in that case**. **Mixing the two models = position off by a whole scale factor** — written up as a regression test that pins "the pulse-card adapter must not call `dmc_set_equiv`".
- **EMC is not another function library**: it uses **the same `LTDMC.dll` and the same `dmc_`/`nmc_` function names** (of the 804 declarations in the official EMC package, **zero** carry the `emc_` prefix, and the EMC manual's own C prototypes are all `dmc_`); the only differences are that `dmc_board_init_eth(IP)` goes over Ethernet and that the "card number" is a link number.
  The knowledge base used to hold two contradictory conclusions — "shares the same library" and "EMC is a different library" — which were corrected this round and pinned by a test.

Two **real typos** also turned up: the EMC manual writes `dmc_emg_stop` as `dmc_EMG_stop` and `dmc_axis_io_status` as `dmc_axis_IO_status` (wrong in the body text, in the C prototype and in the appendix 4 index). **PE export names are case-sensitive, so copying them verbatim blows up** — the verdict is three-way agreement: the official EMC C# binding and the export tables of all three DLL versions use the all-lowercase spelling.
Ten further occurrences of `position→positIOn` are **PDF text-layer glyph artefacts**, not typos, so **no false accusation is filed against the vendor**.

**Two items are still too risky to decide alone** (both are in the document-request list): ① in appendix 3, table F3.0, **15 rows have PDO directions opposite to CiA402 convention** — a reversed direction means the axis does not move or the state cannot be read; ② **EMC has no dedicated EMG emergency-stop terminal**; the manual suggests mapping a general input, and **without that mapping on site there is effectively no emergency stop**. Until both are confirmed, **the bus-axis adapter is not landed**, and bus-axis `Enable` stays an explicit failure.

### 1c. Fourth truth layer: **the return types the vendor's own C# bindings declare** (including DLL-variant conventions)
The first three truth layers each cover a part, but **return types could never be compared**:

| Layer | Language | Has return types? | Applicability to a C# declaration |
|---|---|---|---|
| PE export table | symbol names | ✗ | proves only that "the function exists" |
| `official_api/{gts,leisai,zmotion}.csv` | C# | ✗ (the prototype column gives parameters only) | parameters comparable, return types not |
| `official_api/*_cpp.csv`, `gts_hdr.csv` | C | ✓ | comparable, but the **conventions are offset**: under Windows (LLP64) a C `long` is 32-bit while a C# `long` is Int64 |
| **the vendor's own official C# binding source** | **C#** | **✓** | **this is the layer a C# declaration must line up with** |

With the fourth layer in place, "is the return type right" no longer needs a cross-language conversion. The approach is a **new reproducible extractor**, `scripts/extract_binding_returns.py`, which pulls straight from the vendor's original C# binding sources and produces `knowledge/sdks/official_api/binding_returns.csv` (**3105 entries**):

| Source file | Variant | Entries |
|---|---|---|
| `正运动_ZMotion/SDK_头文件/Zmcaux.cs` | zauxdll | 402 |
| `gts_sdk/固高GTS资料/02_CSharp封装/64bit_single_card/gts.cs` | 64bit_single_card | 475 |
| `gts_sdk/固高GTS资料/02_CSharp封装/64bit_multi_card/gts.cs` | 64bit_multi_card | 474 |
| `gts_sdk/固高GTS资料/02_CSharp封装/32bit_single_card/gts.cs` | 32bit_single_card | 475 |
| `gts_sdk/固高GTS资料/02_CSharp封装/32bit_multi_card/gts.cs` | 32bit_multi_card | 474 |
| `EMC系列开发头文件/C#/LTDMC.cs` (GBK encoded) | LTDMC | 806 |

Three things fall out:

- **All 402 ZMotion declarations return `Int32`** — the 20 entries previously recorded as "return type has no ground truth" in fact **do** have evidence; it just was not in the C header. Leadshine's `dmc_get_position` at `LTDMC.cs:891` likewise returns `Int32` (the vendor maps C's `long` to C# `Int32`), which is the evidence for "declaring it as a C# `long` reads garbage from the upper 32 bits of RAX".
- **The four Googol variants are recorded separately** (not one "official signature"). The extractor automatically reports that **474 functions differ in their parameter tables between the single-card and multi-card libraries**: the multi-card library adds a leading `cardNum` parameter to every API.
  Googol has only one library name, `gts.dll`, so you get **the same DLL name, the same export symbol and a different signature** — call a multi-card DLL with the single-card signature and the parameters are shifted wholesale on x64, **and nothing throws**.
- The variant convention also reaches the deliverables: the Trae Googol kit's `buildNote`, the `GT_Open` check notes, the adapter's P/Invoke section comments and `ApiChecklist.md` all state "this kit binds against the single-card library signature".

`scripts/verify_trae_pinvoke.py` is therefore upgraded to a **two-convention** comparison: parameters from the official C# binding prototypes, return types from the vendor's C# binding return types. Result: for 58 declarations, **58/58 parameters agree, 58/58 return types agree, 0 have no ground truth**, plus 22 Googol declarations flagged as "variant parameter-table conflict".

`tests/test_binding_truth.py` keeps this layer from rotting: the table structure, every P/Invoke of this repo's three vendor adapters must be findable in the vendor's C# binding with a matching return width, **the LLP64 trap must not be stepped into** (where the vendor binding says `Int32`, a C# `long` declaration is forbidden), Googol variant differences must be recorded, and **re-running the extractor must produce the same table** (so the ground truth cannot drift away from the vendor's originals).

### 2. `servo` — Offline servo waveform diagnosis (the **reverse** half of the chain)
> Requirements: Q-06b (offline diagnosis); Q-06a (online tuning) is explicitly not done

`motion` is **forward**: given parameters, compute the error. This tool is **reverse**: from the **measured waveform**, back out servo state and root cause.

```bat
mcopilot servo diagnose wave.csv --accel 1000
mcopilot servo synth --model 2inertia     :: synthesise a waveform with known ground truth, to validate the estimator
```

> ⚠ **The report's "evidence basis" section is mandatory reading.**
> Whether a conclusion counts depends on **where the waveform came from**, not on how carefully the tool ran:
>
> | Waveform source | Basis type | What it can show |
> |---|---|---|
> | `synthetic_fixture` (the repo's own 3 fixtures) | **self-consistency check** | truth and waveform are **same-sourced** (one set of model parameters) → the diagnosis matching the truth is **tautological** and **is not evidence of validity** |
> | `synthetic_model_truth` (produced by `servo synth`) | self-consistency check | same as above; it validates "the estimator can solve the same model back" |
> | `real_record` (a real machine record, e.g. `samples/servo/twincat_export10.csv`) | **external evidence** | an independent baseline in `twincat_export10.truth.json` (vendor metadata + a recomputation **not done by this tool**); the conclusion only counts if it lines up with that baseline |
> | `unknown` (a waveform you captured yourself) | unknown | the report says plainly that the basis type cannot be determined |
>
> The tag lives in the **CSV header** (`# provenance: …`) and in the `.truth.json`; the tool labels the report automatically.
> The verdict tests are in the "evidence grading (A-87)" section of `tests/test_mcopilot.py`.
>
> `mcopilot all` produces **both** servo reports: `out/servo_sample.md` (fixture · self-consistency) and
> `out/export10.md` (real machine record · external evidence) — shipping only the fixture means shipping only "I graded my own homework".

What it does:

- Marks overshoot, peak time, settling time, ringing frequency (zero-crossing method) and non-convergence of the tail.
- **Least-squares fit of equivalent second-order parameters** (ωn/ζ), cross-checked against the overshoot method: a large discrepancy between the two is itself a conclusion (the response is not a single second order).
- **type-1 / type-2 discrimination**: the correlation between error and velocity **plus** the stability of the error/velocity ratio.
  A high correlation alone is not enough — under mechanical resonance the error and the velocity oscillate together and the correlation is equally high, but the ratio swings wildly; a true type-1 is `err = k·v` (a constant ratio), in which case `e≈a/ωn²` does not apply and the error does not converge.
- **Measured following error over the constant-acceleration segment vs. `e≈a/ωn²`**: the constant-acceleration segment is located in the waveform first, then compared; when it cannot be found the report says so explicitly rather than passing off the instantaneous step error as steady-state following error.
- Outputs candidate root causes plus "how to verify" for each.

**The output follows the C3 diagnosis contract** (`schema: mcopilot.servo.diagnosis/1`, from axiscope's `docs/contracts/C3-diagnosis.md`).
This is not "printing one more paragraph"; it is **delivering the conditions under which the conclusion holds**:

| Field | What it does |
|---|---|
| `hypotheses[]` | each entry carries `fault_mode` (one of the 22 slugs in KB0 §2), `supporting_evidence` (≥2 items, with criterion id and truth source), `contradicting_evidence` (**mandatory** — an empty array if there is none), `expected_effect.basis`, `next_data_to_collect`, `counterfactual` |
| `differential.not_evaluable` | structurally unevaluable rules go here, **not into hypotheses**; each row carries `blocked_by` / `why` / `unlocks` |
| `audit` | every criterion is exactly one of `rules_fired` / `rules_skipped` (not executed because a precondition was unmet) / `rules_not_hit` (executed, did not fire) — the three are mutually exclusive, nothing is omitted |
| `verdict.overall_confidence` | per KB4 §2.2: `primary-confidence × (1 − 0.05 × min(4, number of de-duplicated independent absence reasons))` |

Three hard rules (each written down only after being bitten):

1. **A criterion's "status" must be explicit.** A criterion that never ran cannot count as "no problem found" — the report says it in two separate sentences: "the criteria that ran did not fire" and "N further criteria were not executed because their preconditions were unmet".
2. **Frequency criteria are judged by "spectral line absolute amplitude ÷ error dynamic scale"**, not by in-band energy share and not by relative prominence.
   When the error itself is small, a ratio turns a negligible spectral line into the protagonist (cross-validation §F-07).
   Likewise, a "dominant frequency" sitting in the **lowest/highest bin** is a resolution-edge residue, not a frequency — the report says so on the spot.
3. **The command refresh rate is a measured signal** (the inverse of the median command-jump interval, not a hard-coded constant).
   A spectral line landing on an integer multiple of the refresh rate is judged **"command-refresh component, not a response of the controlled object"**; it does not enter the conclusion, only `not_evaluable`.
   It is produced by the upper computer refreshing commands at a fixed period — **it is not a spurious line**, and it is not a response of the controlled object.

**Knowledge and code are separated**: the thresholds, the 22 slugs and the criterion formulas all live in `knowledge/servo_rules.json`; `src/mcopilot/agents/servo.py` contains only signal computation and a generic evaluator — **change the config, not the code**.

The tests that guard this layer:

- `tests/test_fault_mode_slugs.py` — the `fault_mode` set must be **exactly equal** to axiscope's KB0 §2 (no invention, no omission);
- `tests/test_crossval_regression.py` — the cross-validation failure points are locked in as regressions (F-01 crash / F-03 bias decomposition / F-07 edge bin / refresh-rate convention);
- `scripts/verify_servo_spectrum.py` — independently recomputes the frequency-domain numbers in the report using the **standard library only** (**never validating reviewed conclusions with the reviewed code** — that is the "same-source self-certification" the axiscope audit calls out).

**Its limits (must be read together with it)**:

1. What it estimates is an **equivalent** second-order parameter (≈ closed-loop bandwidth), **not the mechanical natural frequency**. Judging resonance requires a sweep to confirm.
2. `e ≈ a/ωn²` holds for **type-2 (position loop + velocity feed-forward)** and only describes the **constant-acceleration segment**.
3. **Getting the time-column unit wrong is a 1000× error** (milliseconds read as seconds → ωn off by 1000×, and the report still looks perfectly normal).
   The tool judges by **column name** first (`time_ms` / `t_ms` / `time_us`) and shows its decision in the report; `--time-unit` can also set it explicitly.
4. This tool **does not replace an oscilloscope and the servo manual**. It tells you "what to suspect, what to measure", not "what gain to set".

#### 2.1 v3: torque/current channel (`cur_q`) + event stream (`events.jsonl`) — unlocking 11 criteria

```bat
mcopilot servo diagnose wave.csv --events events.jsonl --accel 1000
```

Two new inputs (both **optional**: without them the 11 new criteria remain "not evaluable", never invented):

- **A `cur_q` torque/current column** (recognised by the names `torque` / `current` / `转矩` / `电流`) —
  unlocks the last four of the mechanical family: breakaway ratio at start (static friction, SRV-15), low-speed stick-slip (crawling, SRV-16), narrow-band torque ripple (SRV-17) and resonance-error pairing (dual inertia, SRV-20).
- **`--events events.jsonl`** (the C6 machine-context format: one event per line, `t` in **waveform timeline** seconds, `source`, `code`, optional `level`/`axis`/`detail`) — unlocks six of the software family:
  host pause → error spike causality (SRV-23), interpolation underrun (SRV-24), bus cycle loss (SRV-25), late vision (SRV-26), premature done judgement (SRV-28) and command polling lag (SRV-29).

**Events have two levels, with different discipline** (this is the C2 causality contract in practice):

1. **Event-side statistics** (count, duration, interval, p95) — evaluable **without** synchronisation:
   SRV-24/25/26/29 look only at the event stream itself;
2. **Causal-level signals** (a pause aligned with an error spike, error not converged at done) — these align events onto the waveform and are
   causal claims, so they are **only computed when event-waveform synchronisation has been verified**:
   `move_started` is paired with command-jump edges and counts as "aligned" only when the median |Δt| ≤ the clock budget (5 ms by default);
   when pairing fails, SRV-23/28 **refuse to answer outright** (`blocked_by=events_sync_unverified`),
   rather than offering a discounted causal conclusion. Refusal ≠ absence: in that state the software family does **not** trigger whole-family absence registration.

The accompanying pitfalls are all filled (each pinned by a test): a command step raises the velocity baseline → cruise segmentation uses p99, not max; differencing a stepped feedback gives a pulse train → derived velocity uses a cross-sample central difference; a global dynamic std drowns the spike in the quiet segment → the spike baseline uses a **local-window maximum**; the done-judgement baseline uses the **self-referenced median of the other dones**; and before a spectral line is given a physical attribution it must pass the **refresh-line gate** (a 47 Hz ripple must not be matched to a 100 Hz refresh line).

**What was not evaluable before v5 (all now have an unlock entry point, see below)**: SRV-18 (drive current-loop parameters), SRV-19 (frequency sweep), SRV-21/22 (temperature channel), SRV-27 (process recipe context).

**v4: the axis nameplate sidecar `--axis axis.json`** (`cpr` / `pole_pairs` / `screw_pitch_mm`) —
with it, the SRV-17 torque-ripple conclusion is promoted from "a narrow-band component exists, at this frequency" to an **order attribution**: "**6× electrical frequency**" (inverter / dead-time signature) or "**k× per revolution**" (mechanical periodicity error)
(landing in `hypotheses[].attribution`; no attribution when the distance to the nearest integer exceeds 0.2).
Without the sidecar the attribution field is absent — absence means "no attribution performed", not a guess dressed up as one.
This sidecar is a C1 sample-package file, **not a C6 contract object** (C6 has no `cpr` field anywhere).

**v5: the last batch of deferred criteria is fully unlocked** —
- **Temperature**: add a `temp` column to the CSV → SRV-21 thermal drift (the slow trend of the error correlates with temperature ≥0.6 and drifts ≥2 µm per K), SRV-22 motor heating (temperature rise ≥0.3 K/min with temperature tracking torque RMS); a cold/hot pairing still needs two waveforms, as the criterion states;
- **Recipe**: a `recipe_change` event in the stream (the C6 contract already defines this feature) → SRV-27 pulse-scale rewrite (the displacement ratio jumps ≥5% at a recipe boundary); without the event it defers to SPC;
- **Drive parameters**: `--drive-params drive_params.json` (`current_loop_bandwidth_hz`) → SRV-18: a torque resonance exceeding the current-loop bandwidth by ≥1× is judged "the current loop cannot hold it"; C6 has no such contract object, so this uses a file entry point with data from the drive manual or the tuning software;
- **Frequency sweep**: no new file — a chirp/sweep in cmd is detected automatically (coherent H1 estimate) → SRV-19: a measured closed-loop bandwidth < 0.5×ωn is judged as PI mistuning.
  **A closed-loop sweep cannot give open-loop phase margin; the conclusion stops at "measured bandwidth + ratio to ωn" and never claims margin**

Of the 29 criteria, 28 are now evaluable (SRV-27 needs the recipe event, otherwise it defers to SPC).

### 3. `forensics` — Device log root-cause analysis + format health check
> Requirements: R-09, Q-09, R-04

```bat
mcopilot forensics analyze device.log --out out
mcopilot forensics probe  device.log --out out
```

**`analyze`**: log timeline reconstruction + defect detection + root-cause candidates ranked with line-numbered evidence.
Defect types detected: positioning deviation, axis parameters overwritten (changeover race), same-axis timing contention, packet loss, arrival-time overrun, calibration residual drift, cycle jitter, timeout clustering, heartbeat loss, and segmented vision defect-rate increases.

**Every conclusion points back to the original log line**, so a human can check and rebut it; root-cause candidates are hypotheses, not conclusions, and each one carries "how to verify".

**`probe` (format health check)**: turns "how tightly coupled is this toolkit to your logs?" into a **quantified number**, reported in two layers:

- **Layer 1, line format** — what percentage of lines the current `line_regex` matches; when it does not, a usable `line_regex` starting point is offered.
- **Layer 2, event regexes** — the status of each event class:
  - `已支持` (the regex matches directly) / `需改正则`、`缺字段` (**these events really are in the log**, the syntax just doesn't match — a config change is enough)
    / `未出现` (**this log has no such instrumentation**, so the matching detector has no data to run on).
- It ends by separating two **qualitatively different** kinds of "cannot run": **blocked by format** (fixable by config) vs. **no instrumentation** (requires changing your logging).

`samples/logs/` ships three logs so the numbers above are recomputable:
`machine_a.log` (the built-in format), `vendor_b.log` (**only the line layout differs, the key names are the same** → adaptation cost 0, one `line_regex` changed) and
`legacy_c.log` (**the key names differ too and a batch of instrumentation is missing** → it points out correspondences like `target→pos` and `speed→spd`, and names the detectors that will go blind).

**`thresholds` (threshold sensitivity and false-positive boundaries)**:

```bat
mcopilot forensics thresholds logs/your-log.log --out out
```

The thresholds in `knowledge/log_rules.json` are a **generic starting point**. The worst thing about on-site calibration is not "the threshold is inaccurate" but **"it flips with a tiny nudge"** — the threshold sits so close to the conclusion-flip point that a different batch of data reverses the conclusion while you assume the data just differs.

This tool scans every threshold on its own and uses **bisection to pin down the "conclusion flip point" exactly** (a coarse grid would show "only 5% away from the flip point" as "stable"). It also catches two kinds of **config-vs-code mismatch**:

- **Dead threshold**: it is configured, but the forensics code **never reads it** (e.g. `concurrent_command_ms`) → calibrating it on site has no effect whatsoever;
- **Hard-coded fallback**: the code reads it as `th.get("x", default)`, but the config has no such entry (e.g. `cycle_slow_ratio`)
  → the code's default is what takes effect, and calibrating it means editing code.

> If these two are not reported, on-site calibration is wasted work — and the person doing it will never notice.

A **detector false-positive boundary table** is attached: for each detector, what input makes it false-positive, what guard the tool already has, and how to review it manually
(in `knowledge/detector_meta.json` — knowledge separated from code). **The tool says "this fired"; it does not say "you should believe it".**

### 4. `spc` — SPC and yield analysis
> Requirements: R-08, R-07, R-05

```bat
mcopilot spc report process.csv --metric place_x_mm --group-by lot --usl 0.02 --lsl -0.02
```

Outputs: I-MR control charts (out-of-control points and the detection rules), Cp/Cpk, a defect Pareto, yield trends, CUSUM change-point detection, and point-biserial correlation between process parameters and defects. **Its biggest value is a single shared definition** — for the same metric, production, R&D and process engineering each compute their own number, and when the numbers don't match the discussion cannot continue.

### 5. `motion` — Offline motion-parameter validation
> Requirements: R-04, Q-05, Q-06a

```bat
mcopilot motion plan --distance 100 --v 200 --a 1000 --j 5000 --freq 50 --damping 0.7 --tol 0.01
mcopilot motion gear --lead 10 --encoder 131072 --ratio 1 --ppr 16384 --configured 1638.4 --travel 200
mcopilot motion compare --distance 500 --v 200 --a 1000 --j 5000 --target 250 --counts-per-mm 13107.2 --exposure-us 50
mcopilot motion vectors --file out/golden_vectors.json    # output path; out/ is a local generation area and is not committed
```

- 7-segment jerk-limited S-curve: segments, total time, peaks, constant-velocity segment, braking distance.
- **Up-front following-error check**: `e ≈ a / ωn²` tells you directly whether this acceleration will eat your positioning tolerance —
  you learn how far to drop the acceleration without trial and error on the machine.
  **Preconditions**: type-2 (position loop + velocity feed-forward); `a` is taken from the constant-acceleration segment (using the peak acceleration only gives a conservative upper bound);
  `ωn` is the natural frequency corresponding to the equivalent closed-loop bandwidth, not the mechanical natural frequency. The report states all three on its face.
- **Electronic gear / pulse-scale self-check**: a 2.3% pulse-scale deviation is a 4.7 mm positioning error over a 200 mm travel.
- **Golden test vectors**: Python computes them once, C# computes them again — a mismatch means the algorithm implementation is wrong.

### 6. `cam` — Electronic cam table feasibility check and generation
> Requirements: Q-05 (electronic cam), R-03 (Leadshine / ZMotion / Googol SDK wrapping)

```bat
mcopilot cam check samples\cam\pick_place_cam.csv --master-v 360 --master-a 200 --slave-v-max 300 --slave-a-max 2000 --slave-travel 120 --master-unit deg
mcopilot cam plan --master-travel 360 --slave-travel 8 --segments 4 --master-v 360 --slave-v-max 300 --slave-a-max 2000
mcopilot cam caps
```

- **Inter-segment velocity step (the source of mechanical shock)**: adjacent segments of a cam table have different slopes, so the slave velocity jumps instantly at the seam.
  The step is `Δv = (kᵢ − kᵢ₋₁)·θ̇` — **the most common fatal flaw in a hand-drawn cam table**;
  it shows up as a "clack" from the machine plus a servo following-error alarm, while the table itself looks perfectly fine.
  The report directly gives "how much master travel the transition segment needs at minimum to absorb this step".
- **Slave peak velocity / acceleration budget**: slope × master velocity = slave peak velocity; slope × master acceleration = slave peak acceleration.
- **Following-error budget**: `e ≈ a/ωn²` (type-2 precondition), so the positioning tolerance is accounted for while the cam table is being designed.
- **Cam table generation**: segmented by a trapezoidal velocity profile with **slave velocity going to zero at every segment seam**, so there is inherently no step between segments.
  After generation it self-checks automatically (master monotonicity, limit overrun, steps, point count).
- **Capability differences across the three vendors (`cam caps`)** — the most counterintuitive and most useful output of this tool:
  **Leadshine can download the whole table from the upper computer (`dmc_cam_table_unit`), ZMotion can only reference a table range on the controller side
  (`ZAux_Direct_Cam` passes only the start and end point), and Googol has no cam table at all** (zero `cam` symbols in the `gts.dll` export table;
  master/slave synchronisation goes through "follower segment + event cross-trigger").
  **So "swapping the card doesn't touch business code" is false for electronic cams** — this item cannot be carried over in a cross-brand migration.

> This agent was added on 2026-10-20: while re-checking the requirements baseline source we found that the original transcription had written "electronic gear" instead of "electronic cam",
> so the coverage audit reported "no coverage gap" while the electronic cam explicitly required by the baseline had no tool at all. **A transcription error contaminates every downstream conclusion.**

### 7. `review` — Real-time motion code rule review
> Requirements: R-10, Q-03, R-11

```bat
mcopilot review ..\MyApp\Source --out out
```

The rule pack (`knowledge/review_rules.json`) covers: blocking waits, empty catch blocks, unbounded loops without timeout,
**a missing pulse-scale conversion (lightweight data-flow check)**, hard-coded IPs, magic numbers, float equality comparison, and nested locks.

The "missing pulse-scale conversion" check is not something a regex can catch — the tool performs a lightweight data-flow pass:
it identifies which identifiers feed millimetre-based business interfaces, which feed pulse-based SDK interfaces, and which have been converted;
a variable that lands in the first two but not in the third is a missing conversion. **This is the most common root cause of "intermittent positioning deviation".**

The rule pack is extensible: one regex is one new rule, so a team can accumulate every trap it has stepped in.

### 8. `requirements` — Industrial requirements baseline and traceability
> Requirements: all

```bat
mcopilot requirements report --out out
```

An item-by-item verdict table + a coverage audit (**does every requirement have a tool behind it, does every tool have a requirement behind it** — this prevents tools that flatter themselves).

**The baseline's source text was transcribed, and transcription is where errors live — one error contaminates a whole chain of conclusions.**
On 2026-10-20 the three source screenshots were re-checked item by item at 2× / 4× zoom, which caught 11 errors in the item bodies, two of them serious:

| Original transcription | Baseline source | Consequence |
|---|---|---|
| Q-05 "electronic **gear**" | Q-05 "electronic **cam**" | the coverage audit reported "no coverage gap", **while the electronic cam explicitly required by the baseline had no tool at all** — the `cam` agent was added |
| R-03 "Googol / JingSai / ZMotion / …" | R-03 "Googol / **Leadshine** / ZMotion / …" | the brand list **lost the vendor we had gone deepest with**, and gained a "JingSai" the baseline never mentioned |

Eight qualifiers that had been dropped were also restored (such as R-11's "patents and software copyrights", Q-07's "at least two of (active / passive alignment)").
**That chain is now closed**: `requirements_map.json`'s `meta.provenance_check` records the verification method and every difference,
and `tests/test_knowledge_truth.py` freezes "what the baseline source says" into assertions — so the next person to change `requirements_map.json` / `cards.json`
gets a red test instead of discovering several rounds later that the coverage audit has been lying.

The coverage audit now distinguishes two cases explicitly: **"every requirement with AI share > 0 and no registered gap has a corresponding tool"**
(truly passed) versus **"registered known gaps"** (R-11's patents / software copyrights — there is an AI-shareable part, but no tool backs it today,
so it is registered honestly as a phase-3 candidate instead of pretending there is "no gap").

---

## 4. Plugging into MCP: getting the tools into the AI the engineers already use

The CLI is for running things by hand; MCP puts the tools directly into your IDE or desktop agent —
an engineer asks "why does this log keep showing a positioning offset", the agent calls the forensics tool,
and nobody has to copy-paste a log and run a script by hand.

```json
{
  "mcpServers": {
    "mcopilot": {
      "command": "python",
      "args": ["-m", "mcopilot.mcp_server"],
      "env": { "PYTHONPATH": "C:/path/to/mcopilot/src" }
    }
  }
}
```

It exposes 14 tools: `requirements_map`, `motion_plan`, `motion_gear_check`, `cam_check`, `cam_plan`, `cam_caps`,
`servo_diagnose`, `forensics_analyze`, `forensics_probe`, `forensics_thresholds`, `spc_report`,
`review_scan`, `card_capability_matrix`, `adapter_generate`.

---

## 5. Repository layout

```
mcopilot/
├─ src/mcopilot/
│  ├─ cli.py              Command-line entry point
│  ├─ mcp_server.py       MCP stdio server
│  ├─ core/               Report rendering, statistics, charts
│  └─ agents/             Eight agents (ten modules: forensics is split into forensics + threshold_lab + forensics_comm, sharing one detection discipline)
├─ knowledge/             ★ The single source of truth for rules and knowledge
│  ├─ requirements_map.json Industrial requirements capability map (machine-readable)
│  ├─ coverage_ledger.json ★ Three-project coverage ledger (the sole judge of completion: who implements each requirement, at which verification level, with which evidence)
│  ├─ cards.json          Brand capability matrix
│  ├─ cam_rules.json      Electronic cam check criteria + the three vendors' cam capabilities (each pinned to an official binding / header / DLL export table)
│  ├─ sdks/*.json         Vendor API bindings (adding a brand = adding one JSON)
│  ├─ log_format.json     Log format (to switch to your own logs, change only this)
│  ├─ log_rules.json      Event extraction rules, thresholds, detector dependency table
│  ├─ detector_meta.json  Per-detector false-positive sources / built-in guards / how to review manually
│  ├─ servo_rules.json    Servo diagnosis thresholds and criteria
│  ├─ review_rules.json   Code review rule pack
│  ├─ sdks/official_api/  ★ External ground truth exported from official vendor artifacts: official C# bindings + C headers + DLL export tables + manual transcriptions
│  │                        Leadshine: leisai.csv (1466 official C# declarations / 1463 function names) / leisai_cpp.csv (1513 C prototypes incl. return types)
│  │                        leisai_manual_index.csv (169 manual function indices + chapter + page) / leisai_io_bits.csv (64-row table 8.3 bit map)
│  │                        leisai_io_terminals.csv (88-row ACC-X400 terminal table) / leisai_model_kits.csv (10 rows of card↔junction-box pairings)
│  │                        leisai_pdo.csv (23 CiA402 PDO objects, incl. "as the manual states vs. as convention dictates")
│  │                        leisai_dmce_index.csv (201 DMC-E indices) / leisai_emc_index.csv (174 EMC indices, incl. typo verdicts)
│  │                        leisai_dmce_terminals.csv (72-row DMC-E appendix 1 local interface terminal table)
│  │                        Googol: gts.csv (473 official C# bindings) / gts_hdr.csv (535 C prototypes) / gts_structs.csv (30 struct layouts)
│  │                        gts_hdr_macros.csv (200 official macros) / gts_io_terminals.csv (121-row terminal table) + the 5 gts.dll variants in dll_exports.csv
│  │                        plus gts_prototypes.csv (34 manual prototypes with pages) + gts_manual_index.csv (167 instruction indices)
│  │                        binding_returns.csv ★ fourth layer: the vendor's own C# binding return types (3105 entries, incl. Googol's 4 variants)
│  └─ templates/*.cs.tmpl C# templates
├─ samples/               Sample data (with ground truth / injection lists, for self-checks and demos)
│  ├─ logs/               3 log formats + an injected-defect list
│  ├─ process/            Process CSVs
│  │  ├─ servo/              3 **self-made fixture** waveforms + .truth.json (same-source truth, tagged synthetic_fixture)
│  │  │  ├─ twincat_export10.csv  ★ **A real machine record** (Beckhoff TwinCAT export, tagged real_record)
│  │  │  └─ twincat_export10.truth.json  Independent baseline (vendor metadata + a recomputation not done by this tool)
│  ├─ cam/                Hand-drawn cam table samples (a velocity step is left in on purpose, for self-checking)
│  └─ code/               C# sources to be reviewed
├─ tests/                 Regression tests (398)
│  ├─ test_mcopilot.py       Per-agent regressions + C3 contract regressions
│  ├─ test_binding_truth.py  The fourth truth layer (return types / variant conventions) stays intact
│  ├─ test_chart_guards.py   Chart length guards (fail explicitly, never truncate silently)
│  ├─ test_fault_mode_slugs.py The fault_mode set == the 22 slugs of KB0 §2 (exact equality)
│  ├─ test_cam_truth.py      Cam vendor facts agree with the official ground truth (name sets compared exactly)
│  ├─ test_crossval_regression.py Cross-validation failure points locked in as regressions
│  └─ test_trae_truth_bridge.py The truth bridge stands watch permanently (Trae KB citations + P/Invoke 58/58)
├─ scripts/
│  ├─ compile_check.ps1    Compile self-check (compile the adapters + contract tests + actually run the simulator self-check)
│  ├─ convert_twincat.py  CODESYS/TwinCAT export → canonical CSV (per-axis waveform ingest)
│  ├─ extract_binding_returns.py ★Extracts return types and variants from the vendor's official C# bindings → binding_returns.csv
│  ├─ verify_trae_pinvoke.py ★P/Invoke checked against official ground truth (PE export table + C# binding + C header + variant conventions)
│  ├─ verify_crossval_claims.py ★Independently recomputes the data claims of the cross-validation report (standard library only)
│  ├─ verify_servo_spectrum.py ★Independently recomputes the frequency-domain numbers in the servo report (standard library only)
│  ├─ verify_doc_refs.py   ★Checks that the ground-truth line references in the docs still resolve
│  ├─ verify_traekb_citations.py ★Truth bridge: machine-checks the line references in the Trae generator's knowledge base
│  ├─ verify_bilingual_parity.py ★Bilingual sync gate: do the two READMEs correspond one-to-one in structure, commands, paths and identifiers?
│  ├─ check_cam_capability.py The three vendors' electronic cam capabilities (computed from official ground truth, not remembered)
│  └─ xunit_shim.cs       A minimal xUnit stand-in for compile time only (not part of the deliverable)
└─ docs/
   ├─ 落地路线.md           Phased rollout plan
   ├─ 首次上机验证清单.md   ★ Graded bring-up checklist (direction / units / stop semantics, level by level; L7 electronic cam)
   ├─ 厂商手册索取清单.md   ★ Directly forwardable to sales/FAE (manuals in hand; 4 categories still to confirm: form factor / model / terminals / version)
   ├─ 固高资料索取清单.md   ★ Googol-specific version (with exact file names and directories, ready to send to Googol sales)
   ├─ kb3_判据抽取.md       ★ Extraction record for the servo criteria: 22-slug check, SRV-08…29 criteria and formulas,
   │                        C3 field list, four frequency-domain preconditions, the three-way criterion status, landing list and open trade-offs
   ├─ 交叉验证_Export10.md  ★ Cross-validates the servo branch against real TwinCAT export data (14 failure points)
   ├─ 交叉验证_Export10_数据复算.md ★Independent recomputation and correction of the above (convention and numeric mismatches corrected)
   ├─ 评审_Trae修复.md / 评审_Trae修复_二轮.md ★First/second-round reviews of the P/Invoke fixes
   ├─ requirements_provenance_20261021/ ★ Source corpus and harvesting pipeline for the requirements baseline (cross-check only; it does not define the baseline)
   ├─ wiki/07-运行方式.md  ★ How to actually run this codebase (install / CLI / MCP / gates / five traps)
   └─ 厂商资料留存说明.md   ★Retention policy for vendor documents and the disk-usage record
└─ book/                ★ The ebook "Forensics-First Learning" — a book about method; this repo is its publishing vehicle
   ├─ 前言.md / 尾声.md  Entry point and wrap-up
   ├─ chapters/          Nine chapters + the reading guide (the volume anchored to *this* repo's code)
   ├─ crops/裁剪版.md    Per-chapter "verifiable claim" + "90-minute teaching split" (one file)
   ├─ decision-lists/    Decision lists (all three repos' closing snapshots live here)
   ├─ evidence/          In-repo copies of out-of-repo originals (line-for-line, with provenance)
   ├─ tools/             The book's own self-checks (incl. the anchor gate check_doc_refs_heads.py)
   └─ ASSETS.md          Full asset inventory and reference anchors
```

**Change the config, not the code**: thresholds, log formats, review rules, servo criteria, vendor API bindings and the capability matrix all live under `knowledge/`.

### The ebook ships with the code

`book/` is the ebook *"Forensics-First Learning"* — it is about **how to make every technical claim verifiable by a third party on the spot**.
The book was originally written as three volumes, one per repo; when it ships here it keeps **only the volume whose anchors match this repo's code** —
the criterion is "**which volume's citations can be re-verified against this codebase**", not "which one reads better".
The other two volumes travel with their own repos: `axiscope` and `forensics-code-factory` each have their own book, each anchored to its own repo.
Shipping them together means one clone gets you "the book + one runnable case repo".

**The book's coordinates are anchored to this repo itself**: `forensics-mcopilot@285da78`.
They used to be anchored to the pre-release working copy `mcopilot@b53ac62` — a repo that
**does not ship with this one**. A reader would have had no copy of it, so the coordinates
could only ever be checked by the author, which is precisely the thing this book argues against.
The old anchor was not erased, it was **demoted to history**: the stop point `b53ac62` is
still the true fact of that day; only the coordinate blocks now point at the code a reader
can actually obtain.

Every technical claim in the book is anchored to "repository@commit + path + line", and **a citation goes stale — and a stale citation is worse than no citation**,
because the reader assumes the source is still trustworthy. So there is a machine gate for it:
`python book\tools\check_doc_refs_heads.py` checks every documentation reference across the four resolution roots,
reports them in eight categories, and **currently reports zero true broken links** ✓.
(The sibling `axiscope` / `forensics-code-factory` are separate repos and do not ship with this one; while they are absent,
the gate files "found in no repo" paths under **"undecidable without the missing repo"** instead of calling them broken links —
otherwise the very first CI run on a clean checkout would be red. Of the eight categories, only "true broken link" fails the build.)
Details in [`book/README.md`](book/README.md).

### The architectural contract

The directory structure above is **not historical residue — it is a design decision**, and it is pinned by tests
(`tests/test_layout_contract.py`, 10 of them):

| # | Invariant | Architectural reason |
|---|---|---|
| 1 | `src/mcopilot/` holds **code only** — no data, no documents | A packager only ships what is inside the package; the truth base and the book must stay in the repo as **reviewed evidence** |
| 2 | `knowledge/` (the truth base) lives **outside the package** | It is simultaneously runtime data, reviewed evidence (it records vendor originals' sha256), the anchors the book cites — and it points at vendor originals **outside** the repo; putting it in the package demotes it to "ordinary packaged data" |
| 3 | The repository root is resolved **without hard-coded level counts** | Hard-coding `parents[1]` silently points at the wrong place when the layout changes or the tool is installed as a wheel (it once pointed the root at `site-packages`) |
| 4 | `import mcopilot` **must fail** when run directly from the repository root | Otherwise you may be running an *installed stale copy* rather than the one you think you are — this is exactly what the src layout buys you |
| 5 | When the truth base is missing, the error must be **actionable** | The unit of distribution is the repository, not a wheel; the first thing a user asks is "so how do I run it" |
| 6 | The declared **Python floor must actually hold** | `requires-python = ">=3.9"` is a promise to the outside; syntax like `X \| Y` (PEP 604) only exists from 3.10, and one missing `from __future__ import annotations` turns it into an **import-time crash** on 3.9 — this repo had exactly one such miss, and it is now fixed and pinned |

**The unit of distribution is the repository, not a wheel.** The truth base and the code live in one repo and evidence each other,
and it points at vendor originals outside the repo — none of which fits into a wheel. So the supported forms are a
**source checkout** or **`pip install -e .` (editable install)**. A wheel built by `pip install .` carries no truth base:
that is by design, and the command reports it together with three ways to fix it.

```bat
pip install -e .                    REM the supported install form (editable)
mcopilot all --out out              REM works straight after installing
```

---

## 6. Development and self-checks

```bat
python -m pytest tests -q                          REM 398 regression tests
pwsh -File scripts\compile_check.ps1                REM compile + contract tests + actually run the simulator self-check
python -m mcopilot all --out out                    REM end-to-end
python scripts\verify_crossval_claims.py            REM independently recompute the data claims of the cross-validation
python scripts\verify_servo_spectrum.py             REM independently recompute the frequency-domain numbers in the servo report
python scripts\verify_doc_refs.py                   REM check the ground-truth line references in the docs
python scripts\verify_trae_pinvoke.py               REM check P/Invoke against official ground truth
python scripts\verify_traekb_citations.py           REM truth bridge: line references in the Trae generator's knowledge base
python scripts\verify_bilingual_parity.py          REM bilingual sync gate: do the two READMEs correspond one-to-one?
```

> The last five `verify_*.py` scripts are **reviewers of the tools**: they use only the standard library and do not import mcopilot's business functions —
> validating reviewed conclusions with the reviewed code is exactly the "same-source self-certification" the axiscope audit calls out.
> Each exits non-zero on failure, so they can go straight into CI.

**The truth bridge** (`verify_traekb_citations.py`) solves a subtler problem:
the Trae code factory's knowledge base `gen/adapters_kb.js` **hand-copies** the official ground truth —
the line numbers in `chk: '官方原型 GT_Open(...)（gts.csv:326 / gts_hdr.csv:398）'` are prose only; the generator never reads the truth CSVs.
When the ground truth changes, the citation quietly goes stale, and **a stale citation is worse than no citation**
(the reader assumes the source is still trustworthy). This script turns every `file:line` citation into an executable assertion:
that line must **actually contain the symbol it claims**. It has already caught one real problem —
the Googol homing mode list contained only 4 entries and hid `HOME_MODE_LIMIT_HOME(11)`,
`HOME_MODE_LIMIT_INDEX(12)`, `HOME_MODE_LIMIT_HOME_INDEX(13)`,
`HOME_MODE_FORCED_HOME(40)` and `HOME_MODE_FORCED_HOME_INDEX(41)`
(the last two were also outside the original citation range 163-169); it is now the complete 9-mode table at 163-171.
`tests/test_trae_truth_bridge.py` keeps this bridge permanently on watch.

`compile_check.ps1` does three things and **exits 1 if any of them fails**:

1. Compile the adapters (interface + simulator + Leadshine + ZMotion + **Googol**) → `Motion.dll`;
2. Compile the contract tests (with the `scripts/xunit_shim.cs` minimal stand-in — syntax only, since the physical assertions need a card inserted);
3. **Compile and run** `MotionSelfCheck.cs`: verify that the simulator really produces a following error, that commands and feedback share the same convention, and that the error path really throws.

> Step 3 was added this round. It caught two real bugs on the spot: in the short-travel (triangular) case the velocity was not clamped, so the feedback computed as 0,
> and `AdvanceUntilDone` never marked the axis as complete. **Compiling without running catches neither.**

> ⚠ All C# sources are written **UTF-8 with BOM**: csc / MSBuild read BOM-less source files using the system ANSI code page (GBK on Chinese Windows),
> so Chinese comments and strings get decoded into garbage, which shows up as a pile of incomprehensible syntax errors. The generator enforces this, and the compile script adds `/codepage:65001`.

---

## 7. The limits of this toolkit (please read this)

1. **It will not tune your servo for you.** Inertia identification, gain tuning and resonance avoidance require the machine and an oscilloscope.
   What it can do is **offline waveform diagnosis** (read the waveform → back out equivalent parameters → candidate root causes) and a pre-tuning budget check.
2. **What it estimates is an equivalent parameter, not a physical truth** — but it is worth being precise about which item that applies to:
   - **Following error is measured, not estimated.** On an axis with an encoder it comes straight from encoder counts /
     drive `0x6064` (ZMotion MPOS, Leadshine's independent `dmc_get_encoder` counting channel).
     The real risk is not "estimated inaccurately" but "**the axis has no feedback channel at all**" —
     and the tool does not guess that: the adapter declares it honestly via `HasRealFeedback(axis)` and contract tests branch on it (see item 9).
   - **What is estimated is the servo's equivalent second-order parameter (ωn/ζ)** ≈ closed-loop bandwidth, **not the mechanical natural frequency**.
     Under high-order response the deviation from the true −3 dB bandwidth has been measured at tens of percent, so judging resonance requires a sweep.
3. **`e ≈ a/ωn²` has preconditions.** Type-2 plus a constant-acceleration segment. When they do not hold, the report says so,
   and the tool never passes off the instantaneous step error as steady-state following error.
4. **It does not guess vendor behaviour — and now there is external ground truth to back that up.**
   - Every capability-matrix entry carries a `verified` level: `official-manual` / `official-binding` (official C# binding) /
     `public-doc` (public material) / `needs-manual-check` (only the vendor can supply it).
   - **Every P/Invoke of Leadshine/ZMotion is checked line by line against the official C# bindings** (function name / DLL name / parameter count), with regression tests always on;
     **Leadshine is pinned two layers deeper**: against the prototypes in the official C header `LTDMC.h` (**including return types** —
     15 `long`, 11 `DWORD`, 2 `double`, not `short`; writing the wrong one reads the return value at the wrong width),
     and against the **169 entries of the manual's appendix 11, "Motion Control Function Index"** (function name → chapter → page).
     The full error-code table, the full stop-reason table, homing modes 0~12, `dmc_vmove` direction, arc parameter order and the SDO entry points all come from the official manual text.
   - **Googol is now also at "official-binding grade"** (the official SDK package arrived on 2026-10-20): all 34 P/Invoke were checked against the official `gts.cs`
     (function name / parameter count / parameter types / ref-out modifiers), against the C prototypes in the official `gts.h`,
     and against the **field order and byte offsets** of 3 structs (`gts_structs.csv`) and the enum values of 200 official macros
     (`gts_hdr_macros.csv`); the calling convention comes from `gts.h`'s `#define GT_API extern "C" short __stdcall`.
     Two manual-grade truths remain (`gts_manual_index.csv` with 167 instruction indices + `gts_prototypes.csv` with 34 prototypes and pages),
     and they are now the **fourth** line of defence: a function name must be in the official binding *and* in the manual index.
     Googol has **no** `SetPulsePerMm` (the scale is a fractional ratio in `GT_ProfileScale` and the formula is unpublished) → the adapter **does not push** a scale transform,
     and requires the controller to stay at the default 1:1 scale, with the pulse scale supplied on site and converted on the software side.
     Googol also has **no vendor stop-reason codes** → the adapter's stop reason is **a custom encoding this tool derives from the status-word bits**, and it is documented as such.
   - **One more layer: the DLL export table** (`knowledge/sdks/official_api/dll_exports.csv`): a function that the official C# binding **declares**,
     that the official C header **also declares**, but that the shipped DLL does **not export**, blows up with `EntryPointNotFound` just the same.
     Two real hits: `ZAux_Direct_GetNtype` (in the official `Zmcaux.cs`, in `zmcauxdll2.h`, **absent from the export table of the 64-bit `zmcauxdll.dll`**) and
     `GT_GantryHoming` (in the official Googol `gts.cs`, **absent from all 4 `gts.dll` export tables**).
     The export sets of the 32- and 64-bit Leadshine `LTDMC.dll` **are not identical** (the 32-bit build is missing 8 functions) — and the target process bitness is not yet decided,
     so the regression tests require that **whatever bitness you have on hand must be able to export it**.
     Googol adds one more layer: the SDK package contains **5 same-named `gts.dll`** (the 4 SDK copies have identical export tables, 782 symbols each;
     the old one in `03_Demo工具_MCT2008/` has only 569, **214 fewer**) → copying the wrong one does not crash immediately but loses a whole set of features,
     so the regression tests distinguish them by a "variant" column, and the notes state to copy only the `02_CSharp封装/<bits>_single_card/` one.
   - **So "please re-check against your model's function manual" now applies only to the items that are determined per batch/model**:
     the actual card model and its junction box, the IO terminal table, the CMP channel↔terminal mapping, bus-slave PDO mapping, and SDK version↔firmware.
     These are listed in a **directly forwardable** checklist (`docs/厂商手册索取清单.md`); until there is an answer the code **throws explicitly**, and no "looks like it works" implementation is offered.
5. **It only does offline analysis.** No tool connects to a real machine or issues motion commands; real-machine verification is done by humans.
6. **Root-cause candidates are hypotheses.** Each carries "how to verify"; when one is disproved, move to the next — never use it directly as a conclusion.
7. **The samples and the rules share a source, and this is not glossed over.** The sample logs are generated by `make_samples.py` under the same conventions,
   so "all samples detected" **only proves the detection logic is self-consistent; it does not prove it works on your logs**.
   `forensics probe` exists to quantify the latter.
8. **Thresholds must be tuned on your line — but separate "depends on real data" from "does not depend on real data".**
   - **Independent of real data, already pinned**: vendor semantics (error codes / stop reasons / direction encoding / unit conventions / homing modes) come from official manuals and official bindings.
     **Dependent on real data**: numeric thresholds (how much following error counts as abnormal, how much cycle jitter counts as abnormal, packet-loss rate) and the mapping to your log's key names.
   - **Two more steps are possible without a machine**: ① turn fixed thresholds into relative criteria ("baseline + MAD"), which is more robust across lines;
     ② run a **sensitivity analysis** on every threshold, marking the "conclusion flip interval" so that brittle thresholds get calibrated first.
   - **Step ② is already done**: `mcopilot forensics thresholds` pins down each threshold's "conclusion flip point" exactly by bisection,
     marking **which are brittle** (close to the flip point, calibrate first), **which are too strict** (the current value never fires → the detector is mute,
     not "no problem"), and **which configurations never take effect at all** (dead thresholds / hard-coded fallbacks — tuning them changes nothing).
     A coarse grid lies — it would show "only 5% away from the flip point" as "stable", so bisection is mandatory.
   - **The rest genuinely requires real data**: the baseline for a relative criterion must come from your normal-segment distribution, and the final number from your failure distribution.
     **This tool cannot produce those, and should not guess.**
9. **The simulator self-check proves self-consistency, not real-machine correctness.** A green `MotionSelfCheck.cs` shows "the simulator and the contract assertions agree on the convention";
   it does not show "your card behaves the same once inserted". Real-machine consistency is verified by `MotionContractTests` with a card inserted,
   two of which exist specifically to catch "it seems to run but actually goes wrong": **following error must be non-zero** (catches fake feedback positions),
   **and jog direction must match the velocity sign** (catches inverted direction encoding — Leadshine 0/1 and ZMotion −1/1 are both easy to copy backwards,
   and copying them backwards raises no error, the axis simply runs the wrong way).
   ⚠ Both check `HasRealFeedback(axis)` first: **on an open-loop axis the following error is necessarily always 0** (on ZMotion ATYPE=1/7 the MPOS is only
   a copy of DPOS; on Leadshine without an encoder `dmc_get_encoder` is always 0) — that is not fake feedback, it is the absence of a feedback channel.
   The adapter must declare it honestly, otherwise the only thing the machine produces is a false alarm.
   Vendor semantics (direction / stop mode / IO level) and physical wiring (bit numbers / terminals) **cannot be covered by simulation** —
   that part goes through the graded bring-up in `docs/首次上机验证清单.md` and the vendor confirmations in `docs/厂商手册索取清单.md`.
10. **The capability matrix does not pretend to cover everything.** The requirements baseline covers 6 brands, of which **3 have official first-hand material to check against** (Leadshine / ZMotion / Googol);
    the other 3 are listed as "brands still to be entered", each for a different reason (not laziness — it is decided by whether the first-hand material is obtainable):
    - **ACS**: a different form factor (SA/SA-LT are standalone units, **with no card driver to P/Invoke**), so the "communication-library branch" architecture route has to be settled first.
    - **Softwin / GaoChuan**: not even enough public first-hand material exists; anything built for them would be guesswork.
    - **Correction (2026-10-20)**: "JingSai" **is not in the baseline's brand list at all** — after re-checking the baseline source it is confirmed that
      R-03 reads "Googol, **Leadshine**, ZMotion, Softwin, GaoChuan, ACS"; an earlier transcription misread "Leadshine" as "JingSai",
      which meant **the vendor we had gone deepest with was the one excluded from the brand list**.
      Now `cards.json`'s `brands_in_scope` = Googol / Leadshine / ZMotion / Softwin / GaoChuan / ACS,
      and "JingSai" is moved into `out_of_scope_brands` with a note on why it is not worth investing in — not silently deleted, but accounted for.
    - **Googol is in the matrix, at official-binding grade**: the official SDK package (`gts.h` + `gts.cs` + 4 `gts.dll` + 14 manuals) is in hand,
      all 34 bindings were checked against the official C# binding and the C header, and all three truth layers (binding / header / DLL export table) are green,
      with `verified` raised from `needs-manual-check` to `official-binding`.
      Only three items still need the vendor: the **scale-transform formula** (the manual gives only a range and `|alpha|>|beta|`, not the formula or its direction),
      the **actual model and firmware version on site** (PG = pulse output / PV = analogue or pulse output, with a separate GT2-400-ACC2-VB-G/-V terminal board),
      and **the GEN SDK package** (not a single `GTN_` symbol is in the GTS package).
      One more fact established along the way: **Googol has at least two product lines, with separate SDK packages** — GTS uses the `GT_` prefix (PCIe card),
      GEN uses the `GTN_` prefix and **its first parameter is the controller number** (the two families' signatures are not interchangeable);
      the official GTS SDK package contains **not a single `GTN_` symbol** (all 535 declarations in `gts.h`, all 473 declarations in `gts.cs` and the export tables of all 5 DLLs were checked),
      and GEN is an independent product line (with its own user manual and basic function manual) whose samples' `#include "gts.h"` is merely a file with the same name.
      → **Supporting GEN requires asking for the GEN SDK package separately.** The lesson stands: **never conclude from a prefix** (Leadshine's `nmc_`/`dmc_` are the same library with different prefixes).
    **The byte-level PDO mapping still needs vendor confirmation** (the full error-code table and the full stop-reason table are already pinned by the manuals and no longer need asking);
    **the IO terminal tables of both Googol and Leadshine are now transcribed from the official user manuals** (Googol 121 rows in `gts_io_terminals.csv`,
    Leadshine 88 rows in `leisai_io_terminals.csv` + the table 8.3 bit map + the §1.4 pairing table + **the 72 rows of
    `leisai_dmce_terminals.csv` from bus card DMC-E appendix 1**), so they no longer need asking either.
11. **The product form factor decides the implementation route — ask about the form factor before adding a new brand.** A plug-in card = board driver P/Invoke (Leadshine `LTDMC.dll`, Googol `gts.dll`);
    a standalone unit = **no card driver to P/Invoke**, so the host side goes through the vendor's communication library (ACS SA/SA-LT are ACSPL+ commands + SPiiPlus .NET, over TCP/IP or serial).
    Building it with the "bind the DLL's exported symbols" model simply **cannot connect** to a standalone unit.
    Leadshine's internal split is "card (DMC / DMC-E plug-in) / controller (EMC / MC / PAC standalone)",
    and **DMC-E and DMC share the same header and the same DLL** (measured from the official bindings: 1252 `dmc_` + 214 `nmc_` declarations, 1466 in total / 1463 function names, all in `LTDMC.dll`).

---

## 8. License and third-party material

- This repository's **own code, scripts, knowledge base and documentation** are under the **MIT License** (see [`LICENSE`](LICENSE) ✓, SPDX identifier `MIT` ✓).
  MIT permits use, copying, modification, merging, publication, distribution, sublicensing and sale, but **the copyright notice and the permission notice must be retained**;
  the software is provided **"as is", without warranty of any kind**.
- This repository **also redistributes or references third-party material** (vendor-extracted CSVs, public issue corpora, measured pcap fragments, etc.) ✓,
  and the per-item provenance, licence and obligations are registered in **[`NOTICE.md`](NOTICE.md)** ✓ — that file is the factual source for third-party material;
  this README deliberately does not duplicate it ✓.
- **Protocol specifications and vendor manual originals (7 PDFs) are not in this repository** ✓: following this repo's "external truth anchor" convention they live in
  `<repo root>/../mcopilot-external/vendor_docs/protocol_specs/` ✓,
  and the repo keeps only the **pointer + size + sha256** in `knowledge/protocols/anchors.json` ✓
  (not one fingerprint missing ✓, originals fetched on demand ✓).
  When an original is not in place, the relevant gate records **SKIP and says "not currently machine-verifiable"** ✓
  rather than pretending it was checked ✓.
- ⚠ **MIT contains no patent grant**: before merging this repo into a larger engineering effort, or using it for commercial delivery, confirm the patent boundary yourself.

## 9. Bilingual documentation

| Language | File | Notes |
|---|---|---|
| 中文 | [`README.md`](README.md) | The primary document (this file's Chinese counterpart) |
| English | [`README_EN.md`](README_EN.md) | **Section-by-section synchronised** with the Chinese version |

The two READMEs map **one-to-one** on section numbering, commands, tables and conclusions.
Changing one of them **requires changing the other** — this repo's discipline is "if the definitions differ, there is no discussion to be had",
and documentation is no exception.

That discipline is enforced by a **machine gate, `scripts/verify_bilingual_parity.py`** (standard library only):
it compares the heading levels and counts, the number of code fences, the number of table rows,
**every `mcopilot …` command**, **every file path inside inline code**, and a set of key identifiers
(requirement IDs, knowledge filenames, vendor API symbols) across the two READMEs,
and **exits non-zero** if any of them disagrees — so it can go straight into CI.
The prose may differ; **the structure may not**.
