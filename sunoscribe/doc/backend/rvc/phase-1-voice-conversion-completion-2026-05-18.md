# RVC 第一阶段完成声明：变声器模式

日期：2026-05-18

## 状态

RVC 第一阶段结束。

本阶段目标不是完整 score-guided cover，而是先把 RVC 作为“变声器”插件能力接入系统：

```text
vocals_stem artifact
  -> external RVC voice conversion
  -> rvc_vocal artifact
```

当前该目标已完成。

## 已完成范围

- 新增 `voice_conversion` 模式。
- `rvc_prepare` 支持 `mode="voice_conversion"`。
- `voice_conversion` 模式只要求 `vocals_stem`，不再要求 `corrected_f0_track`。
- 新增外部 RVC client，以 `multipart/form-data` 调用外部 RVC 服务。
- 新增 API：

```text
POST /api/score-revisions/{revision_id}/agent/rvc/voice-conversion
```

- RVC 返回音频会落库为：

```text
artifact_type = rvc_vocal
```

- 文档已记录接口协议和配置方式：

```text
doc/backend/rvc/voice-conversion-plugin-2026-05-18.md
```

## 配置要求

后端 `.env` 需要配置：

```env
RVC_ENDPOINT_URL=http://your-rvc-service/convert
RVC_API_KEY=optional-token
RVC_REQUEST_TIMEOUT_SECONDS=600
```

如果 `RVC_ENDPOINT_URL` 未配置，系统会明确失败，不会生成伪 artifact。

## 明确不包含

本阶段不做以下内容：

- `corrected_f0_track` 生成。
- 按 `ScoreIR` 或用户修谱结果做逐音修准。
- score-guided RVC cover。
- RVC mix 与伴奏混音。
- RVC job 异步队列、轮询、外部 job 状态管理。
- voice model 注册表和权限系统。

这些进入后续阶段，择日再说。

## 当前边界

当前能力应在产品和代码中明确标记为：

```text
mode = "voice_conversion"
score_guided = false
```

也就是说，它是变声器，不是最终的按谱 cover 生产链路。

## 验证

针对性测试已通过：

```text
backend/tests/test_agents.py
backend/tests/test_agent_workflow_service.py
backend/tests/test_agent_workflow_api.py
backend/tests/test_rvc_voice_conversion_service.py
backend/tests/test_plugin_registry.py
```

结果：

```text
27 passed
```

## 后续再开事项

后续如继续 RVC，应从以下方向择一开新阶段：

1. `corrected_f0_track` 生成服务。
2. score-guided RVC cover。
3. RVC mix artifact。
4. 外部 RVC job 异步化。
5. voice model registry / 权限 / 模型版本管理。

在上述新阶段开始前，RVC 第一阶段不再扩 scope。
