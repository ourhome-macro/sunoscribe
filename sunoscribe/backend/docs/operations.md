# 运行与缓存约定

## Python 环境

本仓库后端统一使用 Python 3.10，本地只保留一个虚拟环境：

- 标准环境：`backend/.venv310`
- 可清理目录：`backend/.venv`、`backend/.pytest_cache`、`backend/.tmp`、`backend/.tmp_tests`
- 依赖入口：`backend/requirements.txt`

初始化：

```powershell
cd backend
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
```

清理旧环境和缓存：

```powershell
cd backend
Remove-Item -Recurse -Force .venv, .pytest_cache, .tmp, .tmp_tests -ErrorAction SilentlyContinue
```

## RMVPE 与 pitch 配置

默认配置：

```env
PITCH_BACKEND=rmvpe
PITCH_BACKEND_FALLBACKS=crepe,basic-pitch
PITCH_CACHE_DIR=~/.cache/sunoscribe/pitch
RMVPE_MODEL_PATH=
```

说明：

- `PITCH_BACKEND=rmvpe` 是默认音高检测模型。
- `PITCH_BACKEND_FALLBACKS` 是逗号分隔列表，RMVPE runtime 或模型不可用时依次尝试。
- `PITCH_CACHE_DIR` 是 SunoScribe 的 pitch 缓存目录。
- `RMVPE_MODEL_PATH` 指向本地 RMVPE 模型文件；如果 runtime 能自行管理模型，可以留空。
- 模型文件和本地缓存不提交到 git，根目录 `.cache/`、常见模型扩展名和 venv 已被 `.gitignore` 忽略。

## 健康检查

服务启动后可用：

```text
GET /api/health
GET /api/health/pitch
GET /api/health/pitch?deep=true
```

`/api/health/pitch` 默认只做轻量检查：

- 当前 pitch backend。
- fallback backend 列表。
- `PITCH_CACHE_DIR` 是否存在、是否可写。
- `RMVPE_MODEL_PATH` 是否存在。
- RMVPE runtime 模块是否可 import。

`deep=true` 会尝试构造 RMVPE 模型对象，可能触发更重的模型加载，不建议作为高频 liveness probe。

状态含义：

- `ok`：缓存和默认 backend 检查通过。
- `degraded`：默认 RMVPE 不完整，但存在 fallback，服务可降级运行。
- `fail`：默认 backend 不可用且没有 fallback。

## 测试缓存

推荐把 pytest 缓存放到可删除目录：

```powershell
.\.venv310\Scripts\python.exe -m pytest -q tests -o cache_dir=.tmp_tests\.pytest_cache
```

测试完成后可以删除 `backend/.tmp_tests`，不影响源码。
