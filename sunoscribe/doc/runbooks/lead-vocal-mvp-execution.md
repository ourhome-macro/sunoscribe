# Lead-Vocal MVP 执行说明

本文记录当前第一阶段应该如何执行，以及该阶段的输出边界。这里的 MVP 指 lead-vocal score，不是完整钢琴编配或多轨 MIDI 还原。

## 阶段目标

给定一段音频或视频，系统应产出：

- `source.wav`：canonical audio。
- `vocals.wav`：主唱 stem。
- `accompaniment.wav`：伴奏 stem，用于后续同步播放、RVC mix 或调试。
- `f0_track.json`：RMVPE 主唱 F0 轨迹。
- `note_candidates.json`：旋律候选。
- `rhythm_grid.json`：节奏网格。
- `ScoreRevision`：可追踪的 lead-vocal score revision。
- `score.mid`、`score.musicxml`、`score_view.json`：从指定 revision 派生的导出 artifact。

MIDI 的语义是：人声唱的时候有主旋律音符；没人唱的前奏、间奏、尾奏保留时间轴为空拍/休止，不生成伴奏音符。

## 不属于本阶段的目标

- 不生成完整伴奏 MIDI。
- 不生成钢琴演奏版或钢琴伴奏谱。
- 不从伴奏中推断所有乐器声部。
- 不把 `accompaniment.wav` 编码进 MIDI；伴奏应作为音频 stem 保留。
- 不用低质量 fallback 伪造成 production success。

如果需要“前奏也能弹、间奏也能弹、人声进来后右手弹旋律左手保留伴奏”的输出，应作为后续 piano arrangement 能力，而不是污染 lead-vocal MVP。

## 运行前提

后端需要完成：

- Python 3.10 虚拟环境与 `requirements.txt` 依赖安装。
- 数据库可连接，并已执行 Alembic migration。
- `.env` 中配置稳定的 `SECRET_KEY`、`API_KEYS_ENCRYPTION_KEY`、上传目录和数据库连接。
- production profile 下配置可用的 RMVPE runtime 和 `RMVPE_MODEL_PATH`。
- vocal separation 依赖可用；如果分离失败，本阶段应失败。

关键配置示例：

```env
PITCH_BACKEND=rmvpe
PITCH_PROFILE=production
PITCH_ALLOW_BACKEND_FALLBACKS=false
PITCH_BACKEND_FALLBACKS=
PITCH_CACHE_DIR=~/.cache/sunoscribe/pitch
RMVPE_MODEL_PATH=path-to-rmvpe-model
```

## 后端启动

```powershell
cd backend
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
.\.venv310\Scripts\alembic.exe upgrade head
$env:PYTHONPATH='.'
.\.venv310\Scripts\python.exe -m uvicorn app.main:app --reload
```

启动后先检查：

```powershell
curl.exe http://127.0.0.1:8000/api/health
curl.exe "http://127.0.0.1:8000/api/health/pitch?deep=true"
```

如果 deep pitch health 失败，不要继续跑 production 任务；应先修 RMVPE runtime 或模型路径。

## API 执行流程

以下流程可用 Swagger 或命令行执行。前端当前仍主要是 mock 工作台，不建议用它作为第一阶段真实验证入口。

### 1. 注册并登录

```powershell
$base = "http://127.0.0.1:8000/api"

curl.exe -X POST "$base/auth/register" `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"demo_user\",\"email\":\"demo@example.com\",\"password\":\"demo123456\"}"

$login = curl.exe -X POST "$base/auth/login" `
  -H "Content-Type: application/json" `
  -d "{\"username_or_email\":\"demo_user\",\"password\":\"demo123456\"}" | ConvertFrom-Json

$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### 2. 创建项目

```powershell
$project = Invoke-RestMethod -Method Post -Uri "$base/projects" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"name":"lead vocal test","source_type":"upload"}'

$projectId = $project.data.id
```

### 3. 上传音频或视频

音频：

```powershell
$audioPath = "E:\path\to\song.wav"

$upload = curl.exe -X POST "$base/upload/audio" `
  -H "Authorization: Bearer $token" `
  -F "project_id=$projectId" `
  -F "file=@$audioPath" | ConvertFrom-Json
```

视频：

```powershell
$videoPath = "E:\path\to\song.mp4"

$upload = curl.exe -X POST "$base/upload/video" `
  -H "Authorization: Bearer $token" `
  -F "project_id=$projectId" `
  -F "file=@$videoPath" | ConvertFrom-Json
```

上传成功后，项目会写入 `projects.audio_path`，并注册 `source_media` artifact。

### 4. 触发谱面生成任务

```powershell
$task = Invoke-RestMethod -Method Post -Uri "$base/projects/$projectId/score" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"score_type":"staff","key":"C Major"}'

$taskId = $task.data.task_id
```

### 5. 轮询任务

```powershell
do {
  Start-Sleep -Seconds 3
  $taskStatus = Invoke-RestMethod -Method Get -Uri "$base/tasks/$taskId" -Headers $headers
  $taskStatus.data | Format-List
} while ($taskStatus.data.status -in @("queued","running","retrying"))
```

成功状态应为 `succeeded`。失败时优先查看：

```powershell
$taskStatus.data.error_message
```

常见失败原因：

- RMVPE 模型路径不存在或 runtime 不可加载。
- vocal separation 未产出 `vocals.wav`。
- 输入文件无法转换为 canonical audio。
- 音频中没有可用主唱或没有有效 lead-vocal notes。

### 6. 获取当前 ScoreRevision

```powershell
$score = Invoke-RestMethod -Method Get -Uri "$base/projects/$projectId/score" -Headers $headers

$scoreId = $score.data.id
$revisionId = $score.data.current_revision_id
$score.data.current_revision
```

导出必须绑定到明确 revision。不要把项目 workspace 中的临时文件当作产品下载事实源。

### 7. 下载 MIDI / MusicXML / score view

MIDI：

```powershell
curl.exe -L -o lead_vocal.mid `
  -H "Authorization: Bearer $token" `
  "$base/scores/$scoreId/export?format=midi&revision_id=$revisionId"
```

MusicXML：

```powershell
curl.exe -L -o lead_vocal.musicxml `
  -H "Authorization: Bearer $token" `
  "$base/scores/$scoreId/export?format=musicxml&revision_id=$revisionId"
```

Score view：

```powershell
curl.exe -L -o score_view.json `
  -H "Authorization: Bearer $token" `
  "$base/scores/$scoreId/export?format=score_view&revision_id=$revisionId"
```

## 成功后的文件检查

典型工作区路径：

```text
backend/data/projects/<project_id>/preprocess/source.wav
backend/data/projects/<project_id>/separation/vocals.wav
backend/data/projects/<project_id>/separation/accompaniment.wav
backend/data/projects/<project_id>/pitch/f0_track.json
backend/data/projects/<project_id>/pitch/note_candidates.json
backend/data/projects/<project_id>/pitch/rhythm_grid.json
backend/data/projects/<project_id>/score/score_ir.json
backend/data/projects/<project_id>/revisions/<revision_id>/exports/score.mid
backend/data/projects/<project_id>/revisions/<revision_id>/exports/score.musicxml
backend/data/projects/<project_id>/revisions/<revision_id>/exports/score_view.json
```

`backend/data/projects/<project_id>/exports/final_score.mid` 是 runtime/benchmark 兼容落点，不应优先作为产品下载事实源。

## 验收标准

- `source_media`、canonical audio、stems、F0、note candidates、rhythm grid、ScoreRevision 与 exports 都可追踪。
- `score.mid` 只包含 lead-vocal melody，不包含完整伴奏编配。
- 前奏、间奏、尾奏在 lead-vocal MIDI 中保留时间位置，但没有凭空生成伴奏音符。
- `score.musicxml` 可用于前端 OSMD 渲染。
- 如果 required stage 失败，任务状态为失败，并返回清晰 `error_message`。

## 与钢琴编配的边界

如果产品目标变成“钢琴弹奏版”，需要新增 arrangement 层，而不是修改 lead-vocal MVP 的语义：

```text
lead-vocal ScoreRevision
  + accompaniment.wav
  + rhythm_grid
  + chord/harmony analysis
  + structure labels
  -> PianoArrangementIR
  -> PianoArrangementRevision
  -> piano MIDI / MusicXML
```

这个后续能力应允许前奏、间奏、尾奏生成可弹奏钢琴伴奏；但它不是当前第一阶段的验收范围。
