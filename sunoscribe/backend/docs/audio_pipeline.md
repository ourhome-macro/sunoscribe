# 音频处理链路

## 入口

上传接口：

- `POST /api/upload/audio`
- `POST /api/upload/video`

上传成功后，后端会把返回的本地路径或 `s3://...` 对象路径写入 `projects.audio_path`。谱面生成时以这个字段作为音频分析入口。

## 主流程

`generate_or_regenerate_score` 会读取项目并调用 `AudioAnalysisService`：

1. `ProjectWorkspace.save_input_copy` 保存原始输入副本。
2. `AudioProcessor` 在没有可用 stems 时生成归一化 fallback 音频。
3. `VocalSeparator` 可选做人声/伴奏/stems 分离。
4. 歌词识别优先使用 vocals，否则使用 fallback 音频。
5. `PitchPipeline` 处理主旋律、节拍、调式、下拍、量化、小节。
6. `BaselineAnalysisInferencer` 生成 Analysis IR。
7. `ScoreIRBuilder` 生成 Score IR、和弦、结构段落和 bassline。
8. `InitialLyricsAligner` 和可选 LLM refine 生成歌词-音符对齐。
9. 导出或持久化 `score_data`、`score_ir`、alignment、MIDI 等产物。

生成后的 `scores.score_data` 包含：

- `measures`：导出 MIDI/MusicXML 的主要输入。
- `pitch_result`：pitch pipeline 原始分析摘要。
- `analysis_ir`：伴奏、和弦、结构等推断结果。
- `score_ir`：规范化谱面 IR。
- `alignment`：baseline/refined/final 歌词对齐。
- `midi_path` / `final_midi_path`：可复用的 MIDI 产物路径。
- `warnings`：分析、序列化、导出阶段的合并告警。

## 音高检测

默认 backend 是 RMVPE：

```env
PITCH_BACKEND=rmvpe
PITCH_BACKEND_FALLBACKS=crepe,basic-pitch
RMVPE_MODEL_PATH=
```

预期效果：

- RMVPE 通常比 basic-pitch 更适合人声音高轮廓，尤其是滑音、颤音和连续 f0 轨迹。
- 对伴奏较重或人声分离较差的素材，输入 stems 质量仍然会显著影响结果。
- 缺少 RMVPE runtime 或模型时，当前实现会记录 fallback warning，并尝试 CREPE/basic-pitch，避免整条链路直接失败。

## 导出

`GET /api/scores/{score_id}/export?export_format=...` 支持：

- `midi`：优先读取 workspace 中已有 MIDI；没有时从 `score_data.measures` 生成。
- `musicxml`：优先读取已有 MusicXML；没有时从 `score_data.measures`、`chord_timeline`、`form_sections` 生成。
- `pdf`：当前为后端摘要 PDF fallback。

## 覆盖测试

主链路测试：

- `tests/test_audio_flow_integration.py`：上传回写、分析落谱、歌词对齐、MIDI/MusicXML 导出。
- `tests/test_audio_analysis_service.py`：workspace、stems、fallback 音频和 pitch 请求路由。
- `tests/test_score_generation_service.py`：生成谱面、歌词持久化、无音频 stub fallback。
- `tests/test_score_export_service.py`：MIDI/MusicXML/PDF 导出。
- `tests/test_pitch_runtime_health.py`：RMVPE/cache 健康检查。

推荐命令：

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m unittest tests.test_audio_flow_integration tests.test_pitch_runtime_health
.\.venv310\Scripts\python.exe -m pytest -q tests -o cache_dir=.tmp_tests\.pytest_cache
```

## 真实音频验证清单

单元测试不会下载模型，也不会跑真实长音频。接入部署前需要用真实样本补一轮手工或半自动验证：

- `GET /api/health/pitch?deep=true` 能加载 RMVPE。
- 上传 30-60 秒人声音频后能生成非空 `measures`。
- `score_data.pitch_result.analysis_info.detector` 为 `rmvpe` 或明确记录 fallback。
- MIDI 可播放，MusicXML 可被 MuseScore/同类软件打开。
- 歌词对齐 `alignment.final.alignments` 非空，且 token/note 顺序没有明显倒退。
