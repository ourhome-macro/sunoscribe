# 音频处理链路（兼容入口）

本文件不再单独定义 SunoScribe 后端的正式音频流水线事实。

唯一正式事实源为：

- `../architecture/backend-audio-pipeline.md`
- `../architecture/production-runtime-policy.md`

## 目的

保留本文件仅为了兼容历史链接、README 引用和旧的工程入口说明，避免在仓库中继续传播过期语义。

## 当前应遵循的统一语义

- required stage 失败必须显式失败。
- production 禁止 pitch backend fallback。
- production 禁止 audio stub / fake score / silent downgrade。
- 导出必须绑定到明确的 `ScoreRevision`。
- `ScoreIR` / `ScoreRevision` 是导出与修订链的中心边界。

## 已废弃的旧说法

以下表述已废弃，不应再作为当前系统行为理解：

- “缺少 RMVPE runtime 或模型时回退到 CREPE/basic-pitch”
- “无音频时生成 backend stub fallback”
- “导出优先从 workspace 或 `score_data.measures` 作为主真相源生成”
- “workspace 中已有 MIDI/MusicXML 优先于 revision 语义”

## 迁移说明

如果你是从旧文档入口进入这里，请直接改读下面两份文档：

- `../architecture/backend-audio-pipeline.md`
- `../architecture/production-runtime-policy.md`

它们描述的是当前正式的：

- typed data lineage
- required stage contract
- artifact lineage
- production runtime policy
- revision-scoped export boundary
