# 生产运行策略：Pitch Fallback Policy 与 Artifact Lineage

本文档定义 SunoScribe 在后端与音频处理链路中的生产运行策略，重点覆盖 Pitch backend fallback 规则、artifact 注册与 lineage 要求、required stage 失败处理，以及不同运行 profile 的建议配置。

## 1. 适用范围

本文档适用于以下后端处理阶段与相关运维配置：

- 媒体上传与 media ingest
- vocal separation 之后的主旋律 F0 提取
- pitch backend 选择与 fallback 策略
- artifact 注册、metadata 持久化与 lineage 追踪
- required artifact / debug artifact 的错误处理与审计

本文档聚焦生产后端、任务执行与音频处理，不讨论前端渲染细节。

## 2. 运行原则

### 2.1 Production profile 不允许静默降级

在 `production` profile 下，RMVPE 是 lead-vocal F0 extraction 的必需后端。生产环境必须遵守以下原则：

- `RMVPE` 不可用、模型文件缺失、初始化失败、推理失败时，任务必须显式失败。
- 不允许自动回退到 `CREPE`、`basic-pitch` 或其他低质量替代后端。
- 不允许产出“近似可用”的 notes、score 或导出文件来掩盖 pitch stage 失败。
- 错误必须可追踪、可审计，并能关联到 task、project、artifact lineage。

这与项目的 No Silent Fallback Policy 一致：生产系统优先选择“正确失败 + 可追踪诊断”，而不是“看似成功但结果不可靠”。

### 2.2 Diagnostic / Benchmark profile 才允许 fallback

仅在以下 profile 中允许启用 pitch backend fallback：

- `diagnostic`
- `benchmark`

这些 profile 的用途是：

- 对依赖缺失、模型故障、不同 backend 行为差异进行诊断
- 对 RMVPE 与备用 backend 做性能或误差对比
- 在开发或研究环境中收集失败样本与 debug artifacts

即使允许 fallback，也必须满足以下要求：

- fallback 行为必须由显式配置开启，不得默认隐式触发。
- 运行记录中必须保存“原始首选 backend”“实际使用 backend”“fallback 原因”。
- 由 fallback 生成的结果应在任务日志、artifact metadata 或任务摘要中清晰标注，不得伪装为标准生产结果。

## 3. Pitch 相关配置项

以下配置项用于控制 pitch backend 的选择与 fallback 行为。

### 3.1 `pitch_profile`

用于声明当前 pitch 运行策略所属 profile。建议值：

- `production`
- `development`
- `benchmark`
- 如系统已有单独诊断模式，也可使用 `diagnostic`

建议语义：

- `production`：生产转写任务，RMVPE 必须成功，不允许 fallback。
- `development`：本地开发与集成验证，默认仍建议关闭 fallback，避免把问题掩盖成“可运行”。
- `benchmark`：允许显式启用 fallback，用于对比 backend 结果与性能。
- `diagnostic`：允许显式启用 fallback，用于故障定位与样本分析。

### 3.2 `pitch_allow_backend_fallbacks`

布尔值，控制是否允许从首选 backend 回退到备用 backend。

建议规则：

- `production`：必须为 `false`
- `development`：建议默认 `false`，仅在特定排障场景手动设为 `true`
- `benchmark` / `diagnostic`：可设为 `true`

### 3.3 `pitch_backend_fallbacks`

有序列表，定义允许尝试的备用 backend，例如：

- `crepe`
- `basic-pitch`

要求：

- 仅在 `pitch_allow_backend_fallbacks=true` 时生效。
- 顺序必须稳定、显式配置，不得由代码内部隐式拼接。
- 生产环境可保留该配置项，但在 `production` profile 中不得被执行。
- 若列表为空，表示即使允许 fallback，也没有可尝试的备用后端。

### 3.4 `rmvpe_model_path`

指定 RMVPE 模型文件或模型目录路径。

生产要求：

- 在任务启动前即可验证路径存在性、可读性与版本兼容性。
- 如果路径不存在、权限不足、文件损坏或模型加载失败，必须中止 required pitch stage。
- 不允许因为 `rmvpe_model_path` 无效而在生产环境自动切换到 `CREPE` 或 `basic-pitch`。

运维建议：

- 将 `rmvpe_model_path` 视为生产依赖的一部分，纳入部署检查。
- 在 worker 启动日志与健康检查中报告当前模型路径与加载状态。

## 4. 推荐配置矩阵

下表给出开发、生产、benchmark 三种常见 profile 的建议配置。

| Profile | `pitch_profile` | `pitch_allow_backend_fallbacks` | `pitch_backend_fallbacks` | `rmvpe_model_path` | 运行要求 |
| --- | --- | --- | --- | --- | --- |
| 开发 | `development` | `false`（默认） | `[]` 或显式列出但默认不启用 | 必填，本地可访问 | 优先暴露 RMVPE 问题，不建议默认降级 |
| 生产 | `production` | `false` | 可为空，或保留配置但不得执行 | 必填，必须通过部署校验 | RMVPE 失败即任务失败，不允许 fallback |
| Benchmark | `benchmark` | `true` | `['crepe', 'basic-pitch']`（示例） | 必填，作为首选 backend | 允许对比与诊断，但必须记录 fallback 原因与实际 backend |

补充说明：

- 若系统区分 `diagnostic` 与 `benchmark`，可让二者共享与 benchmark 相同的 fallback 策略。
- 即使在 benchmark 模式，也不应覆盖 production 结果；benchmark 输出应保持独立任务、独立 artifact 或独立标签。

## 5. Artifact 注册与 Metadata 要求

## 5.1 上传即注册 `source_media` artifact

系统在用户上传音频或视频文件后，应立即注册 source artifact，而不是等到后续分析成功后再补写。

建议规则：

- 上传完成并通过基础校验后，立即创建 `source_media` artifact。
- 该 artifact 代表用户原始输入，是整条处理链路的起点。
- 即使后续 ingest、separation、pitch 或 export 失败，`source_media` artifact 也必须保留，用于审计、重试和问题排查。

### 5.2 `source_media` metadata 最低要求

`source_media` artifact 的 metadata 至少应保存以下字段：

- `stage`：建议值为 `upload` 或等价上传阶段标识
- `media_kind`：例如 `audio`、`video`
- `original_filename`：用户原始文件名
- `content_type`：上传时识别或声明的 MIME type
- `probe`：媒体探测结果，如时长、采样率、声道数、编码格式、bitrate、视频轨信息等

建议补充字段：

- `file_size`
- `checksum` 或内容摘要
- `ingest_status`
- `upload_source`
- `created_by`

其中 `probe` 应作为结构化对象保存，而不是只保留一段文本，便于后续诊断与任务判断。

### 5.3 后续 artifact 的 lineage 要求

从 `source_media` 往后的 artifact 必须持续保持 lineage，可追溯到：

- `project`
- `task`
- `score_revision`

具体要求如下：

- 与项目输入相关的 artifact 必须带有 `project` 关联。
- 与一次异步处理执行相关的 artifact 必须带有 `task` 关联。
- 与具体乐谱版本相关的 artifact（如 MusicXML、MIDI、view JSON、corrected F0）必须带有 `score_revision` 关联。
- 不得只把文件写入磁盘而不注册 artifact metadata。
- 不得让导出文件脱离 revision 上下文，否则无法审计“某个导出是由哪个版本生成”。

建议 artifact metadata 统一包含：

- `artifact_type`
- `stage`
- `project_id`
- `task_id`
- `score_revision_id`（如适用）
- `parent_artifact_id` 或输入依赖引用
- `backend` / `model` / `profile`
- `created_at`
- `status`

### 5.4 建议的 artifact lineage 示例

典型链路可表示为：

- `source_media`：上传原始文件
- `canonical_audio`：统一采样率/声道/格式后的标准音频
- `vocals_stem` / `accompaniment_stem`：分离结果
- `f0_track`：RMVPE 输出的 F0 轨迹
- `note_candidates`：由 F0 分段得到的音符候选
- `rhythm_grid`：节拍与小节网格
- `score_revision` 派生导出：`midi`、`musicxml`、`view_json`
- `corrected_f0_track`：由 score revision 引导修正后的 F0
- `rvc_vocal` / `rvc_mix`：后续 RVC 输出

其中每个 artifact 都应能回答三个问题：

- 它属于哪个 project？
- 它由哪次 task 生成？
- 如果与乐谱有关，它对应哪个 score revision？

## 6. Required Stage 失败策略

### 6.1 什么是 required stage

对 MVP 与生产链路而言，以下阶段属于 required stage 的典型代表：

- media ingest
- vocal separation
- RMVPE F0 extraction
- rhythm grid（若该任务声明需要生成可导出 score）
- score build
- export（若任务目标明确要求导出 MIDI / MusicXML）

required stage 的共同特征是：

- 它们的输出是后续关键阶段的前提
- 失败后不能用低质量近似结果替代
- 必须给调用方返回失败态，而不是成功态加警告

### 6.2 required stage 失败时如何报错

当 required stage 失败时，应遵循以下处理方式：

- 将任务状态标记为失败，而非成功或部分成功伪装成功。
- 返回明确的阶段错误信息，例如：失败阶段、backend、依赖名称、异常摘要、是否可重试。
- 将错误写入任务日志 / job event / audit trail，便于后续检索。
- 若已生成上游 artifact，应保留并标注下游阶段未完成。
- 若失败与配置有关，应记录相关配置快照，例如 `pitch_profile`、`rmvpe_model_path`、实际 backend。

建议错误记录最少包含：

- `stage`
- `error_code`
- `error_message`
- `backend`
- `profile`
- `task_id`
- `project_id`
- `artifact_ids`（已生成或相关输入）
- `retryable`
- `timestamp`

### 6.3 required artifact 与 debug artifact 的区别

`required artifact`：

- 是业务链路继续推进或对外导出的必要产物。
- 缺失或生成失败时，任务必须失败。
- 示例：`source_media`、`canonical_audio`、`vocals.wav`、`f0_track.json`、`musicxml`（若导出为任务目标）。

`debug artifact`：

- 是面向开发、诊断、运维、管理后台的辅助产物。
- 它们帮助观察模型行为与失败原因，但不是生产成功的判定条件。
- 示例：F0 曲线图、beat debug 图、separation 质量预览图、backend benchmark 对比图。

处理规则：

- required artifact 失败：任务失败。
- debug artifact 失败：可记录 warning，但不得改变 required stage 的成功判定。
- 不得因为 debug artifact 成功而掩盖 required artifact 失败。
- 也不得因为 debug artifact 失败而错误地把本来成功的 required 流程标记为失败，除非该 debug 输出本身被明确升级为 required。

### 6.4 失败记录与告警建议

运维与后端建议对 required stage 失败建立统一记录机制：

- 为每个 stage 输出结构化事件日志
- 为依赖缺失类错误设置单独错误码，例如模型缺失、权限失败、解码失败、分离失败
- 在任务详情中展示“失败阶段”和“失败原因”，而不是仅显示通用异常
- 对高频失败项建立聚合告警，例如 `rmvpe_model_path` 配置错误、模型加载失败、GPU/CPU 不兼容

## 7. Profile 设计建议

### 7.1 开发 profile

适用于本地联调、接口集成和功能开发。

建议：

- 默认也关闭 backend fallback，尽早暴露 RMVPE 依赖与质量问题。
- 允许开发者临时开启 fallback 做问题比对，但不得作为默认行为写死。
- 保留更多 debug artifacts，方便观察 F0、节拍与分离质量。

### 7.2 生产 profile

适用于面向用户的正式任务执行。

要求：

- 必须使用 RMVPE 作为 required pitch backend。
- 必须关闭 `pitch_allow_backend_fallbacks`。
- 必须校验 `rmvpe_model_path`。
- 必须严格注册 artifact，并保留 project/task/score_revision lineage。
- 必须把 required stage 失败明确定义为任务失败。

### 7.3 Benchmark profile

适用于研究、评估和回归测试。

建议：

- 允许启用 `CREPE` / `basic-pitch` fallback 或并行对比。
- 必须清晰区分“首选 backend 失败后 fallback 结果”与“标准生产结果”。
- 建议增加 benchmark 专用 metadata，例如 backend 耗时、置信度分布、音高偏差统计。

## 8. 运维落地检查清单

上线或排障时，建议至少检查以下项目：

- `pitch_profile` 是否符合当前环境角色
- `pitch_allow_backend_fallbacks` 在生产环境是否为 `false`
- `pitch_backend_fallbacks` 是否仅在 diagnostic / benchmark 中启用
- `rmvpe_model_path` 是否存在、可读、版本正确
- 上传后是否立即创建 `source_media` artifact
- artifact metadata 是否包含 `stage`、`media_kind`、`original_filename`、`content_type`、`probe`
- 后续 artifacts 是否带有 `project_id`、`task_id`、`score_revision_id`（如适用）
- required stage 失败后，任务是否明确失败并记录结构化错误
- debug artifact 是否仅作为辅助诊断，而非成功判定依据

## 9. 总结

SunoScribe 的生产后端必须围绕两条底线运行：

- Pitch required stage 在生产环境中不得静默 fallback，RMVPE 失败必须显式失败。
- Artifact 必须从上传开始建立可追踪 lineage，并在后续阶段持续保留 project、task、score revision 关联。

只要这两条底线被严格执行，系统才能在音频处理质量、审计可追踪性、错误可诊断性之间维持稳定的生产行为。
