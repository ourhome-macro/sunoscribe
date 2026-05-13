# SunoScribe Docs Index

本文档目录收敛后端、前端原型、音频处理、评测与运行策略说明。

## 建议阅读顺序

1. `backend-audio-pipeline.md`：后端音频流水线、typed data lineage、服务边界与 required stage 契约。
2. `mainline-plugin-architecture.md`：精简后的六个主干服务、目标依赖图与轻量内置插件 registry 边界。
3. `production-runtime-policy.md`：生产/诊断/benchmark profile、RMVPE fallback policy、artifact lineage 与失败策略。
4. `lead-vocal-mvp-execution.md`：第一阶段 lead-vocal MVP 的实际 API 执行流程、导出边界与验收标准。
5. `post-mvp-development-roadmap.md`：lead-vocal MVP 之后的开发顺序，包含真实前端、artifact API、ScorePatch、RVC 与钢琴编配边界。
6. `sunoscribe-mir-practical-guide.md`：面向当前项目状态的 MIR 实践指南，聚焦主链路、benchmark、artifact、revision 与错误分析。
7. `frontend-current-state.md`：当前 React/Vite 前端工作台原型的已实现页面、mock 数据边界与待对接后端事项。
8. `mvp-trial-runbook.md`：初步 MVP 试验步骤、runtime doctor、单曲 smoke 与 19 首 observe-only benchmark。
9. `mp4-midi-benchmark.md`：26 首 MP4 -> MIDI 本地 benchmark 设计、指标、manifest 与回归门禁。
10. `audio_processor.md`、`vocal_separator.md`、`pitch _detection.md`：早期模块级实现说明，可作为历史/实现参考。
11. `lyrics_processor.md`：歌词处理说明。

## 当前后端重点

- MP4/音频上传后先成为 `source_media` artifact。
- `MediaIngestService` 统一生成 canonical `data/projects/<project_id>/preprocess/source.wav`。
- `StemService` 只消费 canonical WAV，不直接消费原始 MP4。
- Production profile 下 RMVPE 不允许静默 fallback 到 CREPE/basic-pitch。
- 第一阶段输出是 lead-vocal melody MIDI / MusicXML，不是完整伴奏 MIDI 或钢琴编配谱。
- MVP 试验先跑 `doctor -> validate -> single-song smoke -> 19-song observe-only benchmark`。
- MP4 -> MIDI 质量评测以本地 deterministic benchmark 为主，LangSmith 只用于后续 agent/LLM workflow 评估。

## 当前前端重点

- `frontend/` 已是 `React + Vite + TypeScript` 工作台原型，不再是空占位目录。
- 当前页面和组件围绕 Project、ScoreRevision、Artifact、diagnostics、agent patch workflow 组织。
- 当前数据层仍主要读取 `frontend/src/lib/api/mock-data.ts`，尚未接真实后端 API。
- OSMD 与 MIDI 播放仍是展示/封装占位，后续必须从选定 `ScoreRevision` 派生的 artifact 加载。

## 后续开发重点

- 先按 `lead-vocal-mvp-execution.md` 用真实音频跑通主唱旋律 MIDI / MusicXML。
- 再补 artifact list/download API，避免前端直接拼 workspace 文件路径。
- 然后把前端 mock client 替换为真实 API client，并接入 OSMD 与 MIDI 播放。
- ScorePatch、RVC 与 piano arrangement 应按 `post-mvp-development-roadmap.md` 分阶段推进。
