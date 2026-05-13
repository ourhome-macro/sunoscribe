# SunoScribe 后端音频流水线架构

## 文档目的

本文面向未来维护 SunoScribe 后端音频流水线的工程师与 agent，描述当前后端从上传文件到乐谱导出工件的 typed data lineage、服务边界、阶段契约与落盘路径。

本文只覆盖后端音频流水线。前端当前实现状态见 `../frontend/frontend-current-state.md`。

截至 2026-05-11，代码现状是：`Artifact`、`ScoreRevision`、revision-scoped export、上传即注册 `source_media`、任务编排与受约束 agent workflow 已经有代码实现；前端是 mock 驱动的工作台原型；OSMD、真实前端 API 对接、外部 RVC 调用与完整 score editing UI 尚未完成。

## 核心原则

- 流水线必须沿着 typed artifact 链路推进，不能跳过中间层直接写最终产物。
- `AudioAnalysisService` 当前是编排器（orchestrator），负责串联阶段，不应重新膨胀回“单体全能服务”。
- `MediaIngestService` 必须先产出 canonical WAV（`source.wav`），后续分离与转写阶段都应基于该 canonical 音频，而不是直接消费原始上传文件。
- required stages 不允许 silent fallback。尤其是 vocal separation 与 RMVPE production profile，失败时必须显式失败并留下可追踪诊断。
- `ScoreRevision` 是导出与后续编辑的边界对象；MIDI、MusicXML、view JSON 都应从明确 revision 派生。

## 当前服务拆分与编排关系

当前后端已经从宽泛的 `AudioAnalysisService` 中拆出了更明确的阶段服务：

- `AudioAnalysisService`：编排整体流程、聚合阶段输出、持久化工作区工件、驱动导出。
- `MediaIngestService`：将上传的音频/视频转换为 canonical `source.wav`。
- `StemService`：只消费 canonical WAV，执行 vocal/accompaniment separation，并持久化 `vocals.wav`、`accompaniment.wav` 等 stems。
- `MelodyTranscriptionService`：基于主唱音频运行音高/F0 转写，产出 `F0Track`、`NoteCandidateSet`、原始 pitch 结果与相关中间数据。
- `RhythmQuantizationService`：从转写阶段可用的语义音频结果中提取 `RhythmGrid` 负载。
- `ScoreBuildService`：将转写结果、歌词片段、分析结果构建为 `ScoreIR`/`score_data`。
- `RenderExportService`：从指定 `ScoreRevision` 生成 revision-scoped 的 MIDI、MusicXML、score view 等导出工件。
- `ScoreRevisionService`：创建 machine/user revisions，注册分析 artifacts，应用受控 patch，并触发 revision-scoped core exports。
- `AgentWorkflowService`：只在 `ScoreRevision` 与 typed artifacts 之后工作，提供诊断、patch proposal/apply、export regeneration 与 RVC job spec 准备。

推荐将这些服务理解为“阶段处理器”，而 `AudioAnalysisService` 仅负责：

1. 建立项目工作区；
2. 串联 required/optional stages；
3. 聚合 typed outputs；
4. 调用持久化与导出；
5. 在 required stage 失败时中止流程，而不是伪造成功结果。

## Typed Data Lineage

当前后端目标链路如下：

```text
Upload File
  -> MediaAsset
  -> CanonicalAudio
  -> StemSet
  -> F0Track
  -> NoteCandidateSet
  -> RhythmGrid
  -> ScoreRevision
  -> Export Artifacts
  -> Frontend Render/Edit
  -> CorrectedF0Track
  -> RVC Artifacts
```

当前实现已经覆盖到 `Export Artifacts`，并提供了后续 `Frontend Render/Edit` 与 `CorrectedF0Track`/RVC job spec 的接口雏形；真正的前端 API 对接、OSMD 渲染、外部 RVC 调用和混音产物还没有形成生产闭环。

第一阶段的具体执行步骤见 `../runbooks/lead-vocal-mvp-execution.md`。钢琴弹奏版/伴奏编配不属于本阶段，应按 `../roadmap/post-mvp-development-roadmap.md` 中的 piano arrangement 层单独设计。

### 1. Upload File -> MediaAsset

输入可以是音频或视频文件。上传 API 会先把文件保存到配置的上传后端，并更新 `projects.audio_path`，同时立即注册 `source_media` artifact。后续音频分析任务启动后，项目工作区还会保存一份原始输入副本，作为 `MediaAsset` 的工作区落点。

实际入口：

- audio：`POST /api/upload/audio`
- video：`POST /api/upload/video`
- API 文件：`backend/app/api/upload.py`
- 上传服务：`backend/app/services/upload_service.py`
- artifact 注册：`register_source_media_artifact(...)`

- 工作区副本：`data/projects/<project_id>/input/source.<ext>`
- 责任服务：`backend/app/services/workspace.py`
- 调用入口：`ProjectWorkspace.save_input_copy(...)`

约束：

- 原始上传文件是来源记录，不是后续 MIR 阶段的直接标准输入。
- 后续必须先经过 media ingest，得到 canonical WAV。

### 2. MediaAsset -> CanonicalAudio

`MediaIngestService` 负责把上传文件转换为统一的 canonical 音频格式，目前目标产物是：

- `data/projects/<project_id>/preprocess/source.wav`
- 格式：WAV，44.1 kHz，stereo（由 `CANONICAL_AUDIO_SAMPLE_RATE=44100` 与 `CANONICAL_AUDIO_CHANNELS=2` 控制）

该产物代表 `CanonicalAudio`，是后续分离、转写、节奏分析的统一输入基线。

当前实现事实：

- `AudioAnalysisService.process_audio(...)` 在保存输入副本后，立即调用 `_run_media_ingest_stage(...)`。
- `_run_media_ingest_stage(...)` 调用 `MediaIngestService.ingest(...)`。
- `MediaIngestService` 必须验证源文件存在，并确认真的生成了 canonical WAV，否则直接抛错。

这意味着：

- 上传是“来源记录”；
- `source.wav` 才是后端音频处理的 canonical artifact；
- 任何需要音频内容的下游服务，应优先消费 `CanonicalAudio` 或其派生物，而不是回头读取上传文件。
- canonical WAV 不应为了 RMVPE 提前降到 16 kHz；RMVPE 阶段会在 pitch backend 内部按模型要求重采样。

### 3. CanonicalAudio -> StemSet

`StemService` 的职责是从 canonical WAV 执行主唱/伴奏分离。当前约定上，`StemService` 只消费 `CanonicalAudio`：

- 输入：`data/projects/<project_id>/preprocess/source.wav`
- 主要输出：
  - `data/projects/<project_id>/separation/vocals.wav`
  - `data/projects/<project_id>/separation/accompaniment.wav`
  - 其他可选 stem：`data/projects/<project_id>/separation/<stem_name>.wav`

这一步形成 `StemSet`。

实现边界：

- `StemService.separate(...)` 接收 `canonical_audio_path` 与 `ProjectWorkspace`。
- 分离结果统一复制/归档到 `separation/` 目录，而不是让下游直接依赖第三方分离器的临时输出目录。
- stem 名称会经过 `ProjectWorkspace.normalize_stem_name(...)` 标准化。

工程要求：

- MVP 中 vocal separation 是 required stage。
- 生产环境不允许因为分离器不可用或失败而静默跳过，再继续用混音直接伪装成“成功转写”。
- 如果没有拿到 `vocals.wav`，则不能把后续 F0/score 产物当作有效生产输出。

### 4. StemSet -> F0Track

`MelodyTranscriptionService` 负责主唱旋律转写，核心目标是生成 `F0Track`，并保留 voiced/unvoiced、置信度、原始 pitch 结果等可追踪信息。

推荐的生产输入为：

- 首选：`data/projects/<project_id>/separation/vocals.wav`
- 辅助：`accompaniment.wav` 或其它 stems 作为节奏、调性、和声辅助输入
- 来源记录：保留原始 `source.<ext>` 与 canonical `source.wav` 的引用关系

当前落盘路径：

- `data/projects/<project_id>/pitch/pitch_result.json`
- `data/projects/<project_id>/pitch/f0_track.json`
- `data/projects/<project_id>/pitch/vocal_activity.json`
- `data/projects/<project_id>/pitch/raw_pitch.mid`

语义要求：

- `F0Track` 不是 MIDI，也不是简化后的 note 列表。
- `F0Track` 必须保留时间连续的基频轨迹与可用于诊断的信息。
- 生产 profile 使用 RMVPE；缺失 RMVPE 依赖、模型文件或运行失败时，必须显式失败。
- 不允许在 production required stage 中静默切换到 CREPE、basic-pitch 或其它“凑合能跑”的替代后端。

### 5. F0Track -> NoteCandidateSet

`MelodyTranscriptionService` 在拿到 pitch/F0 结果后，会进一步整理为 note-level 候选集合，即 `NoteCandidateSet`。

当前落盘路径：

- `data/projects/<project_id>/pitch/note_candidates.json`

这里的 `NoteCandidateSet` 应被理解为：

- 基于 F0 与语义音频结果提取出的旋律候选；
- 尚未完成最终节拍对齐与量化；
- 可以保留多种候选、边界不确定性与上游来源信息。

工程约束：

- 不要把 chroma 识别结果当成 note transcription。
- 不要直接把 `NoteCandidateSet` 当作最终 `ScoreRevision`；中间仍需要 `RhythmGrid` 和量化逻辑。

### 6. CanonicalAudio/StemSet -> RhythmGrid

`RhythmQuantizationService` 负责节奏网格相关负载。当前实现从语义音频结果中提取 `rhythm_grid`，落盘为：

- `data/projects/<project_id>/pitch/rhythm_grid.json`

虽然当前实现较轻量，但语义边界必须保持清晰：

- `RhythmGrid` 是独立表示，不是 pitch 检测的副作用。
- 节拍、强拍、量化网格错误会直接污染最终记谱。
- 后续如果改为单独的节奏分析后端，也应继续保持 `RhythmGrid` 作为显式 typed artifact。

输入上推荐使用：

- `CanonicalAudio`；或
- `StemSet` 中的 accompaniment / drums / other 等节奏相关 stems。

### 7. F0Track + NoteCandidateSet + RhythmGrid -> ScoreRevision

`ScoreBuildService` 负责从旋律转写与歌词/分析结果构建 `ScoreIR`，再生成 export-facing 的 `score_data`。在体系设计上，这一步对应“从中间表示走向可版本化乐谱”。

当前阶段涉及的中间与持久化产物包括：

- `data/projects/<project_id>/score/score_ir.json`
- `data/projects/<project_id>/score/score_data.json`
- `data/projects/<project_id>/score/analysis_ir.json`
- 数据库模型：`backend/app/models/score_revision.py`

数据库侧由 `ScoreRevision` 持久化 `score_ir`、派生 `score_data`、`patch_data` 与 revision metadata。`scores.current_revision_id` 指向当前选中 revision；machine revision 与 user/agent patch revision 不能互相覆盖。

`ScoreRevision` 应承担的职责：

- 表示某一次可追踪、可导出的乐谱版本；
- 保留 `score_ir`、`score_data`、`patch_data`、`revision_metadata`；
- 区分 machine revision 与 user revision；
- 为导出工件提供稳定的 revision 边界。

注意：

- `ScoreIR` 是中心表示，不是临时导出细节。
- `ScoreRevision` 不能被“重新跑一次流水线然后覆盖旧结果”的方式替代。
- 下游导出必须绑定到明确 revision，而不是绑定到“项目当前状态”。

### 8. ScoreRevision -> Export Artifacts

`RenderExportService` 从指定 `ScoreRevision` 生成导出工件。当前核心导出类型包括：

- MIDI
- MusicXML
- score view JSON
- summary PDF 仍存在于导出服务中，但 PDF 只是摘要/兼容输出，不等同于正式 score PDF engraving。

当前 revision-scoped 文件落点：

- `data/projects/<project_id>/revisions/<revision_id>/exports/score.mid`
- `data/projects/<project_id>/revisions/<revision_id>/exports/score.musicxml`
- `data/projects/<project_id>/revisions/<revision_id>/exports/score_view.json`

运行期还会在项目工作区保留：

- `data/projects/<project_id>/exports/final_score.mid`

数据库侧由 `Artifact` 记录导出工件元数据，模型位于：

- `backend/app/models/artifact.py`

`Artifact` 应至少保存：

- `artifact_type`
- `status`
- `storage_backend`
- `storage_path`
- `filename`
- `mime_type`
- `checksum`
- `score_revision_id`
- 与任务、项目、score 的关联

实现现状：`RenderExportService.ensure_core_exports(...)` 会为选定 revision 生成 MIDI、MusicXML 与 score view artifacts；`/api/score-revisions/{revision_id}/exports/regenerate` 可重新生成这些 core exports。

MusicXML 生成当前仍是代码内构造的导出逻辑，尚未切换到 `music21` 作为长期 engraving/export 层。后续如果开始做高质量 MusicXML 或 score PDF，应优先引入 `music21`/MuseScore/Verovio 等专门服务，而不是继续扩大手写 XML。

### 9. ScoreRevision -> Agent Workflow / Editing / RVC Prep

受约束 agent workflow 已经有后端入口，但它只应发生在 `ScoreRevision` 和 typed artifacts 之后：

- `POST /api/score-revisions/{revision_id}/agent/diagnose`
- `POST /api/score-revisions/{revision_id}/agent/patch/propose`
- `POST /api/score-revisions/{revision_id}/agent/patch/apply`
- `POST /api/score-revisions/{revision_id}/agent/rvc/prepare`
- `POST /api/score-revisions/{revision_id}/exports/regenerate`

当前实现边界：

- agent context 从 `ScoreRevision`、revision artifacts、`f0_track`、`note_candidates`、`rhythm_grid` 等 typed 数据读取。
- patch proposal 必须经过 validator；apply 会创建新的 user revision，不覆盖 machine revision。
- RVC prepare 当前产出的是 job spec / corrected F0 artifact 相关准备信息，不等同于已经调用外部 RVC 服务并生成 converted vocal/mix。

## 服务职责表

| 服务 | 代码路径 | 主要输入 | 主要输出 | 职责边界 |
| --- | --- | --- | --- | --- |
| `AudioAnalysisService` | `backend/app/services/audio_analysis_service.py` | 上传路径、项目选项、依赖服务 | 阶段聚合结果、工作区工件、导出触发 | 只做 orchestration，不直接承担所有 MIR 算法实现 |
| `MediaIngestService` | `backend/app/services/media_ingest_service.py` | `MediaAsset` 文件 | `CanonicalAudio` (`source.wav`) | 统一媒体格式，确保后续只依赖 canonical WAV |
| `StemService` | `backend/app/services/stem_service.py` | `CanonicalAudio` | `StemSet` | 只负责 stems 分离与归档，不承担转写或量化 |
| `MelodyTranscriptionService` | `backend/app/services/melody_transcription_service.py` | `vocals.wav`、canonical WAV、辅助 stems | `F0Track`、`NoteCandidateSet`、pitch 中间产物 | 负责主唱 F0 与旋律候选，不负责导出最终记谱 |
| `RhythmQuantizationService` | `backend/app/services/rhythm_quantization_service.py` | 语义音频结果 / 节奏相关音频 | `RhythmGrid` | 保持节奏网格为独立 typed artifact |
| `ScoreBuildService` | `backend/app/services/score_build_service.py` | pitch 结果、歌词片段、分析结果 | `ScoreIR`、`score_data` | 负责构建可版本化乐谱表示 |
| `ScoreRevisionService` | `backend/app/services/score_revision_service.py` | analysis result / ScorePatch | `ScoreRevision` + analysis/export artifacts | 持久化 machine/user revisions，禁止覆盖机器转写 |
| `RenderExportService` | `backend/app/services/render_export_service.py` | `ScoreRevision` | MIDI / MusicXML / view JSON 工件 | 导出必须 revision-scoped，不能绕过 revision |
| `AgentWorkflowService` | `backend/app/services/agent_workflow_service.py` | `ScoreRevision` + typed artifacts | diagnosis / validated patch / RVC job spec | agent 只能读 typed data 并通过 validator 修改 revision |
| `ProjectWorkspace` | `backend/app/services/workspace.py` | `project_id` | 各阶段标准路径 | 管理每项目工件路径与目录结构 |

## 标准文件路径约定

以下路径是当前后端工作区的标准落盘约定：

| Artifact / 文件 | 路径模板 | 说明 |
| --- | --- | --- |
| 上传副本 | `data/projects/<project_id>/input/source.<ext>` | 原始 `MediaAsset` 副本 |
| CanonicalAudio | `data/projects/<project_id>/preprocess/source.wav` | 统一后端音频输入 |
| vocals stem | `data/projects/<project_id>/separation/vocals.wav` | 主唱分离结果 |
| accompaniment stem | `data/projects/<project_id>/separation/accompaniment.wav` | 伴奏分离结果 |
| 其它 stems | `data/projects/<project_id>/separation/<stem_name>.wav` | 标准化 stem 名称后落盘 |
| lyrics segments | `data/projects/<project_id>/lyrics/lyrics_segments.json` | 歌词识别片段 |
| whisper raw | `data/projects/<project_id>/lyrics/whisper_raw.json` | 原始歌词识别输出 |
| pitch result | `data/projects/<project_id>/pitch/pitch_result.json` | 转写阶段总结果 |
| F0Track | `data/projects/<project_id>/pitch/f0_track.json` | 基频轨迹 |
| NoteCandidateSet | `data/projects/<project_id>/pitch/note_candidates.json` | 音符候选集 |
| RhythmGrid | `data/projects/<project_id>/pitch/rhythm_grid.json` | 节奏网格 |
| vocal activity | `data/projects/<project_id>/pitch/vocal_activity.json` | voiced/unvoiced 等信息 |
| raw pitch MIDI | `data/projects/<project_id>/pitch/raw_pitch.mid` | 调试/中间导出，不等同最终 revision 导出 |
| ScoreIR | `data/projects/<project_id>/score/score_ir.json` | 中心乐谱语义表示 |
| score_data | `data/projects/<project_id>/score/score_data.json` | 导出/兼容层数据 |
| analysis_ir | `data/projects/<project_id>/score/analysis_ir.json` | 辅助分析结果 |
| revision exports | `data/projects/<project_id>/revisions/<revision_id>/exports/*` | revision-scoped 核心导出 |
| runtime final MIDI | `data/projects/<project_id>/exports/final_score.mid` | 编排流程中的最终 MIDI 落点 |

说明：`runtime final MIDI` 是历史/benchmark 兼容落点；产品下载和前端展示应优先使用 `data/projects/<project_id>/revisions/<revision_id>/exports/*` 下的 revision-scoped artifacts。

## Required Stage 契约与禁止静默降级

这是本流水线最重要的工程纪律之一。

### 1. Media ingest

`MediaIngestService` 是 required stage。

- 如果无法从上传文件生成 canonical `source.wav`，任务必须失败。
- 不允许绕过 canonical 化，直接把上传原文件交给下游分离或 RMVPE。

### 2. Vocal separation

vocal separation 在 MVP 中是 required stage。

- 如果分离器缺失、模型不可用、调用报错或没有产出 `vocals.wav`，任务必须失败。
- 不允许静默改用混音全轨继续主唱转写，并把结果当成正常生产输出。
- debug/开发场景可保留显式标记的诊断行为，但不能伪装成 production success。

### 3. RMVPE production profile

主唱 F0 转写的 production profile 必须基于 RMVPE。

- 如果 RMVPE 模型、依赖或推理不可用，任务必须失败。
- 不允许静默 fallback 到 CREPE、basic-pitch 或任意低质量替代方案。
- 失败时应产生明确错误与可追踪诊断，而不是伪造 `F0Track`/`ScoreRevision`。

### 4. Score build / export

- 如果没有有效 `F0Track`、`NoteCandidateSet`、`RhythmGrid` 或必要的 `ScoreIR` 构建条件，不应生成看似可用的最终乐谱。
- 如果指定 revision 不能导出为 MIDI/MusicXML，导出阶段必须显式报错。
- 不允许以占位 JSON、空白 MIDI、伪造 MusicXML 掩盖上游失败。

当前仍需注意一个实现差距：`AudioAnalysisService._run_export_stage(...)` 写入的 `exports/final_score.mid` 主要用于 runtime/benchmark 兼容；正式产品导出应以 `RenderExportService` 从 `ScoreRevision` 生成的 revision-scoped artifacts 为准。

## `AudioAnalysisService` 的推荐定位

虽然当前实现仍保留一些历史兼容逻辑，但未来维护时应坚持以下边界：

- 它是 orchestrator，不是所有音频/MIR 逻辑的宿主。
- 它应消费阶段服务提供的 typed outputs，而不是直接拼装临时字典替代阶段模型。
- 它可以负责统一 warnings、日志、工作区持久化与导出触发。
- 它不应成为 silent fallback 的集中入口。

一个健康的后端主流程应接近：

```text
save input copy
  -> media ingest
  -> stem separation
  -> melody transcription (RMVPE)
  -> rhythm grid extraction / quantization inputs
  -> score build
  -> create/select ScoreRevision
  -> revision-scoped exports
  -> optional post-revision plugins, e.g. audio_analysis report
```

`audio_analysis` 是当前的可选 post-`ScoreRevision` 插件：它只读取 typed artifacts 与可选歌词，生成 `audio_analysis_report` JSON artifact，用于解释音高、音域、滑音/颤音、节奏和歌词情绪推断。它不属于 required transcription pipeline，不应修改 `ScoreRevision`、不应生成 MIDI/MusicXML，也不应把缺歌词或缺可选证据升级为主流程失败。

## 维护建议

后续工程师或 agent 修改该流水线时，优先检查以下问题：

- 是否仍然沿着 `MediaAsset -> CanonicalAudio -> StemSet -> F0Track -> NoteCandidateSet -> RhythmGrid -> ScoreRevision -> Export Artifacts` 推进。
- 是否让 `StemService` 只消费 canonical WAV，而不是直接读取上传源文件。
- 是否把 required stage 的失败显式暴露出来，而不是追加 warning 后继续“成功完成”。
- 是否把 RMVPE 保持为 production F0 profile，而不是引入未标记的替代后端。
- 是否让导出工件始终绑定到明确 `ScoreRevision`。
- 是否把音频分析、诊断、RVC prepare 等解释/外部工作保持在 post-revision plugin 边界内。
- 是否继续通过 `ProjectWorkspace` 统一路径，而不是让服务各自写随机文件。

## 代码入口索引

为方便后续定位，当前关键文件如下：

- `backend/app/services/audio_analysis_service.py`
- `backend/app/services/media_ingest_service.py`
- `backend/app/services/stem_service.py`
- `backend/app/services/melody_transcription_service.py`
- `backend/app/services/rhythm_quantization_service.py`
- `backend/app/services/score_build_service.py`
- `backend/app/services/render_export_service.py`
- `backend/app/services/score_revision_service.py`
- `backend/app/services/agent_workflow_service.py`
- `backend/app/services/patch_validator.py`
- `backend/app/services/workspace.py`
- `backend/app/models/artifact.py`
- `backend/app/models/score_revision.py`
- `backend/app/api/agents.py`

这些文件共同定义了当前后端音频流水线的主要编排边界、typed artifact 落点与导出契约。
