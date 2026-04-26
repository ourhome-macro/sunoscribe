# SunoScribe Backend

FastAPI 后端负责账号、项目、上传、异步任务、歌词、谱面生成和导出。音频处理主链路已经接入 `AudioAnalysisService`，默认音高 backend 为 RMVPE，并配置了 CREPE/basic-pitch fallback。

## 本地环境

标准虚拟环境只保留 `backend/.venv310`：

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
```

`.venv`、`.tmp`、`.tmp_tests`、`.pytest_cache` 都属于可清理本地目录，不应提交。

## 配置

常用 `.env`：

```env
DATABASE_URL=postgresql+psycopg://localhost:5432/sunoscribe
REDIS_URL=redis://127.0.0.1:6379/0
UPLOADS_ROOT=data/uploads
UPLOAD_BACKEND=local
MAX_MEDIA_DURATION_SEC=600

PITCH_BACKEND=rmvpe
PITCH_BACKEND_FALLBACKS=crepe,basic-pitch
PITCH_CACHE_DIR=~/.cache/sunoscribe/pitch
RMVPE_MODEL_PATH=
```

MinIO 上传可选配置：

```env
UPLOAD_BACKEND=minio
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=sunoscribe
MINIO_SECURE=false
MINIO_BASE_PATH=uploads
```

## 启动

```powershell
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m uvicorn app.main:app --reload
```

- Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /api/health`
- Pitch/RMVPE 检查：`GET /api/health/pitch`
- 深度模型加载检查：`GET /api/health/pitch?deep=true`

## API 概览

- Auth：`/api/auth/register`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/refresh`
- Users：`GET/PUT /api/users/me`、`GET/PUT /api/users/me/settings`
- Projects：`POST/GET /api/projects`、`GET/PUT/DELETE /api/projects/{project_id}`
- Upload：`POST /api/upload/audio`、`POST /api/upload/video`
- Scores：`GET/POST /api/projects/{project_id}/score`、`PUT /api/scores/{score_id}`、`GET /api/scores/{score_id}/export`
- Lyrics：`GET /api/projects/{project_id}/lyrics`、`PUT /api/lyrics/{lyrics_id}`
- Tasks：`GET /api/tasks/{task_id}`、`POST /api/tasks/{task_id}/retry`
- Health：`GET /api/health`、`GET /api/health/pitch`

## 音频链路

`POST /api/upload/audio` 或 `POST /api/upload/video` 会保存媒体文件，并把路径写入 `projects.audio_path`。谱面生成任务随后调用 `AudioAnalysisService`：

1. 复制原始输入到项目 workspace。
2. 可选人声分离，得到 vocals/accompaniment/stems。
3. 用 vocals 或归一化 fallback 音频做歌词识别。
4. 用 RMVPE 默认检测主旋律音高；缺模型或 runtime 时回退。
5. 生成 Analysis IR、Score IR、歌词对齐和 MIDI/MusicXML/PDF 导出数据。

更详细说明见 [audio_pipeline.md](docs/audio_pipeline.md)。

## 测试

```powershell
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m compileall -q app tests
.\.venv310\Scripts\python.exe -m pytest -q tests -o cache_dir=.tmp_tests\.pytest_cache
```

关键测试文件：

- `tests/test_pitch_runtime_health.py`
- `tests/test_audio_flow_integration.py`
- `tests/test_audio_analysis_service.py`
- `tests/test_score_generation_service.py`
- `tests/test_score_export_service.py`
- `tests/test_upload_api.py`

## 数据库迁移

```powershell
.\.venv310\Scripts\alembic.exe upgrade head
```

需要生成迁移时：

```powershell
.\.venv310\Scripts\alembic.exe revision --autogenerate -m "message"
```
