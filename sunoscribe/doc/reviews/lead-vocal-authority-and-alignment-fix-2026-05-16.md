# Lead Vocal Authority And Alignment Fix

日期：2026-05-16

## 本次修复

本次修了两个问题：

1. `AudioAnalysisService` 之前没有把歌词识别与歌词对齐真正接入主链。
2. `AudioAnalysisService` 之前在 `process_audio()` 内部暴露 file-backed machine revision authority，和 DB `ScoreRevision` 并行，形成双 authority。

## 改动摘要

### 1. lyrics/alignment 真接入主链

修改文件：

- `backend/app/services/audio_analysis_service.py`

实际变化：

- `_run_perception_stage()` 在 pitch 转写成功后，调用 `_invoke_lyrics_recognizer()`。
- 识别输入优先使用 `vocals_path`，否则退回 canonical/source 音频。
- `lyrics_segments` 不再固定从空数组起步，而是由 recognizer 实际填充。
- `process_audio()` 不再调用 `_empty_alignment_stage()`，而是调用 `_run_alignment_stage(perception.score_ir_obj, options)`。
- 因此 baseline alignment / validator 现在会真正运行，`alignment_source` 正常变为 `baseline`，而不是固定 `plugin_deferred`。

### 2. 停止在 `AudioAnalysisResult` 暴露 file-backed machine revision authority

修改文件：

- `backend/app/services/audio_analysis_service.py`

实际变化：

- `process_audio()` 不再调用：
  - `_persist_machine_score_revision()`
  - `_run_revision_export_stage()`
- `AudioAnalysisResult` 仍保留 MIR / score 结果与 preview `midi_path`，但不再返回：
  - `score_revision`
  - `artifact_manifest_path`
  - `artifact_manifest`
  - `musicxml_path`

这意味着：

- `AudioAnalysisService` 现在退回为编排服务和 runtime artifact/cache 生产者；
- 产品侧唯一 machine revision authority 继续收敛到 DB `ScoreRevision`；
- revision-scoped exports 仍由 `score_revision_service + render_export_service` 负责。

## 为什么这是正确方向

当前产品链里真正被 API / task / score 服务消费的是 DB revision：

- `backend/app/services/score_service.py`
- `backend/app/services/score_revision_service.py`
- `backend/app/services/task_orchestrator.py`
- `backend/app/services/task_service.py`

因此继续让 `AudioAnalysisService` 暴露另一套 file-backed revision，只会制造 traceability 和排障混乱。

本次修复没有删掉 file-backed helper 函数本身，但已经把它们从主流程 authority 中拿掉。

## 测试

执行：

```powershell
.\.venv310\Scripts\python.exe -m pytest tests\test_audio_analysis_service.py tests\test_score_generation_service.py tests\test_typed_artifact_lineage.py tests\test_lyrics_integration.py tests\test_lyrics_recognizer.py tests\test_pitch_pipeline.py tests\test_quantizer.py tests\test_score_ir_builder.py -q
```

结果：

- `59 passed`

## 仍然没做的事

1. `score_revision_service` 里的 artifact snapshot 仍有共享 workspace 路径绑定问题。
2. `audio_analysis_service.py` 里 file-backed machine revision helper 还在文件里，虽然已不参与主流程。
3. lyrics recognition 目前按 optional 处理：
   - 失败会记录 warning
   - 不会中断 lead-vocal 主链

## 下一步建议

下一步最该做的是继续收尾 DB authority：

1. 让 `score_revision_service._register_analysis_artifacts()` 把 `score_ir/score_data` 等关键 artifact 写成 revision-scoped immutable snapshot。
2. 清理 `audio_analysis_service.py` 里已经退出主流程的 file-backed machine revision helper。
3. 再补一组“同一项目连续两次 machine revision，不覆盖旧 artifact path”的测试。

