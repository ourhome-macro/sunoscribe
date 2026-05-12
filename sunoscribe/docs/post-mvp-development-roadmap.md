# Post-MVP Development Roadmap

本文记录 lead-vocal MVP 之后的开发顺序。核心原则是先把主链路跑稳，再接真实前端和编辑闭环，最后再扩展 RVC 与钢琴编配；不要把 full piano arrangement 混入第一阶段。

## 当前边界

当前第一阶段是 lead-vocal MVP：

```text
audio/video
  -> canonical audio
  -> vocals/accompaniment stems
  -> RMVPE F0
  -> note candidates
  -> rhythm grid
  -> ScoreRevision
  -> MIDI / MusicXML / score view
```

它的 MIDI 是主唱旋律 MIDI，不是完整伴奏 MIDI。`accompaniment.wav` 是音频 stem，应作为伴奏音频保留，不应被误认为 MIDI 伴奏轨。

## 推荐开发顺序

### 1. 跑稳 Lead-Vocal MVP

目标：对真实音频/视频稳定产出 `ScoreRevision`、`score.mid`、`score.musicxml` 和 `score_view.json`。

重点：

- production 下 RMVPE 失败必须失败。
- vocal separation 未产出 `vocals.wav` 必须失败。
- exports 必须从指定 `ScoreRevision` 派生。
- 前奏、间奏、尾奏在 lead-vocal MIDI 中保留时间轴，但不生成伴奏音符。
- runtime `exports/final_score.mid` 只能作为兼容/benchmark 落点，产品下载以 revision exports 为准。

优先检查文件：

- `backend/app/services/audio_analysis_service.py`
- `backend/app/services/score_revision_service.py`
- `backend/app/services/render_export_service.py`
- `backend/app/services/pitch_runtime.py`

### 2. 补 Artifact 查询与下载 API

前端真实闭环需要公开、受控的 artifact 访问方式，而不是直接拼 workspace 路径。

建议新增：

- `GET /api/projects/{project_id}/artifacts`
- `GET /api/artifacts/{artifact_id}`
- `GET /api/artifacts/{artifact_id}/download`

要求：

- 所有查询必须校验当前用户是否拥有项目。
- 下载接口只允许读取 artifact metadata 指向的受控路径。
- 不暴露后端任意文件路径。
- response 中可返回公开字段：`id`、`artifact_type`、`status`、`filename`、`mime_type`、`file_size_bytes`、`checksum`、`created_at`、`score_revision_id`、`task_id`。

### 3. 把前端 mock client 替换成真实 API client

当前 `frontend/` 是工作台原型，数据层仍主要来自 `frontend/src/lib/api/mock-data.ts`。

下一步应接入：

- 登录 / token 保存 / refresh。
- 创建项目。
- 上传音频或视频。
- 触发 score generation task。
- 轮询 task status。
- 获取 score、current revision、revision list。
- 列出 artifacts。
- 下载 MusicXML 并交给 OSMD。
- 下载 MIDI 并接播放控件。

前端边界：

- 不把 MIDI 或 MusicXML 当成编辑事实源。
- 编辑仍应围绕 `ScoreRevision` 和受控 `ScorePatch`。
- required stage failure 必须明确展示，不能渲染成“部分成功”。

### 4. 接 OSMD 与 MIDI 播放

目标：把第一阶段输出变成可视、可听、可下载的结果。

步骤：

- 安装并封装 OSMD，替换 `OsmdPlaceholder`。
- 从选定 `ScoreRevision` 的 `musicxml` artifact 加载 MusicXML。
- 对 MusicXML 加载失败、export 缺失、task 失败做清晰状态展示。
- 接入 MIDI 播放控件，播放 lead-vocal melody MIDI。
- 后续再考虑和 `accompaniment.wav` 同步播放。

### 5. 完成 ScorePatch 编辑闭环

目标：用户或 agent 可以对低置信音符做小型、可审计修改，生成新的 user revision。

后端已有基础入口：

- diagnose transcription。
- propose score patch。
- apply score patch。
- regenerate exports。

下一步重点：

- 前端展示 uncertain notes、reason codes、note detail。
- 前端发起 `replace_note_pitch`、`adjust_note_duration`、`delete_note`、`merge_notes`、`bind_lyric_token` 等操作。
- 后端 validator 返回的错误要在 UI 中可读展示。
- apply 后创建新的 user revision，不覆盖 machine revision。
- 新 revision 自动或手动 regenerate exports。

### 6. 接入 RVC 外部服务

RVC 不应嵌入后端 runtime。正确路线是外部服务集成。

推荐链路：

```text
vocals.wav
  + original F0Track
  + selected ScoreRevision
  + voice model / transpose
  -> CorrectedF0Track
  -> external RVC service
  -> rvc_vocal artifact
  -> mix with accompaniment.wav
  -> rvc_mix artifact
```

下一步：

- 明确外部 RVC service API contract。
- 实现 RVC client，而不是直接把 RVC 模型塞进后端。
- 将 corrected F0、converted vocal、mix 都注册为 artifacts。
- RVC job 必须可追踪到 project、task、score_revision 和 voice_model_id。

### 7. 单独设计 Piano Arrangement 能力

钢琴弹奏版是新能力，不属于 lead-vocal MVP。

目标输出：

- 前奏、间奏、尾奏有可弹奏钢琴伴奏。
- 人声段右手/高声部引入主唱旋律。
- 左手/内声部提供和声、低音、节奏型。
- 导出 piano MIDI / MusicXML。

建议新增表示层：

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

初版可以先做简化钢琴伴奏：

- 使用 chord progression 或手工/半自动 chord hints。
- 人声段保留 melody priority。
- 前奏/间奏/尾奏用 pattern 填充，不追求完全还原原曲。
- 清晰标注它是 generated arrangement，不是原曲多轨精确转写。

更高质量版本再引入：

- beat-synchronous chroma。
- chord recognition + HMM/Viterbi。
- bassline extraction。
- structure labels。
- motif/riff extraction。
- piano playability constraints。

## 不建议的开发顺序

- 不要先做完整钢琴编配，再回头修 lead-vocal ScoreIR。
- 不要让 agent 直接写 MIDI/MusicXML 绕过 `ScoreRevision`。
- 不要把 debug fallback 输出当成 production success。
- 不要让前端直接读 workspace 文件路径。
- 不要为了 demo 成功而隐藏 RMVPE 或 vocal separation 失败。

## 下一步最小任务清单

近期最小可执行顺序：

1. 用 `lead-vocal-mvp-execution.md` 跑通一首真实音频。
2. 补 artifact list/download API。
3. 前端接真实 auth/project/upload/task/score API。
4. 前端接 MusicXML 下载与 OSMD 渲染。
5. 前端接 MIDI 下载与播放。
6. 接 ScorePatch apply 与 revision regenerate exports。
7. 再设计 RVC job runner。
8. 最后单独开 piano arrangement 设计与实现。
