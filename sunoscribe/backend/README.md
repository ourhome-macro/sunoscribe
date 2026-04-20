# SunoScribe Backend

## Pitch 模块（P0）

当前已实现 `app/modules/pitch` 的 P0 能力：

- 音高检测：`basic-pitch`
- BPM 检测：`librosa`
- 调式分析：`librosa chroma + Krumhansl-Schmuckler`
- 输出：原始音符序列 + BPM + 调式（不做小节划分，不做量化）

## 主要文件

- `app/modules/pitch/config.py`
- `app/modules/pitch/exceptions.py`
- `app/modules/pitch/types.py`
- `app/modules/pitch/detector.py`
- `app/modules/pitch/beat_tracker.py`
- `app/modules/pitch/key_analyzer.py`
- `app/modules/pitch/serializer.py`
- `app/modules/pitch/pipeline.py`
- `tests/test_pitch_pipeline.py`

## 测试

当前提供了一个最小单测，使用 mock 避免依赖实际模型下载与真实音频：

- `tests/test_pitch_pipeline.py`

## 后端 API 进展

已实现（可在 `http://localhost:8000/docs` 查看）：

- Auth: `register/login/logout/refresh/forgot-password/reset-password`
- Users: `GET/PUT /api/users/me`、`GET/PUT /api/users/me/settings`
- Projects: `POST/GET /api/projects`、`GET/PUT/DELETE /api/projects/{id}`
- Upload: `POST /api/upload/audio`、`POST /api/upload/video`（格式限制 + 100MB）
- Score: `GET/POST /api/projects/{id}/score`、`PUT /api/scores/{id}`、`GET /api/scores/{id}/export`
- Lyrics: `GET /api/projects/{id}/lyrics`、`PUT /api/lyrics/{id}`
- Tasks: `GET /api/tasks/{id}`

数据模型：

- `users`
- `user_settings`
- `projects`
- `scores`
- `lyrics`
- `token_revocations`（鉴权吊销）

## 数据库迁移（Alembic）

初始化后可用以下命令：

1. 生成迁移（可选）：`alembic revision --autogenerate -m "msg"`
2. 应用迁移：`alembic upgrade head`
3. 回滚一步：`alembic downgrade -1`

当前已包含初始迁移脚本：`alembic/versions/20260420_0001_initial_schema.py`

## 本地启动

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 `.env`（推荐 PostgreSQL + Redis）：
   - `DATABASE_URL=postgresql+psycopg://...`
   - `REDIS_URL=redis://127.0.0.1:6379/0`
   - `UPLOADS_ROOT=data/uploads`
   - `UPLOAD_BACKEND=minio`（或 `local`）
   - `MINIO_ENDPOINT=127.0.0.1:9000`
   - `MINIO_ACCESS_KEY=minioadmin`
   - `MINIO_SECRET_KEY=minioadmin`
   - `MINIO_BUCKET=sunoscribe`
   - `MINIO_SECURE=false`
   - `MINIO_BASE_PATH=uploads`
3. 执行迁移：`alembic upgrade head`
4. 启动：`uvicorn app.main:app --reload`
5. Swagger：`http://localhost:8000/docs`
