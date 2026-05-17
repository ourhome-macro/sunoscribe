# Lead Vocal Production Top 3 Blockers

日期：2026-05-15

## 结论

`lead-vocal` 的 pitch 主链已经能跑，但离上生产还有 3 个硬阻塞，不解决就不该判定为 production-ready。

## 阻塞 1：歌词识别与对齐链路没有真正接入主流程

这是当前最直接的功能缺口。

证据：

- `backend/app/services/audio_analysis_service.py`
  - perception stage 里 `lyrics_segments` 直接初始化为空列表。
  - 主流程没有真正调用歌词识别产出歌词段。
  - `process_audio()` 里直接走 `alignment = self._empty_alignment_stage()`。
  - `_empty_alignment_stage()` 返回的是 `plugin_deferred`，不是实际对齐结果。

影响：

1. Lead-vocal score 目前没有真实歌词输入，也没有真实的音符-歌词对齐。
2. 后续若前端要做歌词绑定、编辑、导出一致性校验，这条链是空的。
3. 这不只是“效果不好”，而是链路本身未接通。

建议动作：

1. 在 perception stage 真正接入 lyrics recognizer。
2. 用 recognizer 输出驱动 baseline alignment，而不是固定走 deferred stub。
3. 把 `lyrics_segments`、`baseline_alignment`、`final_alignment` 的成功/失败语义做成 required/optional 的明确契约。

## 阻塞 2：machine revision 存在文件态和数据库态双重 authority

这是结构性问题，比普通 bug 更危险。

证据：

- `backend/app/services/audio_analysis_service.py`
  - 会创建文件态 `MachineScoreRevisionState`
  - 会写 `revisions/machine-0001-.../score_ir.json`
  - 会写 `revisions/machine-0001-.../artifact_manifest.json`
  - 还会在这个文件态 revision 目录下生成 MIDI/MusicXML

- `backend/app/services/score_service.py`
  - `generate_or_regenerate_score()` 在 `AudioAnalysisService` 返回后，又调用数据库态 `create_machine_score_revision()`

- `backend/app/services/score_revision_service.py`
  - 会创建真正的 DB `ScoreRevision`
  - 会重新注册 artifact
  - 会再次用 `RenderExportService` 基于 DB revision 生成 exports

影响：

1. 同一次转谱实际上生成了两套 machine revision 语义。
2. 文件态 revision id 与 DB revision id 不同，traceability 会裂开。
3. artifact manifest 和 API 返回的 revision/artifact authority 不完全一致。
4. 这种双轨状态在调试时看起来“都成功”，但线上排障和审计会非常难受。

建议动作：

1. 选一个唯一 authority。
2. 更合理的方向是：DB `ScoreRevision` 为唯一 revision authority，文件系统只做该 revision 的 artifact storage。
3. `AudioAnalysisService` 不要再自造独立 machine revision id；它只负责产 typed artifacts，把 revision 创建放到 `score_revision_service`。

## 阻塞 3：完整上传场景下的 required-stage 实链还没有被真实验证完

注意，这里说的不是 pitch 主链没实现，而是生产入口还没有被证明稳定。

已确认的事实：

1. 我实跑过真实 vocal stem，`F0Track -> candidate -> selected melody -> quantized -> ScoreIR` 是通的。
2. 但这次实跑是 `enable_vocal_separation=False`，输入的是现成 vocal wav。
3. 也就是说，验证的是“已分离人声后的 pitch 主链”，不是“用户真实上传 raw mix/video 后的完整 lead-vocal 生产链”。

代码侧证据：

- `backend/app/services/audio_analysis_service.py`
  - 默认 `enable_vocal_separation=True`
  - vocal separation 是 required stage，没出 `vocals stem` 直接失败

- `backend/app/services/score_service.py`
  - `vocals_path` 不存在会直接拒绝 machine revision

- `backend/app/modules/vocal/separator.py`
  - 分离逻辑本身很重，且依赖外部模型、输出目录、文件扫描与伴奏拼装逻辑

影响：

1. 现在不能把“vocal stem 上能跑通”直接等同于“真实用户上传就能稳定生产”。
2. 如果 separation、视频抽音、长音频、弱人声、伴奏泄漏这些入口场景没做实测，生产故障会首先爆在 required stages。
3. 这已经不是算法小调优，而是 release gating 问题。

建议动作：

1. 用真实 raw mix、真实视频、不同风格样本做最小回归集。
2. 至少覆盖：上传音频、上传视频、正常分离、分离失败、弱人声、长时长样本。
3. 把这套回归直接接到 task/API 层，不要只在 pitch module 层做局部测试。

## 不是阻塞的部分

下面这些不是当前 top 3：

1. `f0-candidate` 主体实现。
2. `lead-vocal` 的 quantized-notes 到 ScoreIR 主链。
3. MIDI/MusicXML 的“能不能生成”。

这些部分已经到了可运行状态，问题更多是调优和收口，不是主阻塞。

## 最短判断

如果只看 `lead-vocal`，当前最短的生产判断应该是：

> pitch 主链基本可用，但歌词链未接入、revision authority 分裂、完整上传场景未做 required-stage 实证，因此还不能判定为 production-ready。

