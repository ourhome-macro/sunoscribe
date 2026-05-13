# SunoScribe Backend

FastAPI 后端负责账号、项目、上传、异步任务、歌词、谱面生成和导出。

正式的音频流水线与 production runtime 语义以这两份文档为唯一事实源：

- `../docs/backend-audio-pipeline.md`
- `../docs/production-runtime-policy.md`

本文件只保留当前后端的运行入口、API 概览和与实现对齐的简要说明；不再单独定义 fallback、stub 或 legacy export 语义。

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
SECRET_KEY=replace-with-a-stable-32-plus-char-secret
API_KEYS_ENCRYPTION_KEY=replace-with-a-stable-32-plus-char-secret
UPLOADS_ROOT=data/uploads
UPLOAD_BACKEND=local
MAX_MEDIA_DURATION_SEC=600
TASK_STALE_AFTER_MINUTES=120

PASSWORD_RESET_BASE_URL=https://example.com/reset-password
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_USE_TLS=true

PITCH_BACKEND=rmvpe
PITCH_PROFILE=production
PITCH_ALLOW_BACKEND_FALLBACKS=false
PITCH_BACKEND_FALLBACKS=
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
- Agent workflows：`POST /api/score-revisions/{revision_id}/agent/diagnose`、`POST /api/score-revisions/{revision_id}/agent/patch/propose`、`POST /api/score-revisions/{revision_id}/agent/patch/apply`、`POST /api/score-revisions/{revision_id}/agent/rvc/prepare`、`POST /api/score-revisions/{revision_id}/exports/regenerate`
- Lyrics：`GET /api/projects/{project_id}/lyrics`、`PUT /api/lyrics/{lyrics_id}`
- Tasks：`GET /api/tasks/{task_id}`、`POST /api/tasks/{task_id}/retry`
- Health：`GET /api/health`、`GET /api/health/pitch`

## 音频链路

`POST /api/upload/audio` 或 `POST /api/upload/video` 会保存媒体文件，并把路径写入 `projects.audio_path`。谱面生成任务随后调用 `AudioAnalysisService`：

1. 复制原始输入到项目 workspace。
2. 通过 `MediaIngestService` 生成 canonical `preprocess/source.wav`。
3. 执行主唱/伴奏分离，产出 `vocals.wav`、`accompaniment.wav` 等 stems。
4. 基于主唱音频做旋律转写、节奏网格提取、ScoreIR 构建与歌词对齐。
5. 生成 `ScoreRevision` 与 `Artifact`，并从选定 revision 派生 MIDI / MusicXML / score view 导出。

当前还包含受约束 agent workflow：agent 只能读取 `ScoreRevision` 与 typed artifacts，诊断或提出小型 `ScorePatch`，patch 必须经 validator 后才会创建新的 user revision；RVC prepare 目前准备 job spec，不直接调用外部 RVC。

当前 production 语义：

- required stage 失败必须显式失败；
- production 禁止 pitch backend fallback 与 audio stub fallback；
- 导出必须 revision-scoped；
- `ScoreRevision` / `ScoreIR` 是导出和修订链的中心边界。

详细说明见：

- `../docs/backend-audio-pipeline.md`
- `../docs/production-runtime-policy.md`

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
