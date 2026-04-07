# Pitch P1 测试矩阵（定稿）

## 1. 目标

确保 P1 输出在功能正确性、降级路径、协议兼容性上可验收。

## 2. 测试维度与用例

| 维度 | 用例 ID | 场景 | 核心断言 | 优先级 |
|---|---|---|---|---|
| Detector | DET-001 | 常规人声输入 | 返回音符序列，`confidence` 在 `[0,1]` | P0 |
| Detector | DET-002 | 超长音频 | 抛 `AudioTooLongError` | P0 |
| Detector | DET-003 | basic-pitch 缺失 | 抛 `PitchModelUnavailableError` | P0 |
| Beat | BEAT-001 | 常规节拍 | 产出 BPM、beat_times 非空 | P0 |
| Beat | BEAT-002 | 空音频 | 抛 `NoBeatsDetectedError` | P0 |
| Downbeat | DB-001 | downbeat 正常检测 | downbeat 递增且非空 | P0 |
| Downbeat | DB-002 | madmom 不可用 | 降级 librosa，记录 warning | P1 |
| Quantizer | QTZ-001 | 4/4 常规旋律 | 时值量化正确，小节号连续 | P0 |
| Quantizer | QTZ-002 | 3/8 配置拍号 | measure 按配置拍号计算（非写死 4/4） | P0 |
| Pipeline | PL-001 | 弱起场景 | 首小节 `is_anacrusis=true` | P0 |
| Pipeline | PL-002 | downbeat 边界分段 | `measure_boundary_source=downbeat_sequence` | P0 |
| Pipeline | PL-003 | 量化对齐 | `quantized_measure_alignment=downbeat_reindexed` | P0 |
| MIDI | MIDI-001 | 导出字节流 | 返回 `bytes` 且包含 `MThd` 头 | P0 |
| MIDI | MIDI-002 | 导出文件 | 目标路径生成 `.mid` 文件 | P0 |
| 协议 | SCHEMA-001 | 顶层结构 | 必填字段完整 | P0 |
| 协议 | SCHEMA-002 | 小节结构 | `measure_num/start_time/end_time/is_anacrusis/notes` 完整 | P0 |

## 3. Fixtures 目录规范

建议目录：

- `tests/fixtures/pitch/vocal/`
- `tests/fixtures/pitch/accompaniment/`
- `tests/fixtures/pitch/complex_rhythm/`

每个 fixture 建议包含：

- `input.wav`：输入音频
- `expected.json`：关键断言字段
- `meta.json`：采样率、时长、标签

## 4. 验收通过标准

- 全部 P0 用例通过。
- P1 用例通过率 >= 90%。
- 无阻塞级错误（协议字段缺失、导出失败、降级路径失效）。
