这里是根据 PRD 文档专门为后端开发人员 **yfp** 提取和整理的专属需求文档。
按照团队分工，yfp 全面负责**后端 CRUD、用户系统、数据库设计以及 API 接口**，不涉及前端 UI 和底层 AI 算法（AI 模块由成员1负责，后端只需预留对接入口）。
---
# SunoScribe - 后端开发 PRD (yfp 专属)
## 一、技术栈要求
*   **Web 框架**：FastAPI
*   **ORM**：SQLAlchemy
*   **数据库**：PostgreSQL
*   **认证方案**：JWT (使用 `passlib` + `python-jose`，加密算法 `bcrypt`)
*   **数据校验**：Pydantic
*   **数据库迁移**：Alembic
## 二、数据库模型设计
请严格按以下结构建立 5 张核心表，主键统一使用 UUID，必须包含 `created_at` 和 `updated_at` 字段。
1.  **User (用户表)**：id, username(唯一), email(唯一), password_hash, avatar_url, created_at, updated_at
2.  **Project (项目表)**：id, user_id(外键), name, source_type(枚举: upload/bilibili), source_url, audio_path, status(枚举: pending/processing/completed/failed), progress(0-100), created_at, updated_at
3.  **Score (谱子表)**：id, project_id(外键), score_type(枚举: jianpu/staff), key(调式), vocal_range(音域), recommended_voice(推荐声部), emotion(情感), score_data(JSON), created_at
4.  **Lyrics (歌词表)**：id, project_id(外键), text, timeline(JSON), created_at
5.  **UserSettings (用户设置表)**：id, user_id(外键), default_score_type, default_key, api_keys(JSON), created_at
## 三、API 接口开发清单
### 3.1 认证模块
*   `POST /api/auth/register`：用户注册（密码需 bcrypt 加密存储）
*   `POST /api/auth/login`：用户登录（返回 access_token 有效期30分钟，refresh_token 有效期7天）
*   `POST /api/auth/logout`：用户登出
*   `POST /api/auth/refresh`：刷新 Token
*   `POST /api/auth/forgot-password`：忘记密码 (P1)
*   `POST /api/auth/reset-password`：重置密码 (P1)
### 3.2 用户模块
*   `GET /api/users/me`：获取当前用户信息
*   `PUT /api/users/me`：更新用户信息（昵称、头像）
*   `GET /api/users/me/settings`：获取用户设置
*   `PUT /api/users/me/settings`：更新用户设置（默认谱子类型、API Key等）
### 3.3 项目模块
*   `POST /api/projects`：创建项目
*   `GET /api/projects`：获取项目列表（**必须支持分页**）
*   `GET /api/projects/{id}`：获取项目详情
*   `PUT /api/projects/{id}`：更新项目（如重命名，P1）
*   `DELETE /api/projects/{id}`：删除项目及相关联数据
### 3.4 文件上传模块
*   `POST /api/upload/audio`：上传音频文件
*   `POST /api/upload/video`：上传视频文件
*   **限制要求**：
    *   音频格式限：`mp3, wav, flac, aac, ogg, m4a`
    *   视频格式限：`mp4, mkv, avi, mov, webm`
    *   大小限制：`100MB`
    *   存储路径规范：`/app/data/uploads/{user_id}/{project_id}/`
### 3.5 谱子与歌词模块
*   `GET /api/projects/{id}/score`：获取项目的谱子数据
*   `POST /api/projects/{id}/score`：触发/重新生成谱子（此处需调用成员1的 AI 接口）
*   `PUT /api/scores/{id}`：更新谱子（如移调、简化操作）
*   `GET /api/scores/{id}/export`：导出谱子（支持 PDF/MusicXML/MIDI 格式返回）
*   `GET /api/projects/{id}/lyrics`：获取歌词及时间轴
*   `PUT /api/lyrics/{id}`：编辑修改歌词
### 3.6 任务状态模块
*   `GET /api/tasks/{id}`：获取 AI 处理任务的状态和进度百分比（供前端轮询用）
## 四、核心业务逻辑规范
### 4.1 统一响应格式
所有接口必须严格遵守以下 JSON 格式：
```typescript
// 成功
{ "success": true, "data": {...}, "message": "操作成功" }
// 失败
{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "用户名已存在", "details": {} } }
// 分页列表
{ "success": true, "data": [...], "pagination": { "page": 1, "page_size": 10, "total": 100, "total_pages": 10 } }
```
### 4.2 统一错误码
需要定义全局异常处理器，包含以下错误码：
`VALIDATION_ERROR`, `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR`, `NOT_FOUND`, `INTERNAL_ERROR`, `FILE_TOO_LARGE`, `UNSUPPORTED_FORMAT`
### 4.3 认证拦截规范
*   请求头格式：`Authorization: Bearer <access_token>`
*   除了 `/api/auth/register` 和 `/api/auth/login` 外，其他所有接口均需校验 Token。
### 4.4 核心业务流：项目创建与处理
1. 接收前端上传文件，校验格式和大小，存储到指定目录，返回 `file_path`。
2. 接收前端带着 `file_path` 的创建项目请求，写入 Project 表，状态设为 `pending`。
3. 前端请求生成谱子时，将任务交给 AI 模块，Project 状态改为 `processing`。
4. 提供 Task 接口供前端查询进度，AI 处理完成后，状态改为 `completed`，结果写入 Score 和 Lyrics 表。
## 五、项目结构与交付物要求
后端代码必须按照以下目录结构组织：
```text
backend/
├── app/
│   ├── main.py          # FastAPI入口
│   ├── config.py        # 配置管理 (读取.env)
│   ├── database.py      # 数据库连接池
│   ├── models/          # SQLAlchemy模型 (5个表)
│   ├── schemas/         # Pydantic请求/响应模型
│   ├── api/             # 路由层 (auth, users, projects, upload, scores)
│   ├── services/        # 业务逻辑层
│   └── utils/           # 工具类 (security.py处理加密和JWT, dependencies.py处理依赖注入)
├── alembic/             # 数据库迁移脚本
├── tests/               # 接口测试用例
├── requirements.txt
└── Dockerfile
```
## 六、开发排期 (的里程碑)
*   **Phase 1 (Week 1-2)**：完成项目初始化、数据库连接、5张表 Model 建立、Alembic迁移配置；完成注册、登录、Token刷新 API。
*   **Phase 2 (Week 3-4)**：完成项目 CRUD API；完成音频/视频文件上传 API（含限制和存储逻辑）。
*   **Phase 3 (Week 5-6)**：完成谱子数据 CRUD API；完成导出 API (PDF/MIDI等)；对接成员1的 AI 处理状态，完善 Task 状态查询接口。
*   **Phase 4 (Week 7-8)**：完成用户设置 API；全面优化错误处理和边界校验；配合前端 wxl 进行全量接口联调。
## 七、协作与规范要求
1.  **接口文档**：由于使用 FastAPI，必须确保自带的 Swagger 文档 (`http://localhost:8000/docs`) 完善可用，这是前端 wxl 对接的唯一依据。
2.  **代码风格**：严格遵守 PEP 8，提交前必须使用 Black 格式化代码。