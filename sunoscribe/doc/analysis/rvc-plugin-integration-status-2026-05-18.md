# RVC 作为插件接入状态评估

日期：2026-05-18

## 结论

当前项目已经有“RVC prepare 插件壳”，但还不能算真正接入 RVC。

准确状态是：

```text
可以作为插件注册一个 rvc_prepare，生成/校验 RvcJobSpec
不能端到端提交外部 RVC job
不能生成 corrected_f0_track
不能持久化 rvc_vocal / rvc_mix 结果
```

所以如果你问“能不能作为插件塞入”：

- 能塞入插件框架。
- 现在只能塞 prepare/spec 阶段。
- 真正 production RVC 插件还差 corrected F0、外部 client、结果 artifact 三段。

## 已有能力

### 1. 插件注册框架已有

`AgentWorkflowService` 已经内置 `PluginRegistry`，默认注册了：

- `diagnosis`
- `audio_analysis`
- `score_patch_agent`
- `rvc_prepare`
- `lyrics_alignment` 占位

关键位置：

- `backend/app/services/agent_workflow_service.py:347`
- `backend/app/services/agent_workflow_service.py:376`

`rvc_prepare` 当前只是调用 `RvcPrepareAgent.prepare(...)`。

### 2. RVC prepare API 已有

API：

```text
POST /{revision_id}/agent/rvc/prepare
```

关键位置：

- `backend/app/api/agents.py:133`
- `backend/app/services/agent_workflow_service.py:300`

输入是 `voice_model_id` 和 `transpose_semitones`，输出 `RvcJobSpecResponse`。

### 3. RVC artifact 类型已预留

`ArtifactType` 里已经有：

- `corrected_f0_track`
- `rvc_vocal`
- `rvc_mix`

关键位置：`backend/app/models/enums.py:60` 到 `backend/app/models/enums.py:62`。

### 4. RVC prepare spec 已定义

`RvcJobSpec` 包含：

- `project_id`
- `revision_id`
- `vocal_stem_artifact_id`
- `accompaniment_artifact_id`
- `corrected_f0_artifact_id`
- `voice_model_id`
- `transpose_semitones`
- `warnings`

关键位置：`backend/app/modules/agents/types.py:206`。

### 5. 基础依赖 artifact 已可注册

机器 revision 会注册：

- `vocals_stem`
- `accompaniment_stem`
- `f0_track`
- `score_ir`
- `note_candidates`
- `rhythm_grid`

关键位置：`backend/app/services/score_revision_service.py:384` 到 `backend/app/services/score_revision_service.py:405`。

这说明 RVC 插件需要的 vocals/accompaniment/score/F0 基础对象大体在库里能拿到。

## 当前阻塞点

### P0：没有 corrected_f0_track 生成服务

`RvcPrepareAgent` 要求 `corrected_f0_track` artifact：

- `backend/app/modules/agents/rvc_prepare_agent.py:20`
- `backend/app/modules/agents/validators.py:391`

但当前没有看到生成 `corrected_f0_track` 的服务。也就是说，现在调用 prepare 大概率会失败：

```text
corrected_f0_artifact_id is required
```

这不是小问题。按项目路线，RVC 不能直接拿原始 F0 或 MIDI 糊上去，应该由 `ScoreRevision + original F0Track` 生成 `CorrectedF0Track`，既修音准又保留自然滑音和 vibrato。

### P0：没有外部 RVC client/job service

当前只有 `prepare_rvc_job`，没有：

- RVC endpoint 配置；
- job submit；
- job status polling；
- converted vocal 下载；
- mix with accompaniment；
- `rvc_vocal` / `rvc_mix` artifact 写库。

因此还不能真正“接入 RVC 服务”。

### P0：plugin 接口还是同步 in-process，不适合长任务执行

`PluginRegistry.run(...)` 是同步调用：`backend/app/services/plugins/registry.py:80`。

RVC 是长任务，正确方式不应该在请求里同步跑。应该是：

```text
plugin.prepare -> 创建 RVC task/job row -> worker 调外部 RVC -> artifact 落库 -> 前端轮询状态
```

当前插件框架适合 deterministic prepare / analysis，不适合直接跑外部推理长任务。

### P1：voice model 只有字符串，没有模型注册表

`voice_model_id` 只是字符串校验：`backend/app/modules/agents/validators.py:384`。

缺少：

- voice model 是否存在；
- 用户是否有权限；
- 模型支持的 pitch extractor / transpose range；
- 模型 endpoint / version / sample rate；
- 模型授权和版权约束。

### P1：F0 correction 需要 performance/notation 分层

前面评审已指出，RVC 应使用 performance-oriented corrected F0，而不是 notation-only notes。否则会把滑音、颤音、哭腔抹掉，听感变机械。

RVC corrected F0 应该：

```text
原始 F0 保留 vibrato/slide 微结构
ScoreIR 只提供 note center / target pitch / 长音音准约束
对明显跑调或八度错做温和 correction
```

不能直接用 MIDI 音高阶梯替代 F0。

## 最小可接入方案

如果要“作为插件塞入”，建议分三层，不要一步到位硬跑：

### Phase 1：CorrectedF0 插件

新增插件：`rvc_correct_f0`

输入：

- `ScoreRevision.score_ir`
- `f0_track` artifact
- `vocal_activity`
- 参数：`transpose_semitones`

输出：

- `corrected_f0_track.json`
- `ArtifactType.CORRECTED_F0_TRACK`

职责：只生成 corrected F0，不调外部 RVC。

### Phase 2：RVC Prepare 插件升级

当前 `rvc_prepare` 可以保留，但应改成只校验并生成提交 payload：

```text
vocals_stem + corrected_f0_track + voice_model_id + transpose -> external RVC submit payload
```

不要在 prepare 阶段调用外部服务。

### Phase 3：RVC Submit/Result 插件或 Job Worker

新增：

- `rvc_submit`：提交外部 RVC job，保存 external job id。
- `rvc_poll`：查询状态，下载 converted vocal。
- `rvc_mix`：和 accompaniment 混音，落 `rvc_mix` artifact。

输出：

- `rvc_vocal` artifact
- `rvc_mix` artifact

## 推荐插件边界

```text
read-only plugin:
  rvc_prepare

artifact-producing plugin:
  rvc_correct_f0
  rvc_submit
  rvc_mix
```

注意：artifact-producing plugin 不能直接绕过 service 写 DB。应该通过专门的 `RvcCoverService` 或 `ArtifactService` 写库，保持数据链路：

```text
ScoreRevision + F0Track
  -> CorrectedF0Track artifact
  -> RVC external job
  -> RVC vocal artifact
  -> RVC mix artifact
```

## 是否现在就接？

我的判断：可以开始接，但不要直接接“调用 RVC 推理”。

最优先接入点是：

```text
rvc_correct_f0 plugin/service
```

原因：

1. 它是现在 `rvc_prepare` 的硬阻塞。
2. 它能复用现有 ScoreIR/F0 lineage。
3. 它决定最终 RVC 听感质量。
4. 外部 RVC client 反而是工程对接问题，不是产品质量核心。

## 一针见血

现在项目到的是：

```text
RVC 插件接口可挂，RVC 生产链路未就绪。
```

不要先塞一个外部 RVC HTTP client 进去，那会绕开最关键的 corrected F0。正确顺序是：

```text
1. 生成 corrected_f0_track artifact
2. 让 rvc_prepare 真正通过 validator
3. 再接外部 RVC submit/poll/download
4. 最后做 rvc_mix artifact
```
