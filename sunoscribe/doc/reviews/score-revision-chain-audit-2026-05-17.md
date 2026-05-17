# ScoreRevision 全链路与 service 边界审计（2026-05-17）

## 结论先行

当前代码里真正的 `ScoreRevision` 边界只存在于 **API / task 生成路径**，不在 `AudioAnalysisService` 主 pipeline 内部。

也就是说：

- **benchmark 路径** 现在没有经过真实 `ScoreRevision`；
- **生产转谱路径** 是先跑完整 file-backed pipeline，再由 `score_revision_service` 把结果“二次封装”为数据库 `ScoreRevision`；
- `RenderExportService` 已经是 revision-centered，但上游 typed artifacts 仍大面积停留在 **project workspace 单例文件**，不是 **revision-scoped immutable artifacts**。

这导致现在的链路是：

```text
benchmark:
MP4 -> AudioAnalysisService -> workspace files -> final_score.mid

production:
audio/video -> AudioAnalysisService -> workspace files
  -> create_machine_score_revision()
  -> RenderExportService.ensure_core_exports()
  -> revision exports
```

所以项目当前不是“typed artifacts -> ScoreRevision -> export”的闭环，而是“workspace files -> 事后写入 ScoreRevision -> 再导出”的半成品状态。

---

## 1. benchmark / pipeline 实际经过了哪些 revision 边界

### 1.1 benchmark CLI：**没有真实 revision 边界**

`backend/app/scripts/mp4_midi_benchmark.py` 直接调用 `AudioAnalysisService.process_audio(...)`，然后拿 `analysis_result.midi_path` 作为 benchmark 的 `produced.mid` 来源。

关键位置：

- `backend/app/scripts/mp4_midi_benchmark.py` 中 `_run_sample_logged(...)` 直接调用 `AudioAnalysisService.process_audio(...)`
- 返回的 `analysis_result.midi_path` 被复制为 benchmark 输出 `produced.mid`

因此 benchmark 链路实际是：

```text
sample.input_mp4
  -> AudioAnalysisService.process_audio
  -> workspace/input|preprocess|separation|pitch|score|alignment|exports
  -> exports/final_score.mid
  -> benchmark metrics
```

这里 **没有 `Score` 行，没有 `ScoreRevision` 行，也没有 revision-scoped export artifacts**。

### 1.2 AudioAnalysisService 主 pipeline：**只有 file boundary，没有 revision boundary**

`AudioAnalysisService.process_audio(...)` 当前顺序是：

```text
save_input_copy
-> media ingest
-> perception(stage)
-> alignment(stage)
-> _persist_artifacts(workspace)
-> _run_export_stage(workspace final_score.mid)
-> return AudioAnalysisResult
```

它会写：

- `input/source.*`
- `preprocess/source.wav`
- `separation/*.wav`, `stems.json`
- `pitch/*.json`, `raw_pitch.mid`
- `score/score_ir.json`, `score/score_data.json`, `semantic_audio.json`, `analysis_ir.json`
- `alignment/*.json`
- `exports/final_score.mid`

但不会创建数据库 `ScoreRevision`。

### 1.3 生产生成路径：**只有在 score_service / score_revision_service 才进入真实 revision 边界**

真实 machine revision 发生在：

```text
score_service.generate_or_regenerate_score(...)
  -> _run_audio_analysis(project)
  -> score_revision_service.create_machine_score_revision(...)
  -> RenderExportService.ensure_core_exports(...)
```

这才是当前唯一落库的 machine revision 边界。

### 1.4 用户编辑 / agent 编辑：**有真实 child revision 边界**

当前有两条 child revision 路径：

- `score_revision_service.apply_score_patch(...)`
- `agent_workflow_service.apply_patch_to_revision(...)`

这两条都会创建新的 `ScoreRevision(parent_revision_id=...)`，然后重新导出。

### 1.5 当前“revision 边界”总览

#### 实际存在

- machine revision：`create_machine_score_revision(...)`
- user revision：`apply_score_patch(...)`
- agent revision：`apply_patch_to_revision(...)`

#### 实际不存在

- benchmark revision
- AudioAnalysisService 内部 machine revision
- MIR typed artifacts 的 revision-scoped snapshot 边界

---

## 2. 哪些地方仍是 file-backed state，而不是 revision-centered

### 2.1 benchmark 全链路仍是 file-backed

benchmark 只消费这些文件，不消费 `ScoreRevision`：

- `workspace.score_ir_path`
- `workspace.score_data_path`
- `workspace.final_midi_path`
- 各类 pitch / alignment / stem 中间件 JSON/WAV

这意味着 benchmark 衡量的仍是“workspace pipeline 输出”，不是“产品真实 revision 输出”。

### 2.2 AudioAnalysisService 输出仍以 project workspace 单例文件为中心

`ProjectWorkspace` 设计的是 **project 级固定路径**，不是 **revision 级不可变路径**。

比如：

- `pitch/f0_track.json`
- `pitch/note_candidates.json`
- `pitch/quantized_notes.json`
- `score/score_ir.json`
- `alignment/final_alignment.json`

这些路径对同一 project 多次转谱会被覆盖。

### 2.3 create_machine_score_revision 虽然创建了 Artifact 行，但大部分 analysis artifact 仍指向 project 级共享文件

这是当前最严重的问题。

`score_revision_service._register_analysis_artifacts(...)` 会给 revision 挂 Artifact 记录，但它记录的是：

- `workspace.f0_track_path`
- `workspace.note_candidates_path`
- `workspace.rhythm_grid_path`
- `workspace.score_ir_path`
- `workspace.baseline_alignment_path`
- `workspace.final_alignment_path`

这些路径都是 **project 单例文件**，不是 `revision/<revision_id>/...` 下的快照。

结果是：

- `Artifact.score_revision_id` 看起来像 revision-scoped；
- 但 `Artifact.storage_path` 实际可能被后续 rerun 覆盖；
- 历史 revision 的 typed artifacts 不可追溯，不可重放，不可审计。

这本质上仍是 **file-backed mutable state**，不是 **revision-centered immutable artifact**。

### 2.4 AudioAnalysisService 内部还保留了一套未接线的 file-backed pseudo-revision 机制

`score_build_service.py` 里的 `MachineScoreRevisionState` 和 `AudioAnalysisService` 里的：

- `_persist_machine_score_revision(...)`
- `_run_revision_export_stage(...)`

都是 **文件系统版 pseudo revision**。

但它们现在没有接到 `process_audio(...)` 主流程。

这说明代码里同时存在三套概念：

1. workspace 文件态
2. file-backed pseudo revision
3. DB-backed real ScoreRevision

当前真正在线的是 1 + 3，2 基本是死代码。

### 2.5 pipeline 现在有一份 pre-revision MIDI 导出

`AudioAnalysisService._run_export_stage(...)` 直接从 `score_data_dict` 导出 `exports/final_score.mid`。

随后在生产路径中，`RenderExportService.ensure_core_exports(...)` 又会从真实 `ScoreRevision` 再导出一遍 MIDI / MusicXML / score_view。

也就是当前同时存在：

- **pre-revision export**
- **revision-centered export**

benchmark 用前者，产品下载用后者。

这是明显的边界分裂。

### 2.6 Score 顶层仍保留了一份 current snapshot

`Score.score_data` 会被 `_sync_score_from_revision(...)` 覆写成当前 revision 的副本。

这本身不是致命问题，但它意味着：

- `Score` 仍承载了一份“当前快照状态”；
- canonical state 并没有被强约束到“只能读 `ScoreRevision`”。

建议把它明确降级为 projection / cache，而不是产品语义真源。

### 2.7 agent patch 路径与 export contract 还不完全一致

`RenderExportService` 要求：

- `revision.score_data["source_of_truth"] == "score_ir"`
- `revision.score_data["score_ir"] == revision.score_ir`

`score_revision_service.apply_score_patch(...)` 满足这个约束；
但 `agent_workflow_service.apply_patch_to_revision(...)` 当前直接使用 `_build_score_data_from_score_ir(...)` 的结果，没有统一再写 `source_of_truth = "score_ir"`。

这会让“agent child revision”与“render export contract”之间存在隐患。

---

## 3. 现有 service 边界的实际状态

### 3.1 AudioAnalysisService：边界过宽，已经承担了太多职责

它现在同时做了：

- media ingest orchestration
- stem separation orchestration
- melody transcription orchestration
- rhythm grid 组织
- lyrics recognition
- alignment refine
- workspace 文件落盘
- pre-revision MIDI 导出
- 未接线 pseudo-revision 辅助逻辑

这已经不是单一 service，而是“pipeline orchestrator + persistence helper + export helper”的混合体。

### 3.2 ScoreBuildService：build 边界本来清晰，但被 pseudo-revision 混入

`build(...)` 本身边界是对的：  
输入 transcription 结果，输出 `ScoreIR + score_data`。

问题在于它又持有：

- `MachineScoreRevisionState`
- `create_machine_revision_state(...)`

这把“ScoreIR 构建”和“revision identity/persistence”混在了一起。

### 3.3 RenderExportService：当前是最接近目标态的边界

它的核心约束是正确的：

- 输入必须是 `ScoreRevision`
- 导出必须从 revision 的 `score_ir/score_data` 出发
- export artifact 带 revision lineage metadata

这是当前最像目标架构的部分。

但它的上游还没有完全 revision-centered，所以它现在只是“出口是对的，入口还不干净”。

### 3.4 ScoreRevisionService：是真正的 machine revision owner，但 artifact 冻结做得不够

优点：

- 真正创建 DB `ScoreRevision`
- 维护 parent/current revision 关系
- 从 revision 导出 artifacts

问题：

- analysis artifacts 没有 snapshot 到 revision-scoped 路径
- 仍然回指 project workspace 单例文件

所以它解决了“有 revision 行”，但还没解决“typed artifacts 真正挂到 revision 上且不可变”。

---

## 4. 下一阶段把 typed artifacts 真正推进到 ScoreRevision：最小落地顺序

下面给的是**最小且正确**的顺序，不是兜底方案。

### Step 1：先把 analysis artifacts 从“project 单例路径”改成“revision-scoped snapshot”

这是第一优先级，必须先做。

machine revision 创建时，不要把 Artifact 指到：

- `pitch/f0_track.json`
- `pitch/note_candidates.json`
- `score/score_ir.json`
- `alignment/final_alignment.json`

而是统一复制/落盘到：

```text
data/projects/<project_id>/revisions/<revision_id>/analysis/
```

至少先冻结这些 required typed artifacts：

- `canonical_audio`
- `vocals_stem`
- `accompaniment_stem`（若存在）
- `f0_track`
- `pitch_contours`
- `note_candidates`
- `selected_melody`
- `quantized_notes`
- `rhythm_grid`
- `score_ir`
- `score_data`
- `final_alignment`

完成这一步后，artifact row 才真正配得上 `score_revision_id`。

### Step 2：把 machine revision 变成 pipeline 的主输出，而不是事后封装

目标不是让 `AudioAnalysisService` 直接写数据库，而是让 pipeline 的“完成态”从：

```text
AudioAnalysisResult + workspace files + final_score.mid
```

变成：

```text
typed artifact bundle
-> create_machine_score_revision(...)
-> revision artifact snapshot
-> RenderExportService exports
```

也就是：

- pipeline 产物先进入 revision
- export 只从 revision 出
- benchmark / product 都不再把 `workspace.exports/final_score.mid` 当真源

### Step 3：删掉 pre-revision export 作为产品真源

`AudioAnalysisService._run_export_stage(...)` 当前导出的 `exports/final_score.mid` 只能作为 debug convenience，不能再作为主链路输出。

主链路必须统一成：

```text
ScoreRevision -> RenderExportService -> MIDI/MusicXML/score_view
```

benchmark 也必须切到这条线，否则 benchmark 和线上产品不是同一条边界。

### Step 4：benchmark 改为测 revision-centered 输出

benchmark 至少要做到：

- pipeline 先生成 machine revision
- benchmark 的 `produced.mid` 来自该 revision 的导出 artifact
- benchmark 报告记录 `revision_id` 和 artifact ids

否则 benchmark 仍然只是在测“一套旁路文件流”，而不是测产品真实输出。

### Step 5：收敛死代码与重复概念

完成前四步后，应当收掉：

- `MachineScoreRevisionState`
- `_persist_machine_score_revision(...)`
- `_run_revision_export_stage(...)`
- project 级 `score/score_ir.json` 作为历史真源的角色

保留 workspace 可以，但只能作为 runtime cache / debug scratch，不再承担历史语义。

---

## 5. 最终架构建议

目标链路应该收敛成：

```text
Upload/MediaAsset
-> CanonicalAudio Artifact
-> Stem Artifacts
-> F0Track / NoteCandidateSet / RhythmGrid Artifacts
-> ScoreBuildService
-> Machine ScoreRevision
-> Revision-scoped Export Artifacts
-> User / Agent Patch
-> Child ScoreRevision
-> Regenerated Export Artifacts
```

核心要求只有两条：

1. **typed artifacts 必须 revision-scoped 且 immutable**
2. **所有导出必须从 selected ScoreRevision 生成**

只要这两条没有同时成立，就还不是真正的 revision-centered architecture。

---

## 6. 审计判断

### 当前已经对的

- `ScoreRevision` 数据模型基本够用
- `RenderExportService` 的 revision-centered方向是对的
- patch / child revision 机制已经成型

### 当前最核心的缺口

- benchmark 不走真实 revision
- analysis typed artifacts 没有冻结到 revision scope
- pipeline 仍以 workspace files 为真源
- pre-revision export 与 revision export 双轨并存

### 最该优先修的不是导出，而是 artifact freeze

如果不先把 typed artifacts 冻结到 revision-scoped artifact snapshot，  
那 `ScoreRevision` 只是有 `score_ir/score_data` 两块 JSON，整个 MIR lineage 仍然是漂在文件系统里的。

这会直接破坏：

- rerun 可追溯性
- benchmark 可重放性
- agent diagnosis 的 revision 可信度
- RVC 后续对原始 F0 / note candidates 的稳定引用

---

## 7. 相关关键文件

- `backend/app/services/audio_analysis_service.py`
- `backend/app/services/score_build_service.py`
- `backend/app/services/score_revision_service.py`
- `backend/app/services/render_export_service.py`
- `backend/app/services/score_service.py`
- `backend/app/scripts/mp4_midi_benchmark.py`
- `backend/app/services/workspace.py`
- `backend/app/models/score_revision.py`
- `backend/app/models/artifact.py`
- `backend/app/models/score.py`
## 2026-05-17 revision-centered benchmark switch

本轮主线整改不再碰 phrase 逻辑，改为把 benchmark / pipeline 输出切到 revision-centered file-backed machine revision。

### 目标

- 冻结 typed artifacts 到 revision 目录
- 让 benchmark 使用 revision export，而不是 workspace `final_score.mid`
- 保持 `mojito` benchmark success 不回退

### 实施

#### `backend/app/services/audio_analysis_service.py`

- `process_audio(...)` 现在主路径接入：
  - `_persist_machine_score_revision(...)`
  - `_run_revision_export_stage(...)`
- 返回结果新增并填充：
  - `musicxml_path`
  - `score_revision`
  - `artifact_manifest_path`
  - `artifact_manifest`
- `midi_path` 现在优先指向 revision export `score.mid`，仅在 revision export 不可用时才回退到旧 `final_score.mid`

#### `backend/app/scripts/mp4_midi_benchmark.py`

- benchmark 继续消费 `analysis_result.midi_path`，但该字段现在已经是 revision-centered export
- `artifacts.json` 额外写出：
  - `score_revision`
  - `artifact_manifest_path`
  - `artifact_manifest`

### 验证

测试：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m pytest tests\test_audio_analysis_service.py tests\test_mp4_midi_benchmark_cli.py -q
```

结果：`36 passed`

真实样本：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --run-id codex_20260517_mojito_revision_centered
```

结果：`mojito: success`

### 当前状态

- benchmark 已经不再依赖 workspace `exports/final_score.mid` 作为主输出
- 当前仍是 file-backed machine revision，不是 DB `ScoreRevision`
- 但语义边界已经前移到 revision 目录，后续切 DB revision 的成本明显下降

### 下一步

下一阶段应该做：

1. `score_revision_service` 注册 artifact 时不再指向 project 单例文件，而是 revision 冻结副本
2. benchmark diagnostics 显式标注 revision export 路径和 revision id
3. 收敛 `AudioAnalysisService` 里旧 `final_score.mid` 到 debug convenience，而不是主输出
## 2026-05-17 revision frozen artifact registration

本轮继续推进 revision-centered 主线，把 artifact 注册从“指向 project workspace 单例文件”改成“冻结到 revision 目录后再注册”。

### 改动

#### `backend/app/services/score_revision_service.py`

- `_register_analysis_artifacts(...)` 现在会解析 revision 目录：
  - `workspace.revision_dir(str(revision.id))`
- `_record_file_artifact(...)` 新增 `revision_dir` 参数。
- 在注册 Artifact 前，先把源文件复制到：
  - `revisions/<revision_id>/artifacts/<filename>`
- Artifact 的：
  - `storage_path` 指向 revision 冻结副本
  - `artifact_metadata.source_workspace_path` 保留原始 workspace 来源

这样 revision 已经不再引用 project workspace 单例文件作为正式 artifact 存储路径。

### 验证

测试：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m pytest tests\test_typed_artifact_lineage.py tests\test_audio_analysis_service.py tests\test_mp4_midi_benchmark_cli.py -q
```

结果：`37 passed`

真实样本：

```powershell
cd backend
.\.venv310\Scripts\python.exe -m app.scripts.mp4_midi_benchmark run --manifest ..\samples\manifest.v1.json --sample-id mojito --run-id codex_20260517_mojito_revision_frozen_artifacts
```

结果：`mojito: success`

### 当前效果

- benchmark 主输出已是 revision-centered export
- Artifact 注册路径已是 revision 冻结副本
- `source_workspace_path` 仍保留，方便回溯原始 pipeline 文件

### 剩余差距

- 这仍然是 file-backed machine revision，不是 DB `ScoreRevision` 全量主干
- `AudioAnalysisService` 里旧 `final_score.mid` 仍存在，当前只是 fallback / convenience
- benchmark summary 还没有单独高亮 revision export path / revision id

### 下一步建议

1. benchmark summary / artifacts.json 显式提升 revision export 信息
2. `score_revision_service` 的其他 artifact type 也逐步消除对 project 单例文件的依赖
3. 再考虑把 benchmark 直接校验 revision manifest 完整性
