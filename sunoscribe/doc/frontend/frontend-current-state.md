# SunoScribe 前端当前实现说明

本文记录当前 `frontend/` 目录与实际代码对齐的状态，避免继续把前端描述成空占位，也避免误认为它已经接入生产后端。

## 当前定位

前端当前是一个 `React + Vite + TypeScript` 工作台原型，用于验证 SunoScribe 的产品信息架构和 typed artifact / revision / agent workflow 交互方式。

它已经可以本地启动、构建和展示主要页面，但数据层仍主要是 mock：

- mock 数据入口：`frontend/src/lib/api/mock-data.ts`
- mock API client：`frontend/src/lib/api/client.ts`
- 路由入口：`frontend/src/app/router.tsx`

因此，当前前端适合用来评审界面结构、状态展示、ScoreRevision 工作台和 agent patch 交互雏形；不应把它视为已经连接真实后端的生产 UI。

## 已实现页面

当前路由覆盖：

- Dashboard：展示项目与整体状态概览。
- Projects：展示项目列表。
- Upload：模拟创建项目与上传媒体，页面文案遵循“上传只创建 source media，后续阶段从 typed artifacts 继续”。
- Project Detail：展示项目信息、当前分析状态、revision 列表与 artifact 摘要。
- Score Workspace：围绕某个 revision 展示 OSMD 区域占位、waveform 占位、诊断、uncertain notes、note detail 和 patch 操作。
- Diagnostics：展示 stage progress、quality metrics、artifact 可用性与 required-stage failure 信息。
- Settings：展示运行策略和 workspace 相关配置占位。

## 已实现组件边界

当前组件已经围绕后端目标模型组织：

- `ArtifactSummary` 只展示公开 artifact metadata，不展示后端存储路径。
- `RevisionList` 展示 revision、export status 与进入 Score Workspace 的入口。
- `StageProgress` 展示 media ingest、stem、F0、quantization、ScoreIR、exports 等阶段状态。
- `UncertainNotesPanel`、`NoteDetailSheet` 与 `DiffSummary` 表达 agent diagnose 和 ScorePatch 的 UI 形态。
- `OsmdPlaceholder` 明确把 MusicXML 视为由选定 `ScoreRevision` 派生的展示 artifact，而不是事实源。

## 尚未完成

- 真实 API client 尚未替换 mock client；当前没有统一鉴权、错误处理、分页、文件上传进度和任务轮询实现。
- Upload 页面当前模拟 `createProject`，尚未串起真实 `POST /api/projects`、`POST /api/upload/audio|video` 与 `POST /api/projects/{project_id}/score`。
- OSMD 尚未安装/接入，MusicXML artifact 下载、解析和渲染仍是占位。
- MIDI 播放控件尚未接入真实 MIDI artifact。
- ScorePatch UI 仍是轻量原型，尚未完整覆盖后端 patch schema 的所有操作与 validator 错误展示。
- Diagnostics 页面使用 mock summary，不读取真实 debug artifact 文件内容。

## 对接后端时的约束

后续接真实 API 时必须保持这些产品边界：

- 前端不要把 MIDI 或 MusicXML 当成可编辑事实源；编辑入口应围绕 `ScoreRevision` 与受控 `ScorePatch`。
- 前端不要绕过 artifact metadata 直接拼后端文件路径；下载和展示应通过公开 API 或受控 artifact endpoint。
- required stage failure 应在任务状态和诊断页明确展示，不能把失败项目渲染成“部分成功”。
- OSMD 只负责展示选定 revision 派生的 MusicXML；修订后必须从新 revision 重新生成导出。

## 本地命令

```powershell
cd frontend
npm install
npm run dev
npm run build
npm run lint
```

当前 `npm run build` 会执行 `tsc -b && vite build`。如果后续引入真实 API 类型，应优先从后端 response schema 对齐类型定义，而不是让 mock shape 漂移。
