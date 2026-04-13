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

## Auth & Users 模块（初始化）

已新增 FastAPI + SQLAlchemy 的认证与用户接口基础实现：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/refresh`
- `GET /api/users/me`
- `PUT /api/users/me`
- `GET /api/users/me/settings`
- `PUT /api/users/me/settings`

核心文件：

- `app/main.py`
- `app/api/auth.py`
- `app/api/users.py`
- `app/services/auth_service.py`
- `app/services/user_service.py`
- `app/utils/security.py`
- `app/utils/dependencies.py`
- `app/models/user.py`
- `app/models/user_settings.py`

## 本地启动

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 `.env` 中 `DATABASE_URL`（推荐 PostgreSQL）
3. 启动：`uvicorn app.main:app --reload`
4. Swagger：`http://localhost:8000/docs`
