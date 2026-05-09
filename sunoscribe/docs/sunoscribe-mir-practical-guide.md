# SunoScribe MIR 实践指南

本文档是基于 `06_mir_practical_problem_solving_guide.md` 为 SunoScribe 当前项目状态定制的一版工程实践指南。

目标不是重复通用 MIR 理论，而是把其中对 SunoScribe 当前系统真正有用的部分，翻译成我们现在能直接执行的项目方法。

本文以当前正式事实源为前提：

- `backend-audio-pipeline.md`
- `production-runtime-policy.md`

如果本文与实现不一致，应优先修实现或在正式事实源中修正文档，而不是在这里追加新口径。

## 1. 先把 SunoScribe 当前任务说清楚

SunoScribe 当前最核心的任务不是“做一个音乐理解平台”，而是：

```text
输入：用户上传的音频或视频
输出：可编辑的 lead-vocal ScoreRevision，以及由该 revision 派生的 MIDI / MusicXML / score view
约束：required stage 失败必须显式失败
评估：note-level 指标、quality gate、stage success/failure、runtime、错误分类
```

这意味着：

- 当前主任务是 lead-vocal transcription，不是通用推荐、检索或标签系统。
- `ScoreIR` / `ScoreRevision` 是当前产品边界的中心，不是临时导出结构。
- 我们更关心“谱子是否可信、链路是否可追踪、失败是否可诊断”，而不是“是否已经支持很多 MIR 子任务”。

## 2. 当前系统最重要的主线

现在最值得守住的不是功能数量，而是这条最小闭环：

```text
Upload
-> MediaAsset
-> CanonicalAudio
-> StemSet
-> F0Track
-> NoteCandidateSet
-> RhythmGrid
-> ScoreRevision
-> Export Artifacts
```

工程上应把它理解成 SunoScribe 的第一性主线。

任何新改动，优先问：

- 它是否强化了这条主线？
- 它是否让这条主线更可追踪、更稳定、更可评估？
- 它是否会让 required stage 失败被掩盖？

如果答案是否定的，这个改动大概率不该优先做。

## 3. 当前最适合 SunoScribe 的分层理解

通用 MIR 项目建议分层，这对 SunoScribe 当前也非常适用。

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

注意：

- 编排层要继续收口成 orchestrator
- 不要再回退成“大而全的万能服务”

### 3.3 领域模型层

当前对应：

- `ScoreRevision`
- `Artifact`
- `ScorePatch`
- `Project`
- `Task`

职责：

- 定义可审计、可追踪的核心业务对象
- 让“谱子版本”“导出工件”“修订操作”变成一等对象

### 3.4 算法能力层

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

### 3.5 数据与工程治理层

当前对应：

- workspace 中间产物
- benchmark manifest
- quality gate
- readiness report
- revision/artifact 持久化

职责：

- 保持数据可追踪
- 保持评估可复现
- 保持失败可归因

## 4. 对 SunoScribe 当前最有价值的项目方法

### 4.1 最小闭环优先，不扩散目标

当前最值得优化的不是“支持更多 MIR 任务”，而是把主链做到稳：

- 上传稳定
- canonical audio 一致
- stems 可靠
- F0 / note candidates 可信
- rhythm grid 不污染记谱
- ScoreRevision 清晰
- export revision-scoped
- benchmark 能稳定报告失败原因

结论：

- 和弦、结构、通用标签、推荐、复杂前端体验，都不是当前第一优先。
- 先把 lead-vocal transcription 做成一个可信的工程系统。

### 4.2 Manifest 与版本先行

对 SunoScribe 来说，当前最该继续强化的是：

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

当前系统更应该关注这些表示边界，而不是优先换更大的模型：

- `CanonicalAudio` 是否统一
- `vocals.wav` 是否真的是 required input
- `F0Track` 是否足够连续、可诊断
- `NoteCandidateSet` 是否只是候选，不被误当最终谱
- `RhythmGrid` 是否独立存在
- `ScoreIR` 是否真的是中心表示
- export 是否真正从 selected revision 派生

在 SunoScribe 当前阶段，表示和边界的正确性，比继续堆模型复杂度更重要。

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
- 失败是上游 stage 问题，还是 reference 问题，还是导出问题

### 4.5 把 debug 顺序固定下来

当前最适合 SunoScribe 的调试顺序是：

1. 先确认任务定义没有偏。
2. 再确认输入和 benchmark 样本可信。
3. 再看 canonical audio / stems / F0Track 是否成立。
4. 再看 note candidates / rhythm grid / score build。
5. 再看 patch/export/revision 是否保持一致。
6. 最后才考虑换模型、调参数、扩功能。

这个顺序能避免一上来就“换模型试试”，而忽略真正的问题常常在：

- 输入质量
- stage contract
- 中间表示
- benchmark 参考
- 后处理

## 5. 当前最该优先解决的问题类型

基于现状，最值得优先处理的是以下几类问题。

### 5.1 Required stage 失败语义还没完全下沉

现在正式文档已经要求：

- vocal separation 失败必须失败
- production pitch 失败必须失败
- required artifact 缺失必须失败

但实现里仍有部分阶段先记 warning 再继续的历史编排习惯。

这类问题的优先级很高，因为它决定了 production policy 是否真的可信。

### 5.2 导出边界还要继续以 `ScoreIR` / `ScoreRevision` 为中心收口

当前系统已经引入了 revision-scoped export，但实现里还保留一些兼容层与旧的 workspace 级路径。

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

当前 benchmark 已经不是简单 demo 了，但还可以更进一步：

- 失败 taxonomy 聚合
- hard-case bucket 报告
- 对 reference suspect 样本单独统计
- 把“系统失败”和“参考问题”持续分开

这是当前最值得投入的 MIR 工程收益点之一。

## 6. 当前不该优先做的事

为了防止目标扩散，下面这些事情应明确降级优先级。

### 6.1 不优先做通用音乐检索/推荐平台

虽然通用 MIR 文档里有大量检索和推荐路线，但这不是 SunoScribe 当前 MVP 主线。

现在不是去做：

- 以歌搜歌
- 相似歌曲推荐
- 大规模 embedding 检索平台

的时候。

### 6.2 不优先做大而全的多任务平台

现在也不适合同时把：

- 和弦
- 结构
- 情绪标签
- 推荐
- RVC 产品化

全部拉高优先级。

当前最重要的是把 lead-vocal score pipeline 做稳。

### 6.3 不优先靠更复杂模型掩盖工程边界问题

如果当前问题来自：

- required stage 失败语义不清
- 中间表示不稳定
- reference 有问题
- 导出边界没收口

那么先换更大的模型通常不会从根本上解决问题。

## 7. SunoScribe 当前建议的工程检查清单

每次做改动时，建议至少检查这些问题：

### 7.1 任务边界

- 这次改动是否仍然服务于 lead-vocal score MVP？
- 是否引入了和当前主线无关的能力扩张？

### 7.2 数据链路

- 是否仍然沿着 `MediaAsset -> CanonicalAudio -> StemSet -> F0Track -> NoteCandidateSet -> RhythmGrid -> ScoreRevision -> Export Artifacts` 推进？
- 是否新增了绕过中间层直接写最终产物的逻辑？

### 7.3 Required stage

- 是否把 required stage 失败显式暴露为失败？
- 是否存在 silent fallback、stub、fake output、占位导出？

### 7.4 Revision / Artifact

- 这次输出是否绑定到明确 `ScoreRevision`？
- 这次产物是否注册为 `Artifact`？
- 是否保留 project/task/revision lineage？

### 7.5 Benchmark / Evaluation

- 改动后是否能在 benchmark 中被观察到？
- 是否新增了可诊断的错误分类，而不是只新增一个平均分？
- 是否会影响 hard-case 或 reference-suspect 样本的解释性？

## 8. 给当前团队的简短工作原则

最后给 SunoScribe 当前阶段一个最短版本的实践原则：

1. 先把任务边界钉死。
2. 先把最小闭环跑稳。
3. 先让数据链和 revision 链可信。
4. 先让 benchmark 能解释失败。
5. 先解决 required stage 和导出边界问题。
6. 再考虑扩模型、扩任务、扩产品面。

这份指南的目的，是帮助我们把 SunoScribe 继续做成一个：

- 边界清晰
- 数据可追踪
- 失败可诊断
- 导出可审计
- 可逐步扩展

的 MIR 工程系统，而不是把它重新带回到“功能很多但语义混乱”的原型状态。
