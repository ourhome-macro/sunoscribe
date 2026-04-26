# SunoScribe

SunoScribe 是一个面向歌曲音频/视频的自动扒谱项目。当前仓库包含后端、前端和音频处理模块；本轮重点落在后端音频链路：

- 上传音频/视频并回写项目媒体路径。
- 音频预处理、可选人声分离、歌词识别、音高检测、节拍/调式分析。
- 生成 Score IR、歌词-音符对齐结果、MIDI/MusicXML/PDF 导出。
- 默认音高检测 backend 为 RMVPE；缺少 RMVPE runtime 或模型时按配置回退到 CREPE/basic-pitch。

## 目录

- `backend/`：FastAPI 后端、音频处理编排、数据库模型、测试。
- `frontend/`：前端工程，本轮未处理。
- `docs/`：早期模块设计文档。
- `backend/docs/`：后端运行、音频链路和 pitch 协议文档。
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

- [后端说明](backend/README.md)
- [运行与缓存约定](backend/docs/operations.md)
- [音频处理链路](backend/docs/audio_pipeline.md)
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
