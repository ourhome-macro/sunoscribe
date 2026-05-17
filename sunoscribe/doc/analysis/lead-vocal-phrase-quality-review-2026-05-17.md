# Lead Vocal Phrase 后半段质量评审：听感与成谱结果

日期：2026-05-17

## 评审结论

如果目标是“听起来更像人唱、谱面更可用”，现在后半段最该优化的不是继续强化 f0-candidate，而是把 phrase postprocess 从“局部修补器”升级成“可审计的旋律事件整形器”。

当前链路里 phrase 已经能做短缝桥接、短音吸收、八度跳修正、中值平滑和 sustain gap。这些规则方向对，但容易出现两个相反风险：

1. 听感风险：过度平滑，把真实滑音、倚音、哭腔、装饰音、大跳唱法抹掉。
2. 成谱风险：不够整理，导致谱面碎片多、短音密、节奏不可读、歌词对不齐。

最优解不是简单调大/调小阈值，而是区分两个输出视角：

```text
performance melody：保留唱法听感，用于播放/RVC/F0 correction
notation melody：整理为可读谱面，用于 MusicXML/OSMD/编辑
```

当前代码把两者混在同一批 `lead_notes -> quantized_notes -> ScoreIR` 里，这是质量上限的主要瓶颈。

## 从“让听感更好”的角度

### 1. 不应把真实唱法强行修成局部中位数

`PhraseAwarePostprocessor._median_smooth` 会在局部窗口内把短音离群拉到 median：`backend/app/modules/pitch/phrase_postprocessor.py:608`。

这对去除 octave/f0 抖动有效，但对真实唱法有风险：

- 蓝调/流行里的快速经过音会被拉平。
- 副歌上行/下行前的小倚音会被当作 outlier。
- 连续滑音被切成几个短 note 后，中间目标音可能被改错。

建议：median smoothing 只允许改“低观测可信度”的音，不应只按 duration 和局部 deviation 判断。需要增加 F0 evidence gate：

```text
允许改音高 = 短音 + 低稳定度/低 voiced ratio/低 confidence + 修改后更接近 F0 主体或上下文强锚点
拒绝改音高 = 高 confidence + F0 frame median 支持原音高 + 处于旋律方向性移动中
```

### 2. octave correction 要保护真实大跳

`_correct_octave_jumps` 和 `_correct_octave_islands` 对听感帮助很大，因为 RMVPE/候选阶段常见八度错。但真实歌曲里也有：

- 副歌跳八度；
- 男声假声切换；
- 装饰性高音；
- 句尾上挑。

如果仅依赖邻近 anchor 和 semitone 阈值，会把真实 expressive leap 改平。

建议：octave 修正输出两类结果：

- `corrected`：证据强，直接改。
- `suspect_octave`：证据不足，只标 uncertain，不改 pitch。

证据强的标准应至少包含：

- 改前与邻居差值接近 12/24 半音；
- 改后局部轮廓更连续；
- 原 note confidence 或 stability 低于阈值，或 F0 frame 有典型 octave flip；
- 不跨明显 phrase gap/downbeat 强位置。

### 3. sustain gap 对听感有用，但不能吞掉呼吸和断句

`sustain_phrase_gaps` 会延长前音覆盖短 gap：`backend/app/modules/pitch/phrase_postprocessor.py:361`。

听感上，这能减少断裂和 MIDI 播放的“啃音”。但人声里短空隙可能是：

- 换气；
- 辅音闭塞；
- 断句；
- 明确的休止。

建议：sustain gap 不要只按 gap 和 pitch delta；还应看 vocal activity / energy：

```text
低能量且无 voiced frames：更像休止/呼吸，不 sustain
有 voiced tail 或 consonant-like gap：允许 sustain notation，但 performance 不延长 F0
```

换句话说，听感输出不应简单延长 F0；谱面输出可以用 tie/sustain 表达。

### 4. 短音吸收要避免吃掉装饰音

`_absorb_short_notes` 对谱面变干净很有价值，但听感上可能吃掉装饰音。建议不要直接删除/合并所有短音，而是先分类：

- `ornament`：保留在 performance，谱面可弱化或标 grace。
- `fragment`：删除或吸收。
- `syllabic_note`：如果对应歌词 token，应保留。

当前 ScoreIR 已有 `is_candidate_ornament`，但它是在 ScoreIR 阶段按 duration/confidence 推断：`backend/app/modules/score_ir/builder.py:752`。更好的做法是在 phrase 阶段就给短音打 `event_role`。

## 从“让结果更好/谱面更好”的角度

### 1. 当前成谱最大问题会是碎片与节奏可读性

量化器目前按 duration beats 分类，最短允许 1/32：`backend/app/modules/pitch/config.py:55`，并在 `NoteQuantizer.quantize` 里低于最小时长直接跳过：`backend/app/modules/pitch/quantizer.py:31`。

这会带来两个结果：

- 低于阈值的真实短音可能消失；
- 高于阈值但很密的短音会进入谱面，让 MusicXML 难读。

建议新增“notation density policy”：

```text
每小节短音比例过高时，不是简单保留，而是进行谱面简化：
- 合并同音短音为延音/连音；
- 快速邻接经过音降级为 ornament/grace；
- 无歌词且低 confidence 的短碎片删除；
- 有歌词 token 对齐的短音保留。
```

这比单纯调 `quantize_min_duration_beats` 更稳。

### 2. phrase 应先决定旋律事件，quantizer 只决定谱面时间

现在 phrase 会改 `end_time_sec`，quantizer 又会合并同音和处理 overlap：

- phrase 修改点：`backend/app/modules/pitch/phrase_postprocessor.py:697`
- quantizer 合并同音：`backend/app/modules/pitch/quantizer.py:60`
- quantizer overlap 修剪：`backend/app/modules/pitch/quantizer.py:260`

这会让结果变好一些，但责任重叠。最坏情况是：phrase 解释 A，quantizer 又改成 B，最终谱面原因不可解释。

建议明确阶段职责：

- phrase：决定“这个旋律事件是否存在、音高是什么、是否属于装饰/碎片/延音”。
- quantizer：决定“它写成几分音符、落在哪个 tick、是否 tie/rest”。
- ScoreIR：只消费已量化结果，不再猜测音乐意图。

### 3. 需要显式 rest/tie，否则谱面和听感都会别扭

当前链路主要处理 notes，短 gap 通过 sustain 或 merge 间接处理。可读谱面需要显式 rest/tie：

- phrase gap 是呼吸：ScoreIR 应有 rest 或 phrase break。
- phrase gap 是辅音空隙：谱面可以 tie/sustain，performance 可以保留空隙。
- 跨小节长音：应拆成 tie，而不是一个长 note 或奇怪 duration。

这对 MusicXML 质量非常关键。否则 OSMD 里会出现难读时值，MIDI 播放也会不自然。

### 4. downbeat/beat 质量直接决定结果，不应只作为 issue

ScoreIR 会标低 downbeat confidence issue：`backend/app/modules/score_ir/builder.py:798`。但如果 downbeat 错，谱面小节和强弱位置都会错，phrase 修得再好也救不了。

从“结果更好”角度，低 downbeat confidence 应触发：

- 输出可编辑但强提示；
- 或进入“unbarred / weak barline”模式；
- 或要求用户选择起拍/拍号后再最终导出。

不要让错误 downbeat 直接生成看似完整的正式谱。

## 推荐改进优先级

### P0：拆分 performance 与 notation 两套语义

新增两个字段或 artifact：

```text
SelectedMelody.performance_notes
SelectedMelody.notation_notes
```

短期不必大改架构，也可以在 selected note 上加：

```json
"event_role": "main" | "ornament" | "fragment" | "sustain" | "rest_boundary",
"notation_policy": "keep" | "merge" | "grace" | "drop" | "tie",
"performance_policy": "keep_f0" | "smooth_octave" | "preserve_gap" | "sustain_playback"
```

这样听感和谱面不会互相牵制。

### P0：phrase mutation 必须接入 F0 evidence gate

每次改 pitch/end_time/merge 前，增加证据判断和 trace：

```text
mutation_allowed = local_context_score + f0_evidence_score + confidence_penalty + lyric/rhythm guard
```

高 confidence 且 F0 支持原音的 note，不应被 median 或 octave 规则强改，只能标 suspect。

### P1：按小节控制谱面密度

在 QuantizedNoteSet 或 ScoreIRBuilder 前增加 `NotationSimplifier`：

- 每小节短音比例过高时触发；
- 优先处理无歌词、低 confidence、低 voiced ratio 的碎片；
- 对经过音/倚音标 grace，不直接删；
- 输出 issue 和 trace。

### P1：显式建 rest/tie/phrase break

不要只靠 sustain gap 延长音。应在 rhythm/score build 阶段表达：

- `rest`：真实静音或呼吸；
- `tie`：同一主音跨拍/跨小节；
- `phrase_break`：歌词/呼吸/长 gap 断句。

### P1：修复 selected melody lineage 校验弱化

`MelodyTranscriptionService._has_authoritative_selected_melody` 重复定义会让严格校验失效：

- `backend/app/services/melody_transcription_service.py:209`
- `backend/app/services/melody_transcription_service.py:230`

为了结果质量，必须保留严格校验：所有 selected notes 都应具备 source candidate/contour/f0 frame lineage。否则后续错误无法定位。

## 一针见血的判断

现在 phrase 逻辑已经能提升 demo 效果，但若直接追求“更顺”，很容易走向过度平滑；若直接追求“谱面更全”，又会保留太多碎片。生产级最优方向是：

```text
不要让一个 note list 同时承担听感和谱面两种目标。
```

先把 phrase 输出分层，再做 F0 evidence gate 和 notation density policy。这样听感会更像真实人声，谱面也会更像人会读的谱，而不是“检测结果的量化截图”。
