# Transcription Job Runner MVP 壳（2026-05-15）

## 目标

在不改 MIR 算法、不改 ScoreIR lineage 的前提下，补齐可上线的异步 transcription job/status/failure 壳，只覆盖 `lead_vocal` MVP 路径。

## 本次落地

- 复用现有 `tasks` 表作为最小 job 模型，不引入新的 pipeline fallback。
- 将 job 语义收敛为 `task_type="transcription"`，输入显式写入 `transcription_target="lead_vocal"`。
- 支持状态：
  - `queued`
  - `running`
  - `succeeded`
  - `failed`
  - `cancelled`
- 失败原因持久化到：
  - 数据库 `tasks.error_message`
  - 工作区 manifest `data/projects/<project_id>/jobs/<task_id>/manifest.json`
- 后台 worker 仍调用既有 lead-vocal 主线：
  - `generate_or_regenerate_score(...)`
  - `create_machine_score_revision(...)`
  - `render_export_service.ensure_core_exports(...)`
- 通过 `task_id` 将产物和 revision 反向挂回 job，便于查询。

## 新增/补齐接口

- `POST /api/projects/{project_id}/score`
  - 语义：创建 `lead_vocal` transcription job。
- `GET /api/tasks/{task_id}`
  - 语义：查询 job 状态。
- `GET /api/tasks/{task_id}/outputs`
  - 语义：查询 job 对应的 score/revision/artifacts。
- `POST /api/tasks/{task_id}/retry`
  - 语义：失败 job 重新入队。
- `POST /api/tasks/{task_id}/cancel`
  - 语义：取消 `queued/running` job。

## timeout / cleanup 基本结构

### timeout

- 增加配置：`task_timeout_seconds`
- 当前实现是软超时壳：
  - worker 启动恢复时，超过 `task_stale_after_minutes` 的 `running` 任务直接转 `failed`
  - 失败原因固定写入 `task_timeout_exceeded`
- 这是上线 MVP 的最小可靠实现，先保证：
  - 有明确超时语义
  - 有持久化 failure reason
  - 不把超时任务静默回队成“假成功”

### cleanup

- 新增 `TaskManifestService.cleanup_runtime(...)`
- 当前只清理每个 job 的运行时目录：
  - `data/projects/<project_id>/jobs/<task_id>/runtime`
- 不碰 typed artifacts / score revisions / exports
- 原因：这些输出属于可追踪 lineage，不允许为了 cleanup 破坏审计链

## manifest 结构

路径：

`data/projects/<project_id>/jobs/<task_id>/manifest.json`

关键字段：

- `task_id`
- `project_id`
- `task_type`
- `transcription_target`
- `status`
- `progress`
- `failure_reason`
- `input_payload`
- `result_payload`
- `outputs`
- `timeout_seconds`
- `queued_at`
- `started_at`
- `finished_at`
- `cleanup`

## 边界说明

- 当前只支持 `lead_vocal`，传入其他 `transcription_target` 会显式失败。
- `cancelled` 目前是 job 级状态，不是 project 级状态。
- 当前 timeout 不是强杀正在执行的 MIR 进程，而是 MVP 级软超时/恢复壳。
- 没有引入任何新的 MIR fallback，也没有改变 ScoreIR / revision / artifact 的 lineage。
