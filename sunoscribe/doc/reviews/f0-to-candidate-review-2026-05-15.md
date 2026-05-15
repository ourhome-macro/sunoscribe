# F0 -> Candidate 审计评价（2026-05-15）

> 本文审计 SunoScribe 当前 lead-vocal 路线中 `F0Track -> PitchContourSet -> NoteCandidateSet/lead candidates` 的实现质量、链路一致性和生产风险。

## 结论先行

当前 `F0 -> candidate` 不是一个清晰的 typed stage，而是两套候选构建逻辑叠加：

1. `PitchDetector` 在 RMVPE 后直接把帧切成 `Note`，这些 `Note` 被当作 raw candidates 进入主流程。
2. `PitchContourBuilder` 从同一份 F0 再切一遍 contour。
3. `ContourToCandidateBridge` 在主流程中只“补洞式”把少量 contour 提升成 raw notes。
4. `NoteCandidateBuilder` 在 `MelodyTranscriptionService` 里又把 `semantic_audio.melody_candidates` 与 contour 合并，主要用于产出 `note_candidates.json`。
5. `ScoreIR` 仍主要来自 `lead_notes/quantized_notes`，不是严格从持久化 `NoteCandidateSet + RhythmGrid` 构建。

一句话判断：这段代码已经开始有 typed artifact 的外形，但核心语义仍是“RMVPE 帧直接切 note + 一堆后处理补救”。它不是稳定、可解释、可评估的生产级 F0-to-candidate stage。

## 主要证据

- `backend/app/modules/pitch/detector.py`：`detect()` 调 RMVPE 后直接 `_frames_to_notes()`，候选音符在 detector 内成型。
- `backend/app/modules/pitch/pipeline.py`：`detected_notes` 先由 detector 产生，再用 `ContourToCandidateBridge` 增补，然后送入 arbitrator、selector、quantizer。
- `backend/app/services/melody_transcription_service.py`：`note_candidates.json` 是服务层用 `f0_track + pitch_contours + semantic_audio.melody_candidates` 重建的 payload。
- `backend/app/modules/score_ir/builder.py`：ScoreIR 优先从 measures/lead notes/raw notes 建出，不是从 `note_candidates.json` 作为唯一输入建出。

## 致命问题

### 1. Stage 边界错位

项目文档要求链路是：

```text
F0Track -> PitchContourSet -> NoteCandidateSet -> RhythmGrid -> ScoreRevision
```

但当前实际链路更接近：

```text
RMVPE frames -> detector-internal Notes -> contour bridge patch -> melody selector -> quantizer -> ScoreIR
                      \-> F0Track/PitchContourSet/NoteCandidateSet as side artifacts
```

这意味着 `NoteCandidateSet` 不是真正的生产状态源，而更像“事后解释/归档”。后续修质量会很痛，因为你不能只修 candidate stage，还要同时理解 detector、bridge、selector、quantizer 四层后处理。

### 2. Detector 同时做 F0 和 note segmentation

RMVPE backend 的职责应是生产 `F0Track`：连续 F0、voiced/unvoiced、confidence、时间戳。当前 `PitchDetector` 还直接负责 `_frames_to_notes()`，包含阈值、平滑、短空洞桥接、Viterbi、segment merge、pitch rounding 等音乐决策。

这是架构上的最大问题：F0 证据层和 note candidate 层混在一个类里，后续很难判断错误来自 F0、voicing、segmentation 还是 candidate filtering。

### 3. 候选构建有“两套事实来源”

主流程中的 candidates 是 `detected_notes + ContourToCandidateBridge`；持久化 artifact 中的 `note_candidates.json` 是 `NoteCandidateBuilder` 重新合并 `semantic_audio.melody_candidates + pitch_contours`。两者并不天然等价。

风险：页面/agent/诊断看的是 `note_candidates.json`，ScoreIR 实际吃的是 quantized/lead notes。用户看到的“候选证据”和最终谱面的因果链可能断裂。

### 4. Contour bridge 不是真正的 F0-to-candidate 主路径

`ContourToCandidateBridge` 代码注释说是 conservative promote isolated high-quality F0 contours，但它有一个硬条件：没有 raw candidates 时直接返回原 raw list。因此当 detector 没切出任何 note 时，bridge 不会用 contour 兜出候选。

这很危险：F0 明明可能存在，但 raw note segmentation 失败时，主流程没有真正的 `F0Track -> CandidateSet` 主路径能救回来。

### 5. Pitch contour 切分过粗

`PitchContourBuilder` 主要按 voiced/active 和短 unvoiced gap 分段，不以音高稳定区间、局部台阶、onset/energy/lyric syllable 边界为主要切分依据。一个长滑音、颤音、连唱 phrase 很容易成为一个 contour，然后再被 median pitch 压成一个 candidate 或被 bridge segmentation 二次补救。

这不是好的候选生成范式。候选层应该显式保留“一个 contour 可产生多个 note hypotheses”的结构，而不是先粗切成 contour 再用多处 guard 和补洞修补。

### 6. 参数体系经验化且分散

相关阈值散落在：

- `PitchDetectionConfig` 的 RMVPE segmentation 参数；
- `PitchContourConfig` 的 contour 参数；
- `ContourToCandidateBridgeConfig` 的桥接参数；
- `NoteCandidateBuilderConfig` 的候选过滤参数；
- `MelodySelector` 和 phrase postprocessor 的过滤参数。

这些参数有大量绝对阈值：0.08s、0.18s、0.72、0.9、48-84 MIDI、1.2 semitone、2.5 semitone 等。它们没有统一的 profile、目标曲风、音区、性别声部、速度依赖，也没有从数据集校准的证据。

### 7. Octave error 处理太靠后、太启发式

有 low octave rescue、octave outlier、context guard 等迹象，但它们分布在 bridge/selector/postprocess。真正理想的处理应在 F0 evidence 到 contour/candidate 时就保留 octave hypothesis 和置信竞争，而不是先 round/merge 成单一 pitch 再靠上下文改。

当前方式会把 octave 错误固化为 candidate，再由后处理猜测修正，缺乏可解释的 alternative hypothesis。

### 8. Candidate 缺少候选竞争模型

`NoteCandidateSet` 现在是 accepted notes 列表 + rejected candidates。缺少：

- 同一时间片多个 pitch hypotheses；
- onset/offset 不确定区间；
- pitch center 的分布/方差；
- voiced coverage 与 confidence curve 的细粒度证据；
- segmentation alternatives；
- candidate ranking score 与 reject/accept 的可校准概率。

这导致 agent 或 UI 只能编辑“已经决定好的 note”，而不是审阅“候选竞争”。

### 9. 与 RhythmGrid 的耦合位置不理想

F0-to-candidate 阶段理论上应输出未量化但节奏可诊断的 note candidates，然后 `RhythmGrid` 再参与量化。当前 detector/bridge/selector 在节奏之前已经做了大量 duration/merge/filter 决策，后续 rhythm quantizer 很难恢复被删掉或过度合并的音。

### 10. 诊断能力比生产能力先进

测试和 debug package 已经开始识别 `f0_exists_but_no_candidate`、`candidate_exists_but_selector_removed`、`f0_to_note_candidate_loss` 等问题。这说明团队已经看到了关键失真点；但实现上仍是补诊断，而不是把主链路改成 typed、可替换、可评估的 candidate builder。

## 建议判断

当前实现不建议作为“生产级 F0->Candidate 核心”继续堆补丁。应把它定性为：可跑 demo 的混合启发式管线，有不错的 artifact 意识，但 stage 边界和因果链还没打通。

下一阶段最优解不是继续调 bridge/selector 阈值，而是重构职责：

1. `PitchDetector/RMVPE` 只产 `F0Track`，不直接产最终 `Note`。
2. 新建明确的 `NoteCandidateService`：唯一消费 `F0Track + PitchContourSet`，唯一产出 `NoteCandidateSet`。
3. `NoteCandidateSet` 必须包含 candidate hypotheses、rejected hypotheses、source frame ranges、alternative octave hypotheses、segmentation alternatives。
4. `MelodySelector` 只从 `NoteCandidateSet` 选择 lead melody，不再混入 detector raw notes。
5. `ScoreIR`/quantized artifacts 必须保留 `source_candidate_id`，并能从 ScoreIR 反查到 F0 frame range。
6. 没有 candidate 时，如果 F0 voiced coverage 足够，应明确报 `f0_to_candidate_segmentation_failed`，而不是只给空谱或后处理警告。

## 风险等级

- 生产风险：高。
- 架构债：高。
- 可维护性：中低。
- 可诊断性：中高。
- 继续调参收益：低到中。
- 重构收益：高。
