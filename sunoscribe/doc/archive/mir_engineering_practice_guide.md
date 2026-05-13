# SunoScribe MIR 工程实践指南

本文档基于项目内的 MIR 实战材料整理而成，用于约束 SunoScribe 当前后端主链路的工程实践。

目标不是扩展新的功能路线，而是把对当前系统真正有用的方法沉淀成一份克制、可执行的工程文档。

正式事实源仍以以下文档为准：

- `../architecture/backend-audio-pipeline.md`
- `../architecture/production-runtime-policy.md`

如果本文与实现不一致，应优先修实现，或在正式事实源中修正文档，而不是在本文中增加临时口径。

## 适用范围

本文只约束当前 SunoScribe 的 lead-vocal transcription MVP，不作为以下方向的设计依据：

- 通用音乐检索平台
- 相似歌曲推荐系统
- 多任务 MIR 平台
- RVC 产品化路线
- 复杂前端交互系统

本文聚焦的是当前已经实现或正在明确过渡中的后端主链路、修订链、artifact 链和 benchmark 方法。

## 1. 先把当前任务定义清楚

SunoScribe 当前的核心任务不是“做一个音乐理解平台”，而是：

```text
输入：用户上传的音频或视频
输出：可编辑的 lead-vocal ScoreRevision，以及由该 revision 派生的 MIDI / MusicXML / score view
约束：required stage 失败必须显式失败
评估：note-level 指标、quality gate、stage success/failure、runtime、错误分类
```

这意味着：

- 当前主任务是 lead-vocal transcription，不是推荐、检索或通用标签系统。
- `ScoreIR` / `ScoreRevision` 是当前产品边界的中心，不是临时导出结构。
- 当前最重要的不是扩能力面，而是让谱子可信、链路可追踪、失败可诊断。

## 2. 当前系统最重要的主线

当前必须守住的主线不是功能数量，而是这条最小闭环：

```text
Upload
-> MediaAsset
-> CanonicalAudio
-> StemSet
-> F0Track
-> NoteCandidateSet
-> RhythmGrid
-> ScoreIR
-> ScoreRevision
-> Export Artifacts
```

工程上应把它理解成 SunoScribe 当前的第一性主线。

任何新改动，都优先问三个问题：

- 它是否强化了这条主线？
- 它是否让这条主线更可追踪、更稳定、更可评估？
- 它是否会掩盖 required stage 的失败？

如果答案是否定的，这个改动通常不该优先做。

## 3. 当前最适合 SunoScribe 的分层理解

通用 MIR 项目建议分层，这对当前 SunoScribe 也适用。

### 3.1 入口层

当前对应：

- FastAPI API
- benchmark CLI

职责：

- 接收上传、导出、任务查询、benchmark 命令
- 不承担核心 MIR 算法实现

### 3.2 应用编排层

当前对应：

- `AudioAnalysisService`
- `TaskOrchestrator`
- `score_service`

职责：

- 串联阶段
- 管理任务生命周期
- 组织导出和持久化

要求：

- 编排层继续收口成 orchestrator
- 不要回退成“大而全的万能服务”

### 3.3 领域模型层

当前对应：

- `ScoreIR`
- `ScoreRevision`
- `Artifact`
- `ScorePatch`
- `Project`
- `Task`

职责：

- 定义可审计、可追踪的核心业务对象
- 让谱面版本、导出工件、修订操作成为一等对象

### 3.4 阶段能力层

当前对应：

- `MediaIngestService`
- `StemService`
- `MelodyTranscriptionService`
- `RhythmQuantizationService`
- `ScoreBuildService`
- `RenderExportService`

职责：

- 每个阶段只处理自己的输入输出
- 保持 typed data lineage

这里使用“阶段能力层”而不是“算法能力层”，是为了避免把 ingest、score build、export 等工程边界错误理解为纯算法模块。

### 3.5 数据与工程治理层

当前对应：

- workspace 中间产物
- benchmark manifest
- quality gate
- readiness report
- revision / artifact 持久化

职责：

- 保持数据可追踪
- 保持评估可复现
- 保持失败可归因

## 4. 当前最有价值的项目方法

### 4.1 最小闭环优先，不扩散目标

当前最值得优化的不是“支持更多 MIR 任务”，而是把主链做到稳：

- 上传稳定
- canonical audio 一致
- stems 可靠
- F0 / note candidates 可信
- rhythm grid 不污染记谱
- ScoreIR 清晰
- ScoreRevision 清晰
- export revision-scoped
- benchmark 能稳定报告失败原因

结论：

- 和弦、结构、通用标签、推荐、复杂前端体验，不是当前第一优先。
- 先把 lead-vocal transcription 做成一个可信的工程系统。

### 4.2 Manifest 与版本先行

当前最该继续强化的是：

- benchmark manifest
- artifact lineage
- revision lineage
- 配置快照
- 失败分类

任何真实评测和回归，都应该能回答：

- 这个结果来自哪个输入？
- 用了哪个 runtime profile？
- 用了哪个 revision？
- 哪个 stage 失败了？
- 哪个工件缺失了？

### 4.3 表示优先于模型复杂度

当前系统更应该优先关注这些边界：

- `CanonicalAudio` 是否统一
- `vocals.wav` 是否真的是 required input
- `F0Track` 是否足够连续、可诊断
- `NoteCandidateSet` 是否只是候选，不被误当最终谱
- `RhythmGrid` 是否独立存在
- `ScoreIR` 是否真的是中心表示
- export 是否真正从 selected revision 派生

在当前阶段，表示和边界的正确性，比继续堆模型复杂度更重要。

### 4.4 不只看总分，要做错误分桶

当前 benchmark 已经具备：

- note-level metrics
- audibility metrics
- quality gate
- reference review
- suspected failure modes
- stage status

下一步最值得做的是分桶分析，例如：

- 伴奏复杂 / 伴奏简单
- 高音域 / 中音域 / 低音域
- 节奏稀疏 / 节奏密集
- 滑音明显 / 平稳旋律
- 参考 MIDI 可疑 / 参考 MIDI 可信

目标不是追求一个“整体 F1”，而是知道：

- 哪类歌最容易失败
- 哪类失败最常见
- 失败是上游 stage 问题、reference 问题，还是导出问题

### 4.5 把 debug 顺序固定下来

当前最适合 SunoScribe 的调试顺序是：

1. 先确认任务定义没有偏。
2. 再确认输入和 benchmark 样本可信。
3. 再看 canonical audio / stems / F0Track 是否成立。
4. 再看 note candidates / rhythm grid / ScoreIR / score build。
5. 再看 patch / export / revision 是否保持一致。
6. 最后才考虑换模型、调参数、扩功能。

这个顺序能避免一上来就“换模型试试”，而忽略真正的问题常常在：

- 输入质量
- stage contract
- 中间表示
- benchmark 参考
- 后处理

## 5. 当前最值得优先收口的工程风险

### 5.1 Required stage 失败语义还没完全下沉

正式文档已经要求：

- vocal separation 失败必须失败
- production pitch 失败必须失败
- required artifact 缺失必须失败

但实现里仍有部分阶段先记 warning 再继续的历史编排习惯。

这是高优先级工程风险，因为它直接影响 production policy 是否可信。

### 5.2 导出边界还要继续以 `ScoreIR` / `ScoreRevision` 为中心收口

当前系统已经引入 revision-scoped export，但实现里还保留了一些兼容层与旧的 workspace 级路径。

优先方向应是：

- 导出逻辑继续围绕 selected revision
- `ScoreIR` / `ScoreRevision` 继续成为真正中心边界
- legacy workspace export 继续降级成调试或兼容用途

### 5.3 Artifact lineage 还可以更完整

当前 artifact 已经接入，但还值得继续加强：

- `task_id` 全链路贯通
- source media probe 更完整
- stage 元数据更统一
- benchmark / runtime profile 写入 artifact metadata

这会直接改善：

- 审计
- 调试
- benchmark 归因
- 后续 agent 只读诊断能力

### 5.4 Benchmark 还应继续从“有指标”进化到“有分桶结论”

当前 benchmark 已经不是简单 demo，但还可以更进一步：

- 失败 taxonomy 聚合
- hard-case bucket 报告
- 对 reference-suspect 样本单独统计
- 把“系统失败”和“参考问题”持续分开

这是当前最值得投入的工程收益点之一。

## 6. 当前应避免的工程反模式

### 6.1 Silent fallback

表现：

- required stage 失败后只记 warning
- 继续用低质量替代结果往下跑
- 最终看起来“有输出”，但输出不可信

在当前系统中，这是必须继续压缩和消除的反模式。

### 6.2 Workspace-first export

表现：

- 把 workspace 中已有文件当导出真相源
- 让导出优先依赖历史临时产物，而不是 selected revision
- 让 revision-scoped export 退化成兼容层

当前应坚持：

- export 绑定 selected `ScoreRevision`
- `ScoreIR` / `ScoreRevision` 是导出边界

### 6.3 Metric-only benchmark

表现：

- 只看一个总分
- 不区分 pipeline failure 和 quality failure
- 不做样本分桶
- 不追踪 reference suspect 情况

当前 benchmark 已经比这更成熟，后续不应退回到只看总分的状态。

### 6.4 Model-first debugging

表现：

- 一看到结果不好就先换模型
- 不先检查输入、stage、reference、后处理

当前更有效的方式是：

- 先查任务边界
- 再查输入和中间表示
- 再查 benchmark 参考和失败分类
- 最后才查模型

### 6.5 Feature-first expansion

表现：

- 主链未稳就继续加和弦、结构、推荐、复杂前端、RVC 产品化
- 把资源从主链稳定性抽走

当前不应优先做能力面扩张，而应继续收口主线闭环。

## 7. 工程检查清单

每次做改动时，建议至少检查以下问题：

### 7.1 任务边界

- 这次改动是否仍然服务于 lead-vocal score MVP？
- 是否引入了和当前主线无关的能力扩张？

### 7.2 数据链路

- 是否仍然沿着 `MediaAsset -> CanonicalAudio -> StemSet -> F0Track -> NoteCandidateSet -> RhythmGrid -> ScoreIR -> ScoreRevision -> Export Artifacts` 推进？
- 是否新增了绕过中间层直接写最终产物的逻辑？

### 7.3 Required stage

- 是否把 required stage 失败显式暴露为失败？
- 是否存在 silent fallback、stub、fake output、占位导出？

### 7.4 Revision / Artifact

- 这次输出是否绑定到明确 `ScoreRevision`？
- 这次产物是否注册为 `Artifact`？
- 是否保留 project / task / revision lineage？

### 7.5 Benchmark / Evaluation

- 改动后是否能在 benchmark 中被观察到？
- 是否新增了可诊断的错误分类，而不是只新增一个平均分？
- 是否会影响 hard-case 或 reference-suspect 样本的解释性？

### 7.6 文档事实源

- `backend-audio-pipeline.md` 是否仍然与实现一致？
- `production-runtime-policy.md` 是否仍然与实现一致？
- README 是否复述了同一套 production 语义？
- benchmark 文档是否仍然与当前主链评估口径一致？

## 8. 当前阶段的简短工作原则

1. 先把任务边界钉死。
2. 先把最小闭环跑稳。
3. 先让数据链、ScoreIR 链和 revision 链可信。
4. 先让 benchmark 能解释失败。
5. 先解决 required stage 和导出边界问题。
6. 再考虑扩模型、扩任务、扩产品面。

本文的目的，是帮助 SunoScribe 继续成为一个：

- 边界清晰
- 数据可追踪
- 失败可诊断
- 导出可审计
- 可逐步扩展

的 MIR 工程系统，而不是回到“功能很多但语义混乱”的原型状态。
