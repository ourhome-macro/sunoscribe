# RVC 变声器模式接入说明

日期：2026-05-18

## 目标

本次先接入“变声器模式”的 RVC，不依赖当前仍在打磨中的 ScoreIR/corrected F0。

该模式明确标记为：

```text
mode = "voice_conversion"
score_guided = false
```

它只做：

```text
vocals_stem artifact
  -> external RVC service
  -> rvc_vocal artifact
```

不做：

- ScoreIR-guided F0 correction
- corrected_f0_track
- RVC mix
- 按用户编辑后的谱逐音修准

## 新增配置

在 backend `.env` 中配置：

```env
RVC_ENDPOINT_URL=http://your-rvc-service/convert
RVC_API_KEY=optional-token
RVC_REQUEST_TIMEOUT_SECONDS=600
```

如果 `RVC_ENDPOINT_URL` 未配置，变声器调用会明确失败，不会伪造成功产物。

## 新增 API

### 1. Prepare RVC job

原 endpoint 保留，并新增 `mode` 参数：

```text
POST /api/score-revisions/{revision_id}/agent/rvc/prepare
```

请求：

```json
{
  "mode": "voice_conversion",
  "voice_model_id": "voice-a",
  "transpose_semitones": 0
}
```

`voice_conversion` 模式只要求 `vocals_stem` artifact，不要求 `corrected_f0_track` 或 `accompaniment_stem`。

### 2. Run voice conversion

新增 endpoint：

```text
POST /api/score-revisions/{revision_id}/agent/rvc/voice-conversion
```

请求：

```json
{
  "voice_model_id": "voice-a",
  "transpose_semitones": 0
}
```

响应包含：

- `rvc_vocal_artifact_id`
- `source_vocal_stem_artifact_id`
- `voice_model_id`
- `transpose_semitones`
- `artifact` public metadata

## 外部 RVC 服务协议

当前 client 使用 `multipart/form-data` POST 到 `RVC_ENDPOINT_URL`：

字段：

- `vocals`: vocal wav 文件
- `voice_model_id`: 模型 ID
- `transpose_semitones`: 整体升降 key
- `mode`: `voice_conversion`
- `metadata`: JSON 字符串，包含 project/revision/source artifact id

返回：

- response body：转换后的音频 bytes
- content-type：建议 `audio/wav`，也支持 `audio/mpeg` / `audio/flac`

系统会把返回音频落为：

```text
ArtifactType.RVC_VOCAL
```

并写入 revision 工作区：

```text
data/projects/{project_id}/revisions/{revision_id}/rvc/rvc_vocal_*.wav
```

## 重要边界

该链路是“变声器”，不是正式 score-guided cover。

它不会使用：

- ScoreIR note center
- 用户修谱后的 ScoreRevision edits
- CorrectedF0Track
- pitch contour / phrase trace

因此输出音准完全取决于原 vocals 和外部 RVC 服务自己的处理能力。

## 后续生产升级路径

后续再做正式 RVC cover 时，继续沿用同一插件边界：

```text
score_guided mode:
  vocals_stem + ScoreRevision + F0Track
    -> corrected_f0_track artifact
    -> external RVC
    -> rvc_vocal artifact
    -> rvc_mix artifact
```

当前新增的 `voice_conversion` 不会阻塞后续 `score_guided`，因为两者通过 `RvcJobSpec.mode` 区分。

## 已验证

针对性测试：

```text
backend/tests/test_agents.py
backend/tests/test_agent_workflow_service.py
backend/tests/test_agent_workflow_api.py
backend/tests/test_rvc_voice_conversion_service.py
backend/tests/test_plugin_registry.py
```

结果：27 passed。
