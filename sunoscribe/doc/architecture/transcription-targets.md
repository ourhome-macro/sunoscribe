# SunoScribe 转写目标架构

## 文档目的

本文定义 SunoScribe 从单一 `lead_vocal` MVP 扩展为 `transcription_target` 双模式架构后的后端约束。当前受支持的目标模式固定为：

- `lead_vocal`
- `piano_score`

本文只讨论后端 typed artifacts、流水线共用链路与分叉链路、`ScoreRevision` 版本边界、导出边界，以及 benchmark/reference 隔离原则，不讨论 frontend 改造，也不授权任何代码层面的 silent fallback。

## 核心结论

- `transcription_target` 必须成为项目级或任务级的显式 typed 输入，不能靠文件名、模型名或运行参数猜测。
- `lead_vocal` 与 `piano_score` 共享上传、media ingest、artifact/revision 治理、导出治理与诊断治理，但不共享同一套转写语义。
- `ScoreRevision` 仍然是事实源。任何可编辑乐谱、用户修订、agent patch、导出工件都必须围绕明确的 `ScoreRevision` 建立。
- MIDI、MusicXML、view JSON 只能从 `ScoreRevision` 派生，不能从 F0、临时 MIDI、polyphonic note events、benchmark ground truth 或 debug 中间结果直接注册为正式导出。
- benchmark/reference 必须按 `transcription_target` 严格分离；`lead_vocal` 的样本、参考标注、指标与基线模型不得与 `piano_score` 混用。

## 为什么必须引入 `transcription_target`

单 lead-vocal MVP 的前提是：

- 主要输入语义是主唱旋律；
- 上游关键中间表示是 `F0Track` 与单旋律 `NoteCandidateSet`；
- 下游乐谱目标是可编辑的单声部主旋律谱；
- 后续可基于 `ScoreRevision` 与 `CorrectedF0Track` 驱动外部 RVC workflow。

而 `piano_score` 不是把 lead-vocal 链路“调参数”就能得到的同类问题。它至少带来以下本质变化：

- 目标对象从单旋律转写变成多音同时发声的钢琴记谱；
- 核心中间表示不再是单条 F0 主线，而是多音事件、双手分配、谱表分配、和声密度与节奏分层；
- 量化、分声部、跨谱表、和弦展开、重复音与延音处理都与 lead-vocal 不同；
- benchmark 与 reference 的真值定义也不同，不能共用一个“转写正确率”口径。

因此，系统必须把 `transcription_target` 当成一等架构边界，而不是把 `piano_score` 硬塞进现有 `lead_vocal` 结果结构里凑合复用。

## 目标枚举与语义边界

### `lead_vocal`

适用于：

- 音频或视频中的主唱旋律提取；
- 输出单主旋律 staff score；
- 后续 `CorrectedF0Track` 与外部 RVC workflow。

关键语义：

- 单主线 pitch/F0 是 required signal；
- vocal separation 是 required stage；
- `ScoreIR` 以单旋律、歌词绑定、句法边界与可编辑旋律谱为中心。

### `piano_score`

适用于：

- 独奏钢琴或以钢琴为明确目标乐器的记谱转写；
- 输出钢琴谱而不是主唱谱；
- 关注双手、多声部、和声叠置、踏板与节奏层次。

关键语义：

- 不允许把 chroma 当作最终 note transcription；
- 不允许把单旋律 F0 管线伪装成钢琴谱生成；
- `ScoreIR` 必须能表达多音事件、staff/voice 分配、跨谱表关系与钢琴专属记谱信息。

## 共用链路

双模式共享的是系统治理边界，不是同一套转写中间表示。对两个 target 都成立的共用主链路如下：

```text
Upload File
  -> MediaAsset
  -> CanonicalAudio
  -> transcription_target switch
  -> target-specific analysis artifacts
  -> target-specific ScoreIR
  -> ScoreRevision
  -> Export Artifacts
```

其中真正无条件共享的阶段只有：

| 共享阶段 | 输入 | 输出 | 共享规则 |
| --- | --- | --- | --- |
| Upload | audio/video file | `MediaAsset` | 注册 source artifact，保留 probe 与来源元数据 |
| Media ingest | `MediaAsset` | `CanonicalAudio` | 统一 canonical WAV，作为后续分析标准输入 |
| Task config | project/task config | target-aware task spec | 必须显式携带 `transcription_target` |
| Artifact governance | stage outputs | typed artifacts | 每个 artifact 必须记录 `project_id`、`task_id`、`transcription_target` |
| Score build boundary | target semantics | `ScoreRevision` | 乐谱版本必须可追踪、可修订、不可被导出绕过 |
| Export governance | `ScoreRevision` | MIDI / MusicXML / view JSON | 导出只允许 revision-scoped 派生 |
| Diagnostics | stage outputs | debug artifacts, warnings | debug 可警告，required output 失败必须显式失败 |

必须明确：`StemSet` 不是两个目标都必需的共享 contract。对于 `lead_vocal`，`vocals.wav` 是 required artifact；对于 `piano_score`，是否需要 piano stem、accompaniment stem 或 full-mix analysis，应由钢琴目标自己的 typed contract 定义，而不是借用 lead-vocal 的 stem 语义。

## 分叉链路

`CanonicalAudio` 之后，必须根据 `transcription_target` 进入不同分叉。分叉不是 UI 选项，而是 required artifacts、诊断视图、validator 与 failure mode 的根边界。

### `lead_vocal` 分叉链路

```text
CanonicalAudio
  -> StemSet
  -> F0Track
  -> PitchContourSet
  -> NoteCandidateSet
  -> RhythmGrid
  -> LeadVocal ScoreIR
  -> ScoreRevision(target=lead_vocal)
  -> Export Artifacts
  -> CorrectedF0Track
  -> RVC Artifacts
```

阶段要求：

| 阶段 | 输入 | 输出 | 约束 |
| --- | --- | --- | --- |
| Stem separation | `CanonicalAudio` | `StemSet` | `vocals.wav` 为 required artifact |
| F0 extraction | `vocals.wav` | `F0Track` | 必须保留 voiced/unvoiced、confidence 与连续时间轨迹 |
| Contour assembly | `F0Track` | `PitchContourSet` | 保留旋律轮廓与边界证据，不把 F0 直接当最终乐谱 |
| Note segmentation | `PitchContourSet` | `NoteCandidateSet` | 不能跳过 F0/contour 直接伪造 notes |
| Rhythm analysis | `CanonicalAudio` or accompaniment | `RhythmGrid` | 节奏网格独立建模 |
| Score build | 上述 target artifacts | `ScoreRevision` | 生成单主旋律语义的 `ScoreIR` |

`lead_vocal` 的 required typed artifacts 至少包括：

- `media_asset`
- `canonical_audio`
- `lead_vocal_stem_set`
- `lead_vocal_f0_track`
- `lead_vocal_pitch_contour_set`
- `lead_vocal_note_candidate_set`
- `lead_vocal_rhythm_grid`
- `score_revision`
- revision-scoped `midi`
- revision-scoped `musicxml`
- revision-scoped `view_json`

### `piano_score` 分叉链路

```text
CanonicalAudio
  -> PianoSourceAnalysis
  -> PolyphonicNoteEventSet
  -> PianoRhythmGrid
  -> PianoVoiceSet
  -> PianoVoicingAssignment
  -> Piano ScoreIR
  -> ScoreRevision(target=piano_score)
  -> Export Artifacts
```

阶段要求：

| 阶段 | 输入 | 输出 | 约束 |
| --- | --- | --- | --- |
| Piano source analysis | `CanonicalAudio` | `PianoSourceAnalysis` | 识别钢琴目标可用的时频、onset、offset、能量与事件级分析结果 |
| Multi-pitch / event decoding | target analysis artifacts | `PolyphonicNoteEventSet` | 必须允许多音同时发声，不得退化成单旋律列表 |
| Rhythm analysis | `CanonicalAudio` or target stems | `PianoRhythmGrid` | 为多声部量化服务，不与 lead-vocal 节奏语义混淆 |
| Voice grouping | note events + rhythm | `PianoVoiceSet` | 形成多声部、双手与纹理分组 |
| Staff / hand assignment | voices + rhythm | `PianoVoicingAssignment` | 明确左右手、谱表、声部分配 |
| Score build | 上述 target artifacts | `ScoreRevision` | 生成钢琴语义的 `ScoreIR` |

`piano_score` 的 required typed artifacts 至少包括：

- `media_asset`
- `canonical_audio`
- `piano_score_source_analysis`
- `piano_score_note_event_set`
- `piano_score_rhythm_grid`
- `piano_score_voice_set`
- `piano_score_voicing_assignment`
- `score_revision`
- revision-scoped `midi`
- revision-scoped `musicxml`
- revision-scoped `view_json`

说明：

- 这里故意不把 `F0Track` 设为钢琴目标的核心 required artifact，因为钢琴谱不是单 F0 问题。
- 如果未来某个钢琴分析阶段内部会产出 frame-wise pitch activation，也应以钢琴专属 typed artifact 落地，而不是复用 lead-vocal 的 `F0Track` 语义名称。
- 是否需要 piano stem、pedal inference、专门的 onset/offset backend，可以继续扩展，但必须保持 `piano_score` 自己的 typed contract，不得偷渡为“lead_vocal artifacts + 后处理”。

## Typed Artifacts 规则

### 1. Artifact metadata 必须带 target

从引入双模式开始，所有与转写任务、参考数据、导出相关的 artifact metadata 至少应包含：

- `project_id`
- `task_id`
- `transcription_target`
- `artifact_type`
- `artifact_stage`
- `status`
- `backend` / `model` / `profile`
- `score_revision_id`（如适用）
- `parent_artifact_ids` 或等价 lineage 引用

没有 `transcription_target` 的 artifact，在双模式架构下是不完整的，因为系统无法判断它属于 lead-vocal 还是 piano-score 语义空间。

### 2. Artifact type 必须 target-aware

建议采用“公共骨架 + target 专属类型”的命名方式。

公共 artifact type 示例：

- `source_media`
- `canonical_audio`
- `score_revision_export_midi`
- `score_revision_export_musicxml`
- `score_revision_export_view_json`
- `debug_waveform`
- `debug_spectrogram`

`lead_vocal` 专属 artifact type 示例：

- `lead_vocal_stem_set`
- `lead_vocal_f0_track`
- `lead_vocal_pitch_contour_set`
- `lead_vocal_note_candidate_set`
- `lead_vocal_rhythm_grid`

`piano_score` 专属 artifact type 示例：

- `piano_score_source_analysis`
- `piano_score_note_event_set`
- `piano_score_rhythm_grid`
- `piano_score_voice_set`
- `piano_score_voicing_assignment`

重点不是命名形式本身，而是不能让两个 target 共享一个语义含糊的 artifact type，然后靠业务代码猜测如何解释。

### 3. Debug artifacts 也必须 target-aware

视觉诊断仍然是生产 MIR 的必要条件，但 debug 图不能混淆 target：

- `lead_vocal` 关注 waveform、spectrogram、F0 trajectory、voiced/unvoiced、pitch contour、note candidates、beat/downbeat；
- `piano_score` 关注 waveform、spectrogram、多音事件热图、onset/offset、节拍网格、voice grouping 与 staff assignment 诊断。

debug 失败可以作为 warning，但不能替代 required artifact。required stage 失败时仍必须显式失败。

## `ScoreRevision` 仍是事实源

双模式扩展后，最容易被做坏的地方是：因为 target 不同，就让导出绕过 revision 直接从某种“分析结果”落文件。这是错误的。

必须坚持以下规则：

- `ScoreRevision` 是唯一的乐谱事实源。
- machine revision 与 user revision 仍然必须分离。
- `ScorePatch` 仍然只允许在既有 `ScoreRevision` 上产生新 revision，而不是直接改导出文件。
- `lead_vocal` 与 `piano_score` 可以拥有不同结构的 `ScoreIR` payload，但二者都必须被 `ScoreRevision` 包裹、版本化、验证并审计。

建议 `ScoreRevision` 最低包含以下 target-aware 信息：

- `score_revision_id`
- `project_id`
- `transcription_target`
- `revision_kind`（machine / user / agent）
- `score_ir`
- `score_data`
- `patch_data`
- `source_artifact_refs`
- `revision_metadata`

关键原则只有一个：target 可以改变 `ScoreIR` 的内部语义，但 target 不能取消 `ScoreRevision` 作为版本边界。

## 导出边界：MIDI / MusicXML / view JSON 只能从 `ScoreRevision` 派生

无论目标是 `lead_vocal` 还是 `piano_score`，以下规则必须不变：

- MIDI 只能从指定 `ScoreRevision` 导出；
- MusicXML 只能从指定 `ScoreRevision` 导出；
- view JSON 只能从指定 `ScoreRevision` 导出；
- 导出 artifact 必须记录 `score_revision_id` 与 `transcription_target`；
- 不允许从 `F0Track`、`PolyphonicNoteEventSet`、benchmark reference、第三方临时 MIDI 或 debug MIDI 直接注册为正式导出结果。

正式导出链路必须是：

```text
target-specific typed artifacts
  -> target-specific ScoreIR
  -> ScoreRevision
  -> MIDI / MusicXML / view JSON
```

而不是：

```text
typed artifacts
  -> 临时结果文件
  -> 直接当正式导出
```

## Benchmark / Reference 必须按 target 分离

这是双模式里最容易被忽略、但对生产判断最致命的点。

### 1. Reference 数据不得跨 target 复用

必须区分至少两类 reference 集：

- `lead_vocal` reference sets
- `piano_score` reference sets

二者不能混用的原因：

- 标注对象不同：单旋律 vs 多声部钢琴谱；
- 评价粒度不同：F0/主旋律 note vs 多音事件/双手分配/和声织体；
- 导出期望不同：单 staff lead sheet vs piano grand staff；
- 失败模式不同：octave error 与 vibrato segmentation，不等于钢琴和弦漏检或左右手错配。

因此：

- `lead_vocal` benchmark 不得拿钢琴 reference 充当“通用乐谱真值”；
- `piano_score` benchmark 不得拿 lead-vocal note 序列宣称“钢琴转写可用”；
- 不得把一个 target 的基线结果作为另一个 target 的 fallback output。

### 2. Benchmark artifacts 必须带 target 标签

所有 benchmark / evaluation 相关 artifact、报表、缓存、中间结果至少应带：

- `transcription_target`
- `reference_set_id`
- `metric_profile`
- `backend_profile`
- `run_id`

推荐按 target 物理隔离目录或命名空间，例如：

```text
benchmark/
  lead_vocal/
    references/
    runs/
    reports/
  piano_score/
    references/
    runs/
    reports/
```

重点不是目录样式，而是：

- 不能共享同一个未分 target 的 reference 池；
- 不能输出一个混合两类任务的“综合准确率”来掩盖问题；
- 不能让 benchmark 结果回流覆盖生产 `ScoreRevision`。

### 3. Reference ingestion 必须做 target 适配检查

reference 导入时必须做 target mismatch 检查，至少识别以下可疑情况：

- 试图用 polyphonic piano staff 充当 lead-vocal ground truth；
- 试图用单旋律 vocal melody 充当 piano-score ground truth；
- note density、pitch range、同时发声数或谱表结构与 target 明显不匹配；
- duplicated onset pitches、异常和弦密度或不合理的单声部标注。

### 4. 评价指标必须按 target 定义

本文不规定完整指标公式，但规定边界：

- `lead_vocal` 指标应围绕主旋律 pitch、note segmentation、rhythm alignment、lyric binding、导出可用性；
- `piano_score` 指标应围绕多音事件识别、onset/offset、节奏量化、voice/staff assignment、和弦完整性、导出可用性；
- 不允许用单一 `note accuracy` 同时代表两个 target 的生产质量。

## 失败策略

双模式不会放宽失败要求，反而必须更严格：

- `lead_vocal` required stages 失败时，不能降级成“粗略旋律”继续导出；
- `piano_score` required stages 失败时，不能退化成单旋律或 chord labels 假装完成钢琴谱；
- `piano_score` 缺少 polyphonic transcription backend 时，任务必须显式失败；
- 不允许 silently downgrade `piano_score` 为 `lead_vocal` 输出；
- 不允许 silently upgrade `lead_vocal` 为“钢琴改编输出”；
- optional diagnostics 可以缺失，但必须与正式结果明确分离。

系统始终应优先：

> target-correct failure + traceable diagnostics  
> over  
> target-confused success + unreliable score

## 对后续工作的约束

后续所有涉及转写、revision、导出、benchmark 的设计或实现，都应先回答以下问题：

- 当前任务的 `transcription_target` 是什么？
- 当前阶段产物是否有明确 typed artifact 与 target 语义？
- 该 target 的 required stages 是否完整，失败是否显式？
- 产物是否最终进入了 `ScoreRevision`，而不是直接写导出？
- MIDI、MusicXML、view JSON 是否都从明确 revision 派生？
- reference / benchmark 是否与另一 target 严格隔离？

如果其中任一问题回答不清，这个设计就还没有达到可上生产的标准。
