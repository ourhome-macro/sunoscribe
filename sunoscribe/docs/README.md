# SunoScribe Docs Index

本文档目录收敛后端、音频处理、评测与运行策略说明。当前阶段暂不覆盖前端实现细节。

## 建议阅读顺序

1. `backend-audio-pipeline.md`：后端音频流水线、typed data lineage、服务边界与 required stage 契约。
2. `production-runtime-policy.md`：生产/诊断/benchmark profile、RMVPE fallback policy、artifact lineage 与失败策略。
3. `mp4-midi-benchmark.md`：26 首 MP4 -> MIDI 本地 benchmark 设计、指标、manifest 与回归门禁。
4. `audio_processor.md`、`vocal_separator.md`、`pitch _detection.md`：早期模块级实现说明，可作为历史/实现参考。
5. `lyrics_processor.md`：歌词处理说明。

## 当前后端重点

- MP4/音频上传后先成为 `source_media` artifact。
- `MediaIngestService` 统一生成 canonical `data/projects/<project_id>/preprocess/source.wav`。
- `StemService` 只消费 canonical WAV，不直接消费原始 MP4。
- Production profile 下 RMVPE 不允许静默 fallback 到 CREPE/basic-pitch。
- MP4 -> MIDI 质量评测以本地 deterministic benchmark 为主，LangSmith 只用于后续 agent/LLM workflow 评估。
