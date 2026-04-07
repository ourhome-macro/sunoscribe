# Pitch P1 协议文档（定稿）

## 1. 输出结构

顶层结构：

- `version: string`
- `meta: object`
- `analysis_info: object`
- `measures: array`
- `raw_notes: array`（可选）
- `warnings: array<string>`

## 2. 字段来源映射

| 字段 | 来源模块 |
|---|---|
| `meta.bpm` / `meta.bpm_confidence` | `beat_tracker` |
| `meta.time_signature` | `pipeline`（配置 + downbeat 结果） |
| `meta.total_measures` | `pipeline` |
| `meta.key` / `meta.key_confidence` | `key_analyzer` |
| `meta.rhythm_type` | `rhythm_analyzer` |
| `measures[*]` | `pipeline`（downbeat 边界） |
| `measures[*].notes[*].duration_beats` / `note_type` | `quantizer` |
| `measures[*].notes[*].measure_num` / `beat_position` | `pipeline`（downbeat 重算） |
| `analysis_info.downbeat_method` | `downbeat_tracker` |
| `analysis_info.measure_boundary_source` | `pipeline` |
| `analysis_info.quantized_measure_alignment` | `pipeline` |

## 3. 降级路径

1. **madmom 不可用**  
   - 行为：自动降级到 `librosa` 或 fallback downbeat。
   - 记录：`analysis_info.downbeat_method` 与 `warnings`。

2. **downbeat 不可用**  
   - 行为：基于 beat 序列按拍号近似回退。
   - 记录：`analysis_info.measure_boundary_source` 应反映回退来源。

3. **MIDI 依赖缺失或无有效音符**  
   - 行为：抛 `MidiExportError`。

## 4. 错误码建议

- `PITCH_DETECT_AUDIO_TOO_LONG`
- `PITCH_DETECT_MODEL_UNAVAILABLE`
- `BEAT_TRACK_NO_BEATS`
- `DOWNBEAT_TRACK_FAILED`
- `MIDI_EXPORT_DEPENDENCY_MISSING`
- `MIDI_EXPORT_NO_VALID_NOTES`

## 5. 兼容性约定

- 新增字段应向后兼容（仅追加，不删除已有字段）。
- `analysis_info` 可扩展，但关键字段不可缺失：
  - `downbeat_method`
  - `measure_boundary_source`
  - `quantized_measure_alignment`
