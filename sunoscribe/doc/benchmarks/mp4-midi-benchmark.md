# MP4->MIDI Benchmark 评测集设计

## 1. 目标与结论

本文定义 SunoScribe 的 `MP4 -> MIDI` 核心评测方案，用于稳定衡量从用户上传的 MP4 到最终导出 MIDI 的生产质量、性能与回归风险。

本评测的核心结论是：

- `MP4 -> MIDI` 主评测应当是**本地 deterministic benchmark**，而不是 LangSmith 主评测。
- LangSmith 仅用于后续 **agent / LLM workflow** 评估，例如 `ScorePatch` 建议、debug diagnosis、失败解释、编辑辅助等，不主导音频 MIR 指标。
- 基准集围绕用户现有 **26 首 MP4 + 对应期望 MIDI** 建立，形成可重复、可版本化、可回归门禁的离线评测体系。

---

## 2. 为什么主评测必须是本地 deterministic benchmark

### 2.1 原因一：核心对象是确定性 MIR 管线，不是开放式 LLM 输出

`MP4 -> MIDI` 的主链路是：

`MP4 -> MediaIngest -> CanonicalAudio -> StemSet -> F0Track -> NoteCandidateSet -> RhythmGrid -> ScoreRevision -> MIDI`

这是一条以音频信号处理、模型推理、规则量化、导出为核心的 **deterministic / near-deterministic MIR pipeline**。主评测需要回答的是：

- 同一个输入 MP4，在相同代码、相同模型、相同配置下，输出 MIDI 是否稳定；
- 音高、起始时刻、时值、八度、切分碎片化是否达到要求；
- 哪个 stage 失败，失败是否可归因；
- 新改动是否导致真实退化。

这类问题更适合本地固定数据、固定依赖、固定配置、固定评测脚本的 benchmark，而不是以 prompt / trace / judge 为中心的 LLM 评测体系。

### 2.2 原因二：MIR 指标需要 sample-level 可复算，而不是主观打分

主评测指标包括：

- onset 偏差
- pitch 命中率
- duration 偏差
- octave error
- fragmentation
- runtime
- stage success rate

这些指标都需要：

- 可复算
- 可对比历史 run
- 可定位到单曲、单 stage、单 note 级别
- 可做 CI / release gate

LangSmith 更擅长：

- 记录 agent trace
- 对 LLM 输出做 rubric 评估
- 比较 prompt / tool 调用效果

但它不适合做音频 MIR 主评测的事实来源（source of truth）。

### 2.3 原因三：音频基准依赖本地工件与运行环境

`MP4 -> MIDI` 评测强依赖：

- 本地 MP4 文件
- 期望 MIDI 文件
- 分离模型 / F0 模型 / 量化参数
- 中间产物与 debug artifact
- 实际运行时长与 stage 错误

这些都更适合保存在仓库外部或大文件存储中，并由本地 benchmark runner 调用。主评测不应依赖在线 trace 平台来承载音频工件与指标归档。

### 2.4 原因四：需要严格遵守“无静默降级”

根据项目约束，若 required stage 失败，必须显式失败，不能用低质量 fallback 掩盖问题。  
因此 benchmark 的首要能力之一是：

- 明确记录哪个 stage 成功/失败；
- 区分“无输出”“错误输出”“低质量输出”；
- 对 required stage failure 直接判为失败。

这类门禁逻辑应在本地 benchmark runner 中固定实现，而不是依赖 LangSmith 中的自由裁量式评估。

---

## 3. 评测范围

本 benchmark 仅评估 **MVP lead-vocal transcription 到 MIDI 导出** 的核心质量，不评估：

- LLM 文案质量
- agent 对用户自然语言的理解质量
- ScorePatch 解释是否“像人”
- debug 建议是否“易读”

主评测覆盖：

1. `MP4` 输入是否被正确 ingest 为 canonical audio；
2. vocals 分离是否成功；
3. F0 与 note segmentation 是否成功；
4. rhythm quantization 是否成功；
5. 最终导出的 MIDI 是否与期望 MIDI 足够接近；
6. 整体 runtime 与 stage runtime 是否可接受；
7. 各类失败是否被正确分类与暴露。

---

## 4. 数据集设计：26 首 MP4 + 期望 MIDI

### 4.1 数据集原则

用户提供的 26 首 `MP4 + 期望 MIDI` 应被视为第一版金标准 benchmark 集。设计原则：

- **固定输入**：每首歌的 MP4 文件内容固定，禁止在 benchmark 中做隐式替换。
- **固定真值**：每首歌对应一个期望 MIDI，作为主对齐目标。
- **固定版本**：manifest 必须记录数据集版本、文件校验和、标注来源、已知问题。
- **可扩展**：后续允许新增曲目，但不得重写已发布 benchmark 的历史结果。
- **可分桶**：按难度、风格、演唱特点分层统计。

### 4.2 建议覆盖的样本难度维度

26 首样本建议在 manifest 中标注以下标签，用于分桶分析：

- `tempo`: 慢速 / 中速 / 快速
- `rhythm_density`: 稀疏 / 中等 / 密集
- `vocal_style`: 平稳 / 强滑音 / 强颤音 / 说唱偏念白
- `register`: 低音区 / 中音区 / 高音区
- `mix_complexity`: 简单伴奏 / 中等 / 稠密伴奏
- `language`: 中文 / 英文 / 其他
- `difficulty`: easy / medium / hard
- `known_risks`: octave_jump、breathy、chorus_bleed、weak_onset 等

这样可以避免只看总平均分，忽略失败集中在某类真实难例上。

---

## 5. 目录结构设计

建议将 benchmark 数据与 run 输出分开管理。

### 5.1 数据集目录

```text
benchmarks/
  mp4_midi/
    README.md
    manifest.v1.json
    cases/
      song001/
        input.mp4
        expected.mid
        metadata.json
      song002/
        input.mp4
        expected.mid
        metadata.json
      ...
      song026/
        input.mp4
        expected.mid
        metadata.json
```

### 5.2 run 输出目录

```text
runs/
  benchmarks/
    mp4_midi/
      2026-05-05T14-30-00Z__git-abc123__manifest-v1/
        run.json
        summary.json
        leaderboard.json
        cases/
          song001/
            produced.mid
            stage_status.json
            metrics.json
            note_alignment.json
            artifacts.json
            logs.txt
          song002/
            ...
```

### 5.3 目录职责

- `manifest.v1.json`：定义 benchmark case 列表与真值元数据。
- `metadata.json`：单曲标签、已知难点、可选 exclusion 说明。
- `run.json`：一次 benchmark 的全局配置、代码版本、模型版本、时间戳。
- `summary.json`：全量汇总指标。
- `leaderboard.json`：便于横向比较不同 run。
- `stage_status.json`：每首歌各 stage 的成功/失败与耗时。
- `note_alignment.json`：预测 note 与真值 note 的匹配结果，便于诊断。

---

## 6. Benchmark Manifest 设计

建议使用单一 manifest 管理 26 首样本，字段保持稳定、可扩展、可审计。

### 6.1 manifest 示例结构

```json
{
  "benchmark_id": "mp4-midi-v1",
  "version": 1,
  "description": "26-song MP4 to MIDI benchmark for lead-vocal transcription",
  "default_eval_config": {
    "onset_tolerance_ms": 80,
    "duration_tolerance_ratio": 0.2,
    "pitch_mode": "midi_note",
    "octave_error_threshold_semitones": 12
  },
  "cases": [
    {
      "case_id": "song001",
      "input_path": "cases/song001/input.mp4",
      "expected_midi_path": "cases/song001/expected.mid",
      "metadata_path": "cases/song001/metadata.json",
      "sha256": {
        "input_mp4": "...",
        "expected_midi": "..."
      },
      "tags": [
        "medium",
        "vibrato",
        "dense_accompaniment",
        "mandarin"
      ],
      "required_stages": [
        "media_ingest",
        "stem_separation",
        "f0_extraction",
        "note_segmentation",
        "rhythm_quantization",
        "midi_export"
      ]
    }
  ]
}
```

### 6.2 case 元数据建议字段

每个 `metadata.json` 建议至少包含：

- `title`
- `artist`（若可记录）
- `duration_sec`
- `difficulty`
- `language`
- `tempo_band`
- `vocal_traits`
- `known_failure_modes`
- `annotation_notes`
- `ground_truth_source`

### 6.3 manifest 设计要求

- **必须记录 checksum**：防止样本文件被静默替换。
- **必须记录 required stages**：便于 stage gate。
- **必须支持 tags**：便于做分桶评测。
- **必须版本化**：`v1`, `v2` 不混用。
- **必须可重放**：同一 manifest + 同一代码版本应可复现结果。

---

## 7. run 输出设计

一次 benchmark run 的输出必须既适合自动汇总，也适合人工排查。

### 7.1 全局 run.json

建议记录：

- `run_id`
- `benchmark_id`
- `manifest_version`
- `git_commit`
- `runner_version`
- `model_versions`
- `started_at`
- `finished_at`
- `host_info`
- `config`
- `aggregate_status`

### 7.2 单曲 stage_status.json

建议按 stage 固定输出：

```json
{
  "case_id": "song001",
  "status": "failed",
  "stages": {
    "media_ingest": { "success": true, "runtime_ms": 1200 },
    "stem_separation": { "success": true, "runtime_ms": 15300 },
    "f0_extraction": {
      "success": false,
      "runtime_ms": 0,
      "error_code": "RMVPE_MODEL_MISSING",
      "error_message": "required model not available"
    },
    "note_segmentation": { "skipped_due_to_upstream_failure": true },
    "rhythm_quantization": { "skipped_due_to_upstream_failure": true },
    "midi_export": { "skipped_due_to_upstream_failure": true }
  }
}
```

### 7.3 单曲 metrics.json

建议包含：

- `matched_note_precision`
- `matched_note_recall`
- `matched_note_f1`
- `onset_mae_ms`
- `onset_p50_ms`
- `onset_p90_ms`
- `pitch_accuracy`
- `pitch_accuracy_matched_only`
- `octave_error_rate`
- `duration_mae_ms`
- `duration_ratio_mae`
- `fragmentation_rate`
- `merge_error_rate`
- `extra_note_rate`
- `missed_note_rate`
- `end_to_end_runtime_ms`
- `stage_runtime_ms`
- `required_stage_success_rate`

### 7.4 单曲 note_alignment.json

用于保存 note matching 结果，建议至少包含：

- 真值 note 列表
- 预测 note 列表
- 匹配对 `(gt_note_id, pred_note_id)`
- 未匹配真值 note
- 未匹配预测 note
- 每个匹配对的 onset / pitch / duration / octave 偏差

这样可以支持后续 debug artifact、失败聚类、可视化分析。

---

## 8. 建议的 note matching 方法

MIDI 评测的核心不是简单比较 note 数量，而是建立**真值 note 与预测 note 的合理匹配**。

### 8.1 基本原则

- 以 **note event** 为比较单位，而不是 frame。
- 匹配必须同时考虑 **onset、pitch、duration**。
- 匹配过程必须 deterministic，不能依赖人工主观判断。
- 一个预测 note 默认只能匹配一个真值 note，避免重复计功。

### 8.2 推荐流程

建议使用以下步骤：

1. 从 `expected.mid` 与 `produced.mid` 中提取单音旋律 note 列表：
   - `pitch_midi`
   - `onset_sec`
   - `duration_sec`
   - `offset_sec`

2. 先按时间窗口建立候选匹配：
   - 仅当 `|pred.onset - gt.onset| <= onset_tolerance` 时才允许进入候选；
   - 默认建议 `onset_tolerance = 80ms`，也可报告 `50/80/120ms` 多档结果。

3. 对候选边赋代价：
   - `onset_cost = abs(delta_onset_ms) / onset_tolerance_ms`
   - `pitch_cost = 0` 若同 MIDI pitch，否则可设：
     - 同八度外但同音级不视为正确；
     - 八度差需要单独记录 penalty；
   - `duration_cost = abs(pred.duration - gt.duration) / max(gt.duration, epsilon)`

4. 使用 **最小代价一对一匹配**：
   - 可用 Hungarian matching；
   - 或按 onset 排序后做受限 bipartite matching；
   - 关键是 deterministic 且实现稳定。

5. 匹配后再计算：
   - 命中 note
   - 漏检 note
   - 多检 note
   - 八度错 note
   - 时值偏差
   - 碎片化 / 合并错误

### 8.3 匹配正确性的判定建议

建议定义多层判定：

- **strict match**：
  - onset 在阈值内；
  - pitch 完全一致；
  - duration 偏差在阈值内。

- **pitch-onset match**：
  - onset 在阈值内；
  - pitch 一致；
  - duration 不要求达标。

- **octave-confused match**：
  - onset 在阈值内；
  - pitch 与真值相差 ±12、±24 半音；
  - 单独计入 octave error，不算正确 pitch。

这样既能给出最终核心分数，也能诊断问题类型。

### 8.4 碎片化与合并错误判定

单纯一对一 note 匹配不足以揭示“把一个长音切成多个短音”或“把多个音合成一个音”的错误。建议额外计算：

- **fragmentation rate**：一个真值 note 对应时间范围内，出现多个预测 note 的比例；
- **merge error rate**：多个真值 note 被单个预测 note 覆盖的比例。

可用基于时间重叠的辅助分析：

- 若多个预测 note 与同一真值 note 大面积重叠，记为 fragmentation；
- 若单个预测 note 与多个连续真值 note 大面积重叠，记为 merge。

---

## 9. 指标设计

## 9.1 核心质量指标

### A. onset 指标

- `onset_mae_ms`
- `onset_median_ms`
- `onset_p90_ms`
- `onset_within_50ms_rate`
- `onset_within_80ms_rate`
- `onset_within_120ms_rate`

用途：衡量节奏起点是否稳定。

### B. pitch 指标

- `pitch_accuracy`
- `pitch_accuracy_matched_only`
- `pitch_f1`
- `semitone_error_mae`

用途：衡量音高是否正确。

### C. duration 指标

- `duration_mae_ms`
- `duration_ratio_mae`
- `duration_within_20pct_rate`

用途：衡量时值是否接近真值。

### D. octave 指标

- `octave_error_rate`
- `octave_error_count`

用途：专门暴露常见的 F0 八度翻转问题。

### E. fragmentation / merge 指标

- `fragmentation_rate`
- `merge_error_rate`
- `extra_note_rate`
- `missed_note_rate`

用途：衡量 note segmentation 是否过碎或过并。

## 9.2 运行与稳定性指标

### F. runtime 指标

- `end_to_end_runtime_ms`
- `runtime_per_audio_second`
- `stage_runtime_ms.{stage_name}`
- `p50/p90 runtime`（跨 case）

用途：衡量生产可用性与回归风险。

### G. stage success 指标

- `required_stage_success_rate`
- `full_pipeline_success_rate`
- `stage_failure_count_by_stage`

用途：防止“分数看似还行，但大量 case 在中途失败”。

## 9.3 汇总口径

建议同时输出三类汇总：

1. **micro average**：按所有 note 汇总；
2. **macro average**：按歌曲先算再平均；
3. **bucket average**：按 `difficulty / vocal_style / language / known_risks` 分桶。

主看板建议优先展示：

- `full_pipeline_success_rate`
- `macro note_f1`
- `macro pitch_accuracy`
- `macro onset_within_80ms_rate`
- `macro duration_within_20pct_rate`
- `macro octave_error_rate`
- `macro fragmentation_rate`
- `p90 runtime_per_audio_second`

---

## 10. 失败分类

Benchmark 不仅要给分，还要可诊断。建议固定失败 taxonomy。

### 10.1 stage failure

- `MEDIA_INGEST_FAILED`
- `CANONICAL_AUDIO_MISSING`
- `VOCAL_SEPARATION_FAILED`
- `VOCALS_WAV_MISSING`
- `F0_EXTRACTION_FAILED`
- `F0_TRACK_EMPTY`
- `NOTE_SEGMENTATION_FAILED`
- `RHYTHM_GRID_FAILED`
- `QUANTIZATION_FAILED`
- `MIDI_EXPORT_FAILED`

### 10.2 quality failure

- `HIGH_ONSET_ERROR`
- `HIGH_PITCH_ERROR`
- `HIGH_OCTAVE_ERROR`
- `HIGH_DURATION_ERROR`
- `HIGH_FRAGMENTATION`
- `HIGH_MERGE_ERROR`
- `TOO_MANY_EXTRA_NOTES`
- `TOO_MANY_MISSED_NOTES`

### 10.3 infrastructure / dependency failure

- `MODEL_MISSING`
- `MODEL_LOAD_ERROR`
- `CUDA_OOM`
- `TIMEOUT`
- `INVALID_INPUT_MEDIA`
- `CORRUPT_EXPECTED_MIDI`

### 10.4 失败分类原则

- **required stage failure 优先**：只要 required stage 挂掉，该 case 直接 fail；
- **质量失败次之**：stage 全成功但分数未达阈值，也应 fail；
- **禁止静默替代**：如 RMVPE 缺失，不允许切到低质量后备模型并继续算主分；
- **必须可统计**：每个失败类型都可跨 run 聚合。

---

## 11. 回归门禁（Regression Gate）

Benchmark 必须直接服务于“能不能合并 / 能不能发布”。

### 11.1 建议门禁层级

#### Level 1：硬门禁

以下任一项不满足则直接阻断：

- `full_pipeline_success_rate` 低于基线；
- 任一 required stage 出现新增系统性失败；
- `MODEL_MISSING` / `MIDI_EXPORT_FAILED` 等基础错误出现；
- 总体运行时间超过上限；
- benchmark runner 本身未完成全部 26 首样本。

#### Level 2：质量门禁

相对基线出现以下退化则阻断：

- `macro matched_note_f1` 下降超过阈值；
- `macro pitch_accuracy` 下降超过阈值；
- `macro onset_within_80ms_rate` 下降超过阈值；
- `macro duration_within_20pct_rate` 下降超过阈值；
- `macro octave_error_rate` 上升超过阈值；
- `macro fragmentation_rate` 上升超过阈值。

建议首版先采用“小而清晰”的阈值，例如：

- 核心准确率类指标下降超过 `1.0 ~ 2.0` 个百分点则 fail；
- 错误率类指标上升超过 `1.0 ~ 2.0` 个百分点则 fail；
- `p90 runtime_per_audio_second` 上升超过 `20%` 则告警，超过 `35%` 则 fail。

#### Level 3：分桶门禁

若总体均值未退化，但某一高风险桶显著变差，也应阻断。例如：

- `vibrato` 桶 octave error 激增；
- `dense_accompaniment` 桶 stage success 显著下滑；
- `hard` 桶 fragmentation 激增。

### 11.2 基线管理

建议每次正式接受的 benchmark run 形成一个 baseline snapshot，包含：

- manifest 版本
- 代码 commit
- 模型版本
- 全局指标
- 每曲指标
- 失败分类汇总

后续 run 必须与**同 manifest、同配置口径**的 baseline 对比，禁止跨口径比较。

---

## 12. 推荐执行流程

### 12.1 benchmark runner 输入

runner 至少应接收：

- `manifest path`
- `output dir`
- `pipeline config`
- `model versions`
- `parallelism`
- `seed`（若存在随机成分）

### 12.2 benchmark runner 行为

对每个 case：

1. 校验 `input.mp4` 与 `expected.mid` checksum；
2. 执行完整 `MP4 -> MIDI` 管线；
3. 保留中间 stage 状态与必要 artifact 元数据；
4. 导出 `produced.mid`；
5. 执行 note matching；
6. 计算单曲 metrics；
7. 记录失败类型；
8. 汇总出全局 summary。

### 12.3 可执行要求

该 benchmark 方案落地时必须满足：

- 同一 case 可单独重跑；
- 单曲失败不影响其他 case 继续执行；
- 输出文件命名稳定；
- 每次 run 都可离线复查；
- 指标计算脚本与 pipeline 执行脚本解耦。

---

## 13. LangSmith 的正确定位

LangSmith 在本项目中是**辅助评测系统**，不是 `MP4 -> MIDI` 主 benchmark 系统。

### 13.1 适合放到 LangSmith 的内容

后续可使用 LangSmith 评估以下 agent / LLM workflow：

- `ScorePatch` 提议质量
- patch explanation 是否清晰
- debug diagnosis 是否正确分类失败原因
- agent 是否正确读取 artifact metadata
- agent 是否遵守“只提 patch、不直接改 ScoreIR”
- 多轮编辑中的工具调用顺序是否合理

这些任务的输出具有：

- 文本性
- 工具链可观测性
- rubric 可判性
- prompt / policy 可迭代性

因此适合放在 LangSmith 中做 trace、judge、对比实验。

### 13.2 不应由 LangSmith 主导的内容

以下内容不应以 LangSmith 作为主评测：

- 音频转 MIDI 的 note-level MIR 指标
- stage success / failure 统计
- runtime / throughput
- 模型缺失、依赖失效、导出失败等工程门禁
- 26 首固定样本的回归比较

这些内容必须由本地 deterministic benchmark 产出并作为发布事实依据。

### 13.3 推荐关系

推荐采用以下职责划分：

```text
local deterministic benchmark
  -> 评估 MP4->MIDI 核心 MIR 质量、stage success、runtime、回归门禁

LangSmith
  -> 评估 agent / LLM 在 ScorePatch、debug diagnosis、workflow orchestration 上的表现
```

---

## 14. 首版落地建议

为了尽快可用，建议首版 benchmark 先做到以下最小闭环：

1. 固定 26 首 `MP4 + expected MIDI`；
2. 建立 `manifest.v1.json`；
3. 输出单曲 `produced.mid / stage_status.json / metrics.json`；
4. 实现 deterministic note matching；
5. 实现核心指标：
   - onset
   - pitch
   - duration
   - octave
   - fragmentation
   - runtime
   - stage success
6. 实现失败 taxonomy；
7. 实现 baseline 对比与 regression gate；
8. 将结果用于本地开发验证与发布前回归检查。

---

## 15. 最终建议

对于 SunoScribe 当前阶段，`MP4 -> MIDI` benchmark 应被视为**音频 MIR 生产评测基础设施**，而不是 LLM 评测问题。

因此推荐：

- 以本地 deterministic benchmark 作为唯一主评测；
- 围绕用户的 26 首 MP4 + 期望 MIDI 建立固定 manifest 与目录结构；
- 以 note matching 和 stage-level trace 为核心产出；
- 用明确的 metrics、失败分类、回归门禁驱动工程决策；
- 将 LangSmith 限定在后续 agent / LLM workflow 评估，不主导音频 MIR 指标。

只有这样，才能同时满足：

- 数据 lineage 清晰；
- required stages 显式失败；
- 输出可追踪；
- 质量退化可被及时阻断；
- 后续 agent 能建立在稳定、可信的 MIR 基座之上。

---

## 16. v1 实际落地入口

当前仓库已经提供第一版本地 deterministic benchmark 基础设施：

- Manifest: `samples/manifest.v1.json`
- CLI: `backend/app/scripts/mp4_midi_benchmark.py`
- Dataset utilities: `backend/app/modules/benchmark/dataset.py`
- MIDI metrics: `backend/app/modules/benchmark/midi_metrics.py`
- Output root: `samples/benchmark_runs/<run_id>/`

### 16.1 只做数据体检

```bash
cd backend
python -m app.scripts.mp4_midi_benchmark validate --manifest ../samples/manifest.v1.json
```

输出：

- `dataset_report.json`
- `summary.json`
- `summary.md`

### 16.2 跑完整 MP4->MIDI benchmark

```bash
cd backend
python -m app.scripts.mp4_midi_benchmark run --manifest ../samples/manifest.v1.json
```

每首歌输出：

- `produced.mid`
- `stage_status.json`
- `metrics.json`
- `artifacts.json`
- `error.json`（仅失败时）

### 16.3 v1 口径

- v1 启用当前可配对的 19 首样本。
- `expected_melody_track` 在 manifest 中手工标注。
- production profile 是默认门禁，不允许 RMVPE 或 required separation 静默 fallback。
- 第一次落地只记录质量指标，不设置硬性 `note_f1` 阈值。

### 16.4 Quality gate and diagnostics update

The v1 benchmark now separates pipeline correctness from output quality:

- Exit `0`: every selected sample is `success`.
- Exit `1`: at least one sample has a pipeline/program failure.
- Exit `2`: the pipeline completed, but at least one sample is `quality_failed`.

Hard quality gate thresholds:

- `first_note_delay_sec <= 15.0`
- `midi_coverage_ratio >= 0.45`
- `note_recall >= 0.05`
- `matched_notes >= 10`

`note_f1`, precision, pitch accuracy, and octave error rate are diagnostic-only in this first version. They are recorded in `metrics.json`, `summary.md`, and `quality_diagnostics.md`, but do not directly fail a sample.

Alignment diagnostics are also diagnostic-only. Each sample records `alignment.best_octave_shift_*`, `alignment.best_time_shift_*`, `alignment.dtw`, median pitch/range deltas, and `alignment.reference_track_suspect_reasons` so low F1 can be separated into transcription quality failure versus likely reference-track octave/time-offset/nonlinear-alignment mismatch before changing the MIR pipeline.

Additional per-song outputs:

- `quality_gate.json`
- `logs/stdout.log`
- `logs/stderr.log`
- `logs/python_logging.log`

Per-run outputs now also include:

- `quality_diagnostics.json`
- `quality_diagnostics.md`

Project workspaces are always retained under `samples/benchmark_runs/<run_id>/projects/<project_id>/` for MIR diagnosis. This keeps canonical audio, separated vocals/accompaniment, F0 tracks, note candidates, rhythm grid, and ScoreIR artifacts available after benchmark completion.
