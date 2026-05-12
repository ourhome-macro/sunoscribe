# SunoScribe

SunoScribe 是一个面向歌曲音频/视频的自动扒谱项目。当前仓库包含后端、前端原型、音频处理模块、agent workflow 与本地 benchmark 能力。当前已成型的重点是后端音频链路与 typed artifact / revision 边界：

- 上传音频/视频并回写项目媒体路径。
- canonical audio、主唱/伴奏分离、歌词识别、主旋律转写、节奏网格与 ScoreIR 构建。
- 生成 `ScoreRevision`、可追踪 `Artifact`，并从选定 revision 导出 MIDI / MusicXML / score view。
- 提供受约束的 agent workflow：诊断、ScorePatch 提议/应用、导出重生成与 RVC job spec 准备。
- production 语义遵循 required-stage 显式失败，不以 fallback/stub 掩盖结果质量问题。

当前前端已经是 `React + Vite + TypeScript` 的工作台原型，包含 Dashboard、Projects、Upload、Project Detail、Score Workspace、Diagnostics 与 Settings 页面；但数据层仍主要使用 `frontend/src/lib/api/mock-data.ts`，尚未接入真实后端 API，OSMD 渲染区也仍是封装占位。

## 目录

- `backend/`：FastAPI 后端、音频处理编排、数据库模型、测试。
- `frontend/`：React/Vite/TypeScript 工作台原型，当前以 mock API 展示项目、revision、artifact、诊断和轻量编辑流程。
- `docs/`：当前正式架构、运行策略与 benchmark 文档。
- `backend/docs/`：后端运行与模块级历史说明，部分内容已标记为兼容/过渡说明。
- `.cache/`：本地模型/工具缓存，已被 git 忽略。

## 后端快速启动

推荐只保留 `backend/.venv310` 作为本地 Python 环境：

```powershell
cd backend
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
```

启动：

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m uvicorn app.main:app --reload
```

常用检查：

- Swagger：`http://127.0.0.1:8000/docs`
- 基础健康检查：`GET /api/health`
- 音高运行时检查：`GET /api/health/pitch`
- 深度 RMVPE 模型加载检查：`GET /api/health/pitch?deep=true`

## 关键文档

- [正式音频流水线事实源](docs/backend-audio-pipeline.md)
- [正式 production runtime policy](docs/production-runtime-policy.md)
- [Lead-Vocal MVP 执行说明](docs/lead-vocal-mvp-execution.md)
- [后续开发路线](docs/post-mvp-development-roadmap.md)
- [前端当前实现说明](docs/frontend-current-state.md)
- [后端说明](backend/README.md)
- [运行与缓存约定](backend/docs/operations.md)
- [Pitch P1 协议](backend/docs/pitch/P1_PROTOCOL.md)
- [Pitch P1 测试矩阵](backend/docs/pitch/P1_TEST_MATRIX.md)

## 测试

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m compileall -q app tests
.\.venv310\Scripts\python.exe -m pytest -q tests -o cache_dir=.tmp_tests\.pytest_cache
```

测试会使用 mock/fake 组件规避真实模型下载。真实 RMVPE 效果和性能仍需要用实际音频样本加本地模型文件做端到端验证。
