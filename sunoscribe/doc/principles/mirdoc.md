# MIR 从零到大师训练手册

来源：本目录中的 `Fundamentals of Music Processing` PDF。本文是扩展版学习文档，不是逐字摘录，而是把全书内容按 MIR 专业训练路线重新组织：先建立概念地图，再逐章学习核心表示、算法、参数、误区和实践项目。

适合读法：

1. 第一遍只看每章的“本章解决什么问题”和“高手重点”。
2. 第二遍边看 PDF 边读每章详细解释。
3. 第三遍按末尾项目路线做实验：画图、调参数、看失败案例。
4. 真正要变强，必须习惯可视化：waveform、spectrogram、chroma、cost matrix、SSM、novelty curve、tempogram、salience map。

全书章节对应关系：

| 章节 | 主题 | 在 MIR 中的位置 |
| --- | --- | --- |
| Chapter 1 | Music Representations | 音乐数据表示，所有任务的输入观 |
| Chapter 2 | Fourier Analysis of Signals | 音频转时频表示的信号处理底座 |
| Chapter 3 | Music Synchronization | Chroma、DTW、跨版本对齐 |
| Chapter 4 | Music Structure Analysis | SSM、重复、分段、thumbnail |
| Chapter 5 | Chord Recognition | Chroma + 音乐理论 + HMM/Viterbi |
| Chapter 6 | Tempo and Beat Tracking | Onset、novelty、tempogram、beat |
| Chapter 7 | Content-Based Audio Retrieval | fingerprint、索引、匹配、版本识别 |
| Chapter 8 | Musically Informed Audio Decomposition | HPSS、旋律提取、NMF、音频分解 |

## 总地图：MIR 到底在做什么

MIR 的核心能力是把音乐转换成恰当的数据表示，然后在这个表示上做比较、推断、检索、分解或标注。

```text
音乐现象
-> 数据表示
-> 特征提取
-> 相似度 / 概率模型 / 动态规划 / 矩阵分解
-> 任务结果
-> 评价与误差分析
```

最常见的处理链如下：

```text
audio waveform
-> STFT / spectrogram
-> log-frequency spectrogram
-> chroma / novelty / tempogram / salience / fingerprint
-> DTW / HMM / Viterbi / SSM / NMF / inverted index
-> synchronization, chords, beats, structure, retrieval, decomposition
```

高手判断一个 MIR 方案，通常先问这几个问题：

- 任务需要保留什么音乐信息？音高、和声、节拍、音色、旋律、结构，还是录音身份？
- 哪些变化应该被忽略？音量、音色、八度、转调、速度、噪声、演奏差异？
- 特征是否保留了目标信息，同时压掉了干扰？
- 后续算法的假设是否匹配这个特征？
- 评价指标是否真的对应任务目标？

---
## 第一篇：音乐表示与傅里叶/STFT/谱图

本文对应《Fundamentals of Music Processing》的 Chapter 1 **Music Representations** 与 Chapter 2 **Fourier Analysis of Signals**。写作目标不是翻译原书，而是把前两章整理成适合从初学者走向进阶实践的中文学习草稿：先理解“音乐如何进入计算机”，再理解“音频如何变成时间-频率表示”。这两章是后续 chroma、同步、结构分析、和弦识别、节拍跟踪、检索和音频分解的共同地基。

---

### Chapter 1 Music Representations：音乐表示

#### 1.1 本章解决什么问题

音乐不是天然以一种形式存在于计算机中。同一首曲子可以是纸上的五线谱，可以是 MusicXML 或 MIDI 文件，可以是一段 WAV/MP3 音频，也可以是从音频进一步计算出的谱图、chroma、novelty curve、tempogram 或 self-similarity matrix。MIR 的第一课是：算法处理的不是“音乐本身”，而是某一种被选择出来的音乐表示。

这个选择会直接决定任务难度。例如：

- 如果输入是 MIDI，音符的起止时间和音高通常已经显式存在，旋律轮廓、音程、节奏型比较容易分析。
- 如果输入是乐谱图像，人类能读，但计算机首先只看到像素，需要经过 OMR 才能变成符号信息。
- 如果输入是音频，演奏细节、音色、混响、噪声都保留了，但“哪个音符正在响”“当前和弦是什么”“拍点在哪里”并不显式写在文件里。

所以，MIR 的许多问题其实是表示转换问题：

```text
音乐现象
-> 可计算表示
-> 任务相关特征
-> 相似度 / 概率模型 / 优化算法
-> 标签、边界、对齐、检索结果或分离结果
```

本章重点区分三类表示：乐谱表示、符号表示、音频表示。

#### 1.2 三类核心音乐表示

##### 1.2.1 Sheet Music：乐谱表示

乐谱是面向人的视觉表示。它用五线谱、谱号、调号、拍号、音符形状、休止符、连线、力度、表情和演奏法等符号描述“应该如何演奏”。它非常适合人类音乐家阅读和解释，但不等于一次真实演奏。

直觉上，乐谱更像一份“演出说明书”，不是声音本身。两个钢琴家按照同一份乐谱演奏，会有不同的速度弹性、力度层次、踏板、断连、音色控制和句法处理。乐谱给出结构和约束，演奏者给出具体声音。

乐谱表示中常见信息包括：

- 音高：音符在五线谱上的垂直位置，加上谱号、调号、临时升降号共同决定实际音高。
- 时值：全音符、二分音符、四分音符、附点、连音线等决定相对持续时间。
- 时间组织：小节线、拍号、反复记号、跳转指令等决定阅读和演奏顺序。
- 表情信息：力度、速度术语、连奏、断奏、重音、装饰音等影响演奏方式。

学习误区：

- 乐谱不是音频。乐谱中没有真实波形、麦克风位置、房间混响和乐器具体音色。
- 乐谱也不是唯一的音乐真相。它常常省略或只暗示大量演奏细节。
- 乐谱图像不是符号数据。扫描谱页只是像素，必须经过识别和语义解析，才能得到音符、节拍、反复结构等机器可读内容。

##### 1.2.2 Symbolic Representations：符号表示

符号表示是机器可读的音乐事件表示。它通常显式记录音符、时间、音高、力度、声部、通道或其他音乐实体。典型形式包括 piano-roll、MIDI、MusicXML。

**Piano-roll**

Piano-roll 可以想成一张二维网格：横轴是时间，纵轴是音高。一个音符就是从起始时间到结束时间的一段水平矩形。它非常直观，尤其适合观察复调音乐中的声部进入、主题重复、音高轮廓和节奏密度。

它和谱图看起来有点像，但本质不同：

- piano-roll 的纵轴是离散音高或 MIDI note number。
- spectrogram 的纵轴是频率 bin，表示音频能量。
- piano-roll 是符号事件；spectrogram 是从真实声音中估计出的频率能量。

**MIDI**

MIDI 最初是电子乐器之间通信的工业标准，不是为音乐学语义存档而设计的。但因为普及程度高、数据多，它在 MIR 中很常用。

MIDI 的关键事件包括：

- `note-on`：某个音开始。
- `note-off`：某个音结束。
- `velocity`：按键速度，通常和响度或触键强度相关，但具体解释依赖合成器。
- `channel`：通道，可用于区分乐器或声部。
- `ticks` 与 `PPQN`：相对时间单位和四分音符分辨率。
- tempo message：把 ticks 转换为真实秒数所需的速度信息。

MIDI 的优点是音高、起点、终点、力度通常直接可得；缺点是它不保证真实演奏音色，也不保证数据质量。网上的 MIDI 文件可能存在量化粗糙、声部分配错误、缺少表情、与原曲不一致等问题。

**MusicXML**

MusicXML 更接近乐谱语义，适合记录谱号、调号、拍号、音符、休止、时值、声部、连线、歌词、排版相关信息等。它比 MIDI 更适合“乐谱层面”的交换和编辑，但也更复杂。

**OMR**

Optical Music Recognition 是把乐谱图像转换成符号表示的过程。它不只是识别黑点和线条，还要理解这些符号在音乐语法中的意义。一个小污点可能被误认为断奏点；一个反复记号识别失败可能导致整首曲子的展开顺序错误；移调乐器如果没有正确解释，也会造成音高偏差。

学习误区：

- MIDI 不是音频。MIDI 文件本身通常不包含声音波形，而是控制消息。
- 符号表示不等于真实演奏。它保留结构清晰度，但丢失或弱化了大量音色、混响、录音和微表情细节。
- piano-roll 的“看得清”不代表音乐问题已经解决。复调声部分离、主题识别、调性分析仍然需要进一步建模。

##### 1.2.3 Audio Representation：音频表示

音频表示记录的是声波的数字化结果。真实演奏产生空气压力的微小变化，麦克风把这些压力变化转成电信号，之后通过采样和量化变成数字音频。WAV、FLAC、MP3 等都是音频表示的常见形式。

音频保留了符号表示通常没有的东西：

- 演奏者的微小速度和力度变化。
- 音色、起音、衰减、颤音、揉弦。
- 多个乐器和声部的真实混合。
- 房间、设备、混响、噪声、压缩编码带来的影响。

但音频不显式告诉你：

- 哪个音符在何时开始和结束。
- 当前基频、旋律或和弦是什么。
- 哪些声部分别属于哪些乐器。
- 段落边界、主题重复和乐曲结构在哪里。

因此，从音频出发的 MIR 任务往往更难，因为它需要从混合声波中推断中高层音乐信息。

#### 1.3 音高、频率、八度与 chroma

MIR 初学者最容易混淆的概念之一是 frequency、pitch、pitch class 和 chroma。

**Frequency**

频率是物理概念，单位是 Hz，表示每秒振动多少次。一个 440 Hz 的正弦波每秒完成 440 个周期。

**Pitch**

pitch 是听觉音高，是人对声音高低的感知。它和频率强相关，但不是同一件事。人耳对音高的感知接近对数关系：220 Hz 到 440 Hz 与 440 Hz 到 880 Hz 都听起来相差一个八度，虽然后者频率差是 440 Hz，前者只有 220 Hz。

**Octave**

两个频率相差 2 倍时，对应一个八度。例如 A3 = 220 Hz，A4 = 440 Hz，A5 = 880 Hz。它们听起来“同名但高低不同”。

**Pitch class**

pitch class 是忽略八度后的音高类别。C3、C4、C5 都属于 C 这个 pitch class。

**Chroma**

chroma 在 MIR 中通常指 12 个 pitch class 的能量或强度表示：C、C#、D、D#、E、F、F#、G、G#、A、A#、B。它把相差整数个八度的音高折叠到同一类中。后续的和弦识别、版本匹配、音乐同步和结构分析会大量使用 chroma。

十二平均律中，MIDI 音高编号 `p` 与中心频率的关系常写作：

```text
F(p) = 440 * 2^((p - 69) / 12)
```

白话解释：MIDI 69 是 A4，对应 440 Hz。每升高 12 个 MIDI 音号，频率乘以 2；每升高 1 个半音，频率乘以 `2^(1/12)`。这说明音乐音高坐标天然更接近对数频率轴，而不是线性频率轴。

#### 1.4 声音的基本物理概念

**Waveform**

waveform 是声压偏离平均气压的变化曲线。横轴是时间，纵轴是振幅。波形能告诉我们“声音随时间如何变化”，但很难直接看出“有哪些音高或频率成分”。

**Sinusoid**

正弦波是最简单的周期波形。它由频率、振幅和相位决定：

- 频率决定每秒振动次数。
- 振幅决定偏离中心的程度，通常和能量或响度相关。
- 相位决定这个周期从哪里开始。

**Fundamental frequency (F0)**

基频通常是决定一个有音高声音的主要频率。例如一根弦整体振动产生的最低周期频率常对应听到的音高。

**Partial / Harmonic / Overtone**

一个真实乐器音不是单一正弦波，而是许多正弦成分的叠加。partial 是组成声音的频率成分。harmonic 是频率等于 F0 整数倍的 partial。overtone 通常指除最低 partial 以外的泛音。

例如，F0 为 100 Hz 的理想谐波声音可能含有 100、200、300、400 Hz 等成分。不同乐器在这些成分的相对强度和随时间变化上不同，所以音色不同。

**Loudness 与 intensity**

intensity 是物理强度，loudness 是主观响度。人耳对响度的感知不是线性的，因此音频分析中常用对数尺度或 dB 表示能量变化。后续谱图可视化中，使用 dB 常常比直接显示线性能量更有用，因为弱但重要的频率成分会更容易看见。

**Timbre**

音色不是一个单独参数，而是频谱分布、起音、衰减、噪声成分、包络、演奏方式和共振结构的综合结果。钢琴、小号、小提琴、长笛即使演奏同一个 C4，它们的波形和频谱也会不同。

#### 1.5 为什么 Chapter 1 对后续 MIR 重要

后续每个 MIR 任务都建立在表示选择之上：

- 音乐同步常把音频先转成 chroma 或 CENS，再做 DTW。
- 结构分析常把特征序列变成 self-similarity matrix。
- 和弦识别常从音频提取 chroma，再做模板匹配或 HMM。
- 节拍跟踪常从 waveform 转成 novelty curve，再分析周期性。
- 检索任务会在 fingerprint、chroma 或其他稳健特征之间权衡。
- 音频分解会直接操作 spectrogram 或其矩阵分解形式。

真正的关键问题不是“哪个算法最强”，而是：

```text
这个任务需要保留什么信息？
需要忽略什么变化？
当前表示显式给出了什么？
当前表示隐藏或丢失了什么？
```

#### 1.6 实践练习与 librosa 任务思路

1. 比较同一首曲子的三种表示  
   找一段音频、一个 MIDI 文件和一页乐谱截图。观察三者分别保留了什么、缺失了什么。尝试用 `pretty_midi` 或 `music21` 读取 MIDI，用 `librosa.load` 读取音频。

2. 画 waveform  
   用 `librosa.load` 读取一段 10 秒音频，用 `librosa.display.waveshow` 画波形。标出你认为可能有明显重音或起音的位置，再和听感对比。

3. MIDI 音号到频率  
   自己实现 `440 * 2 ** ((p - 69) / 12)`，打印 C4、A4、A5 的频率。再用 `librosa.midi_to_hz` 验证。

4. piano-roll 观察  
   读取一个 MIDI，转换成 piano-roll，观察旋律、和声、低音、密集段落。思考：哪些结构在 piano-roll 中比在五线谱中更容易看见？

5. chroma 直觉实验  
   用钢琴或合成器生成 C3、C4、C5 三个音，提取 chroma。观察它们是否主要落在同一个 pitch class 上。

---

### Chapter 2 Fourier Analysis of Signals：傅里叶分析、STFT 与谱图

#### 2.1 本章解决什么问题

原始 waveform 只显示振幅如何随时间变化。对音乐分析来说，我们经常更关心：

- 哪些频率正在出现？
- 哪些频率能量更强？
- 这些频率大约在什么时候出现？
- 不同乐器或不同音高在频谱上有什么差异？

傅里叶分析提供了从“时间视角”到“频率视角”的桥梁。它的核心思想是：复杂信号可以看成许多不同频率、不同强度、不同相位的正弦波叠加。

可以把傅里叶变换理解为一种匹配过程：

```text
拿信号去和许多不同频率的正弦/复指数模板比较
-> 哪个模板匹配得强，说明这个频率成分强
-> 得到每个频率的复数系数
```

这些系数包含两类信息：

- magnitude：这个频率有多强。
- phase：这个频率成分在时间上如何对齐。

#### 2.2 傅里叶变换的直觉

假设有一个钢琴 C4，基频约为 261.6 Hz。真实钢琴声不只是 261.6 Hz 一个正弦波，还会包含 523.2 Hz、784.8 Hz 等更高 partial，以及噪声和瞬态成分。傅里叶变换会在这些频率附近给出较大的系数。

对不同乐器演奏同一个 C4，基频位置可能相近，但高频 partial 的相对强度、起音噪声和包络不同，所以频谱形状不同。这就是为什么傅里叶分析既能帮助我们估计音高，也能帮助理解音色。

但普通傅里叶变换有一个关键缺陷：它给出的是整段信号的总体频率内容，不告诉你频率在什么时候出现。如果一段信号前半段是 1 Hz，后半段是 5 Hz，和另一段同时叠加 1 Hz 与 5 Hz 的信号，它们的整体 magnitude spectrum 可能很相似，但时间结构完全不同。音乐显然是时间变化的，所以我们需要 STFT。

#### 2.3 从连续信号到离散信号

物理世界中的声音可以看成连续时间信号：任意时刻都有一个声压值。计算机不能直接存储无限连续函数，只能按采样率取离散样本。

关键术语：

- sampling rate / sample rate：每秒采样多少次，例如 22050 Hz、44100 Hz、48000 Hz。
- sample：某个采样时刻的振幅值。
- digital signal：由一串样本组成的离散序列。
- quantization：把连续振幅映射到有限精度数字。
- Nyquist frequency：采样率的一半，是可表示频率的上限。

如果采样率是 44100 Hz，那么理论上最高能表示约 22050 Hz 的频率成分。超过 Nyquist frequency 的成分会产生混叠风险。这就是为什么音频采集和重采样需要低通滤波。

#### 2.4 DFT：离散傅里叶变换

实际工程中，我们通常处理有限长度的离散信号片段。给定长度为 `N` 的序列 `x[n]`，DFT 把它变成长度为 `N` 的复数频谱 `X[k]`：

```text
X[k] = sum_{n=0}^{N-1} x[n] * exp(-2*pi*i*k*n/N)
```

白话解释：

- `n` 是时间样本索引。
- `k` 是频率 bin 的索引。
- `exp(-2*pi*i*k*n/N)` 是第 `k` 个频率模板。
- `X[k]` 是原信号和这个频率模板的匹配程度。
- `X[k]` 是复数，因此同时包含 magnitude 和 phase。

注意：`k` 不是 Hz。它只是频率格点编号。要换成实际频率，需要采样率 `sr`：

```text
freq[k] = k * sr / N
```

如果 `sr = 44100`，`N = 2048`，那么相邻频率 bin 的间隔约为 `44100 / 2048 = 21.53 Hz`。这就是频率分辨率。`N` 越大，频率格点越密，但时间窗口也越长。

对真实值音频，DFT 的上半部分和下半部分存在共轭冗余，所以常只看从 0 到 Nyquist frequency 的一半频谱。

#### 2.5 FFT：快速傅里叶变换

FFT 不是另一种变换，而是快速计算 DFT 的算法。直接计算 DFT 大约需要 `O(N^2)` 次操作；FFT 利用 DFT 矩阵的结构，把复杂度降到 `O(N log N)`。

白话理解：FFT 把一个大 DFT 拆成偶数索引样本和奇数索引样本上的两个小 DFT，再递归合并。这个“分而治之”的结构让大规模音频分析变得可行。

学习误区：

- DFT 是数学变换，FFT 是计算 DFT 的高效算法。
- `np.fft.fft` 得到的是复数频谱，不是直接可视化的“响度图”。
- 只看 magnitude 会丢掉 phase；很多分析任务可以丢 phase，但重建和相位相关任务不能随便丢。

#### 2.6 STFT：短时傅里叶变换

普通傅里叶变换把整段信号一次性投影到频率域，缺少时间定位。STFT 的办法是：每次只看一小段音频，对这一小段做 DFT，然后把窗口往前移动，重复这个过程。

STFT 流程：

```text
1. 取一段长度为 n_fft 或 win_length 的窗口
2. 乘以 window function，例如 Hann window
3. 对窗口内信号做 DFT/FFT
4. 向前移动 hop_length 个样本
5. 重复，得到 time frames x frequency bins 的复数矩阵
```

离散 STFT 常写成：

```text
X[m, k] = sum_{n=0}^{N-1} x[n + mH] * w[n] * exp(-2*pi*i*k*n/N)
```

白话解释：

- `m` 是第几个时间帧。
- `k` 是第几个频率 bin。
- `H` 是 hop size，也就是相邻帧之间移动多少样本。
- `w[n]` 是窗口函数，用来让截取片段的边界更平滑。
- `X[m, k]` 表示第 `m` 个时间片里，第 `k` 个频率模板的复数匹配系数。

#### 2.7 window function 的作用

如果直接截取一段信号，相当于用矩形窗口突然切断声音。突然切断会引入边界不连续，从而在频谱里产生额外的 ripple 或 leakage。窗口函数的作用是让片段边缘平滑地接近 0，减少边界伪影。

常见窗口：

- rectangular window：最直接，但边界效应强。
- triangular window：边缘平滑一些。
- Hann window：音频 STFT 中非常常用，边缘平滑，能减少泄漏。

代价是：窗口越平滑，频率定位和能量扩散也会受到影响。窗口选择没有免费午餐。

#### 2.8 Spectrogram：谱图

STFT 的输出是复数矩阵。谱图通常显示它的 magnitude 或 power：

```text
magnitude spectrogram: |STFT|
power spectrogram: |STFT|^2
```

图像中：

- 横轴是时间。
- 纵轴是频率。
- 颜色或亮度表示能量大小。

音频中能量范围很大，直接线性显示往往看不清弱成分。因此常用 dB 标度：

```text
S_db = 10 * log10(power / reference)
```

或对 magnitude 使用类似的对数压缩。白话解释：dB 把“倍数差异”压成更适合人眼和人耳观察的尺度，让弱但重要的结构可见。

谱图中的常见形状：

- 稳定音高：横向亮线。
- 打击声或瞬态：短时间内跨很多频率的竖向亮带。
- 滑音或 chirp：随时间上升或下降的斜线。
- 噪声：较宽频段的散布能量。
- 谐波乐器音：基频和整数倍频率处出现多条水平线。

#### 2.9 时间-频率折中

这是本章最重要的工程直觉。STFT 不能同时拥有任意精确的时间定位和频率定位。

短窗口：

- 时间定位好，适合观察 transient、onset、鼓点。
- 频率分辨率差，难以区分相近频率。

长窗口：

- 频率分辨率好，适合观察稳定音高、和声、泛音。
- 时间定位差，瞬态会被拉宽，起点不清楚。

例子：

- onset detection 更需要时间精度，所以常用较短窗口或关注谱变化。
- pitch / harmony analysis 更需要频率精度，所以可能使用较长窗口或 log-frequency 表示。
- beat tracking 还需要更长时间尺度上的周期性分析，单个 STFT 帧远远不够。

`hop_length` 也很重要。它决定相邻帧之间的时间间隔：

```text
frame_time[m] = m * hop_length / sr
```

`n_fft` 决定频率 bin 间隔：

```text
bin_frequency[k] = k * sr / n_fft
```

初学者常见错误是只改 `n_fft`，不理解它同时改变了窗口长度、频率分辨率和时间模糊程度。实践中还要区分 `n_fft` 与 `win_length`：有些库允许窗口长度小于 FFT 长度，额外部分通过 zero padding 补齐。zero padding 会让频率轴显示更细，但不等于真正提高了分辨两个相近频率的能力。

#### 2.10 magnitude 与 phase

许多 MIR 特征只使用 magnitude 或 power，因为频率能量分布已经足够支撑很多任务，例如 chroma、MFCC、spectral centroid、spectral contrast、onset strength 等。

但 phase 并不无用。phase 影响波形重建，也用于更高级的频率估计、相位声码器、瞬时频率估计、相位相关 novelty、音频变速和源分离重建。

学习误区：

- “人耳不听相位”是过度简化。相位对波形、瞬态、空间感、重建质量和某些分析方法都可能重要。
- 只要能画出谱图，不代表能从谱图无损回到音频。没有 phase 或 STFT 不一致时，重建会变得困难。

#### 2.11 线性频率、对数频率与音乐感知

普通 STFT 的频率轴是线性的：每个 bin 间隔相同 Hz。但音乐音高更接近对数关系。低频处，20 Hz 的差异可能很大；高频处，20 Hz 可能很小。一个八度对应频率乘以 2，而不是加上某个固定 Hz。

因此很多 MIR 特征会从线性 STFT 进一步转换：

```text
STFT / spectrogram
-> log-frequency spectrogram
-> chroma / CQT / mel spectrogram / MFCC 等
```

对数频率表示更接近音高结构。后续 Chapter 3 的 log-frequency spectrogram 和 chroma 就是从这里自然延伸出来的。

#### 2.12 为什么 Chapter 2 对后续 MIR 重要

后续几乎所有基于音频的 MIR pipeline 都会从 STFT 或某种时间-频率表示开始：

- chroma：从频谱能量映射到 pitch class。
- onset novelty：比较相邻谱帧的能量变化。
- tempogram：对 novelty curve 再做周期性分析。
- audio fingerprint：在谱图中找稳定 spectral peaks。
- HPSS：利用谱图中的水平结构和垂直结构分离 harmonic/percussive。
- melody extraction：在时频图中估计 F0 候选和 salience。
- NMF：把非负谱图矩阵分解成 spectral templates 与 activations。

如果不理解 STFT 参数和谱图含义，后续会出现很多调参误判。例如和弦识别效果差，可能不是 HMM 有问题，而是 STFT 窗口太短导致低频分辨率不足；鼓点检测模糊，可能是窗口太长导致时间定位差；检索鲁棒性差，可能是特征保留了太多录音细节而不是音乐结构。

#### 2.13 实践练习与 librosa 任务思路

1. 画三种视图  
   用 `librosa.load` 读取一段音频，画 waveform、linear-frequency spectrogram、dB spectrogram。观察哪些结构在波形中看不见，但在谱图中清楚。

2. 改变 `n_fft`  
   对同一段音频分别使用 `n_fft=512, 2048, 8192` 计算 STFT。观察鼓点、钢琴音、持续弦乐在时间和频率方向上的变化。

3. 改变 `hop_length`  
   固定 `n_fft`，比较 `hop_length=128, 512, 1024`。观察时间帧数量、图像平滑程度和计算量变化。

4. 观察窗口函数影响  
   对一个稳定正弦波或单音，比较 rectangular window 与 Hann window 的频谱泄漏。可以用 `scipy.signal.get_window` 或 `librosa.stft(window=...)`。

5. 频率 bin 到 Hz  
   用 `librosa.fft_frequencies(sr=sr, n_fft=n_fft)` 查看每个 bin 的频率。手算 `k * sr / n_fft` 验证几个 bin。

6. dB 压缩  
   用 `librosa.amplitude_to_db` 或 `librosa.power_to_db` 把谱图转成 dB。比较线性 magnitude 和 dB 图像的可读性。

7. 谐波观察  
   找一个单音乐器音，观察基频和整数倍频率附近的横线。思考为什么不同乐器演奏同一个音，谱图形状不一样。

8. 瞬态观察  
   找一段鼓声或拍手声，观察谱图中的竖向结构。理解为什么 impulse-like 声音会在很宽频率范围内有能量。

9. log-frequency 思路  
   尝试用 `librosa.cqt` 或 `librosa.feature.melspectrogram` 得到更接近感知的频率轴。比较它和普通 STFT 的差异。

10. phase 初步实验  
    用 `librosa.stft` 得到复数矩阵，分别查看 `np.abs(D)` 和 `np.angle(D)`。再用 `librosa.istft(D)` 重建音频，理解为什么完整复数 STFT 比单独 magnitude 更适合重建。

---

### 两章联动：从表示到特征工程

Chapter 1 让我们知道音乐可以有很多表示；Chapter 2 说明音频表示如何进一步变成频率和时间-频率表示。把两章连起来，可以得到 MIR 的基础处理链：

```text
真实音乐表演
-> audio waveform
-> STFT
-> spectrogram / log spectrogram
-> chroma / novelty / MFCC / fingerprint / salience
-> 对齐、识别、分段、检索、分离等任务
```

同时，符号表示也可以走另一条路：

```text
score / MIDI / MusicXML
-> note events / piano-roll
-> pitch, onset, duration, velocity, voice
-> symbolic analysis 或 audio-symbolic alignment
```

进阶学习时要形成一种习惯：每看到一个 MIR 算法，先问它输入的表示是什么，输出的表示是什么，中间丢掉了什么信息，又保留了什么不变性。表示选错时，模型再复杂也很难补救。

### 初学者到进阶的检查清单

学完本基础篇后，至少应该能回答：

- 乐谱、MIDI、MusicXML、piano-roll、audio waveform、spectrogram 分别是什么。
- 为什么 MIDI 不是音频，乐谱图像不是符号表示。
- frequency、pitch、octave、pitch class、chroma 的区别。
- 为什么真实乐器音通常包含 F0、partials、harmonics。
- DFT 公式里 `n`、`k`、`N`、`X[k]` 分别代表什么。
- 为什么 FFT 是 DFT 的快速算法，不是另一种频谱。
- STFT 为什么需要 window 和 hop size。
- spectrogram 的横轴、纵轴、颜色分别表示什么。
- 为什么短窗口和长窗口各有代价。
- 为什么很多 MIR 特征从 STFT 开始，但不会直接停在 STFT。

### 常见学习误区汇总

- 把音频文件和 MIDI 文件混为一谈。
- 以为谱图就是“音符图”，忽略频率 bin、谐波、噪声和窗函数影响。
- 把 pitch 和 frequency 完全等同。
- 以为 chroma 保留了完整音高，实际它折叠了八度信息。
- 只看 magnitude，完全忘记 phase 在重建和高级分析中的作用。
- 认为 `n_fft` 越大越好，忽略时间定位会变差。
- 认为 zero padding 提高了真实频率分辨率。
- 用同一套 STFT 参数处理所有任务，不根据 onset、pitch、harmony、beat 等目标调整。
- 看到模型效果不好就先换模型，而不是先检查表示、特征、采样率、窗口、归一化和标注定义。

### 小项目建议：Spectrogram Explorer

做一个最小但完整的谱图探索工具，不需要复杂模型：

输入：一段 WAV/MP3 音频。  
输出：waveform、linear spectrogram、dB spectrogram、不同 `n_fft` 的对比图、不同 `hop_length` 的对比图。

核心步骤：

```text
1. librosa.load 读取音频
2. librosa.stft 计算复数 STFT
3. np.abs 得到 magnitude
4. librosa.amplitude_to_db 转 dB
5. librosa.display.specshow 可视化
6. 改变 n_fft / hop_length / window 做对比
```

观察任务：

- 标出明显 onset 在 waveform 和 spectrogram 中的位置。
- 找出稳定音高对应的水平线。
- 对比短窗口与长窗口下的鼓点和持续音。
- 找一段不同乐器单音，观察 partial 分布。
- 解释每一次参数变化导致图像变化的原因。

这个项目完成后，再进入 chroma、DTW、和弦识别、节拍跟踪会顺很多，因为你已经能读懂 MIR 中最常见的底层表示。

---

## 第二篇：特征与对齐：Chapter 3 Music Synchronization

本章讨论的是音乐同步（music synchronization）：给定同一首作品的两种表示或两个版本，自动找出它们在时间上的对应关系。它可能是“音频对乐谱”“音频对 MIDI”“一个录音对另一个录音”，也可能是“同一作品的钢琴版对管弦乐版”。

同步问题的核心不是简单比较两个波形。不同演奏会有不同速度、rubato、音色、力度、混响、装饰音和局部处理。如果直接比较 waveform，两个内容相同但演奏不同的版本常常看起来差异极大。因此 Chapter 3 的主线是：

```text
audio / MIDI / score
-> common feature representation
-> chroma or CENS feature sequence
-> cost matrix
-> dynamic time warping
-> alignment path
```

这条链路包含两个基本思想：

1. 先把原始音乐数据变成对任务有用、对无关变化不敏感的中层特征。
2. 再用序列对齐算法处理不同演奏造成的时间伸缩。

### 1. 音乐同步到底要对齐什么

假设有两个序列：

```text
X = x_1, x_2, ..., x_N
Y = y_1, y_2, ..., y_M
```

每个 `x_n` 和 `y_m` 都是某个时间帧的特征向量。例如它们可以是 12 维 chroma 向量，也可以是更稳健的 CENS 向量。同步要回答：

```text
X 中第 n 帧，对应 Y 中第几帧？
Y 中第 m 帧，对应 X 中第几帧？
```

如果两段音乐速度完全一样，对齐路径大致是一条对角线。但真实音乐通常不是这样：

- 一个版本整体更快，对角线会变陡或变平。
- 某些乐句有 rubato，对齐路径会局部弯曲。
- 某些地方停顿更长，对齐路径会出现水平或垂直拖曳。
- 如果重复段、省略段、即兴段不同，经典 DTW 的单调全局对齐假设可能被破坏。

同步的输出通常不是一个标签，而是一条 alignment path。它把两个时间轴连接起来，可以用于乐谱跟随、跨版本跳转播放、音频到 MIDI 对齐、演奏分析、歌词/字幕同步、版本比较等任务。

### 2. 为什么从 STFT 开始

原始音频是 waveform：

```text
x[t] = 声压随时间变化的采样序列
```

它包含大量细节，但不直接告诉我们“当前有哪些音高或和声”。音乐同步更关心的是旋律与和声进行，而不是录音设备、音色或瞬时相位。因此通常先做 STFT：

```text
audio waveform
-> frame blocking
-> windowing
-> FFT
-> magnitude or power spectrogram
```

STFT 结果是一个时间-频率表示：

```text
S[n, k]
```

其中 `n` 是时间帧，`k` 是线性频率 bin。spectrogram 可以告诉我们每个时间附近哪些频率有能量。

但普通 spectrogram 有两个问题：

1. 频率轴是线性的，而音乐音高感知更接近对数尺度。
2. 同一个音名在不同八度上频率相差很大，但音乐上常常属于同一个 pitch class。

因此 Chapter 3 从 STFT 继续走向 log-frequency spectrogram，再进一步折叠成 chroma。

### 3. Log-Frequency Spectrogram

#### 3.1 线性频率与音乐音高的错位

在线性频率轴上，100 Hz 到 200 Hz 的距离和 1000 Hz 到 1100 Hz 的距离相同，都是 100 Hz。但从音乐听感看：

- 100 Hz 到 200 Hz 是一个八度。
- 1000 Hz 到 1100 Hz 远不到一个八度。

音乐音高更接近对数关系。十二平均律中，相邻半音的频率比固定：

```text
2^(1/12)
```

如果用 MIDI pitch number 表示音高，常用关系是：

```text
F_pitch(p) = 2^((p - 69) / 12) * 440 Hz
```

其中 `p = 69` 对应 A4，即 440 Hz。

#### 3.2 从 spectrogram 到 log-frequency spectrogram

log-frequency spectrogram 的目标是把线性频率 bin 的能量重新分配到音乐音高格点上：

```text
linear-frequency spectrogram
-> pitch-frequency mapping
-> energy pooling around pitch bands
-> log-frequency spectrogram
```

可以把每个音高 `p` 看作一个频带：

```text
lower cutoff: F_pitch(p - 0.5)
center:       F_pitch(p)
upper cutoff: F_pitch(p + 0.5)
```

这个频带大致覆盖以 `p` 为中心的半音范围。然后把落在这个频带附近的 STFT 能量聚合起来，得到：

```text
Y_LF[n, p]
```

其中 `n` 是时间帧，`p` 是音高索引。

直觉上，log-frequency spectrogram 是把“物理频率图”改画成“音乐音高图”。它仍然保留八度信息，例如 C3、C4、C5 会在不同音高行上出现，但行与行之间按半音排列。

#### 3.3 常见实现选择

实际实现时不一定真的从 STFT 后手写映射，也可以使用 Constant-Q Transform（CQT）或类似滤波器组。核心目标一样：让频率轴更贴近音乐音高。

常见参数包括：

- `bins_per_octave`: 每个八度分多少格。12 表示半音分辨率，24 表示四分之一音或半半音级别，36 表示三分之一半音。
- `fmin`: 最低分析频率，常设为 C1、C2 或目标乐器的最低音附近。
- `n_octaves`: 覆盖多少个八度。
- `window length`: 影响频率分辨率和时间分辨率。
- `hop size`: 决定特征帧率。

#### 3.4 高低频的分辨率矛盾

固定窗口 STFT 有一个天然矛盾：

- 长窗口：频率分辨率好，但时间定位差。
- 短窗口：时间定位好，但频率分辨率差。

音乐中低频音符的半音间隔以 Hz 计较小，更需要频率分辨率；高频音符的半音间隔更宽，对频率分辨率要求相对低，但 onset 等瞬态信息需要更好的时间分辨率。因此多分辨率分析、CQT、可变窗口滤波器组在音乐处理中很常见。

### 4. Chroma Feature

#### 4.1 pitch、pitch class 与 chroma

音高 `C3`、`C4`、`C5` 频率不同，但都属于同一个 pitch class：C。chroma 的核心就是忽略八度，只保留十二个音级类别：

```text
C, C#, D, D#, E, F, F#, G, G#, A, A#, B
```

一个 chroma 向量通常是 12 维：

```text
c[n] = [C, C#, D, D#, E, F, F#, G, G#, A, A#, B]
```

每一维表示当前时间帧中这个 pitch class 的能量或显著程度。

#### 4.2 从 STFT 到 chroma 的完整流程

标准流水线可以写成：

```text
audio
-> STFT
-> magnitude / power spectrogram
-> log-frequency spectrogram
-> pitch-class aggregation
-> chromagram
-> compression / normalization / smoothing
```

如果已有 log-frequency spectrogram `Y_LF[n, p]`，那么 chroma 聚合可以理解为：

```text
C[n, c] = sum of Y_LF[n, p] for all p where p mod 12 = c
```

也就是说：

```text
C1, C2, C3, C4, C5 -> C
F#1, F#2, F#3, F#4 -> F#
```

这一步丢掉了八度位置，但增强了和声/旋律轮廓在不同音区、不同乐器之间的一致性。

#### 4.3 为什么 chroma 适合同步

音乐同步通常要对齐“同一作品的音乐内容”，而不是“同一声学录音”。chroma 的优势正好对应这个目标：

- 对八度差异不敏感。
- 对部分音色差异不敏感。
- 对整体响度差异可通过归一化降低影响。
- 对不同配器的和声进行有较强可比性。
- 对同一旋律在不同音区演奏仍能保留相似轮廓。

例如同一段贝多芬主题，一个版本由管弦乐演奏，另一个版本由钢琴演奏，spectrogram 看起来会差很多，但 chroma 中的主导音级变化可能仍然相似。

#### 4.4 chroma 丢失了什么

chroma 的强大来自抽象，但抽象一定伴随信息损失：

- 丢失八度信息。
- 丢失大部分音色信息。
- 弱化力度和声学细节。
- 难以区分同一 pitch class 在不同音区的作用。
- 对打击乐、非定音声音、强噪声不敏感或不稳定。
- 对复杂复调中的泛音、低音、旋律线可能混在一起。

因此 chroma 适合 tonal/harmonic content，不适合所有 MIR 任务。比如鼓点识别、音色分类、声源分离，不应只依赖 chroma。

### 5. Chroma 的稳健化与变体

原始 chroma 往往太细、太敏感。为了用于同步、匹配和版本识别，通常还要做增强处理。

#### 5.1 Log Compression

spectrogram 或 chroma 的能量范围可能很大。强能量分量会掩盖弱但有意义的分量。log compression 的作用是压缩动态范围：

```text
large values become less dominant
small but relevant values become more visible
```

常见形式类似：

```text
log(1 + gamma * x)
```

`gamma` 越大，压缩越强。压缩太弱，强泛音或强低音会支配特征；压缩太强，噪声和无关成分也会被抬起来。

#### 5.2 Normalization

归一化用于降低整体响度影响。常见做法是对每个时间帧的 12 维向量做范数归一化：

```text
c[n] <- c[n] / ||c[n]||
```

常用范数：

- L1 normalization：总和归一，强调比例分布。
- L2 normalization：适合余弦距离或点积相似度。
- max normalization：让最大维为 1，简单但可能受单个异常峰影响。

注意：静音或极弱能量帧不能盲目归一化。否则噪声会被放大成看似有意义的 chroma 模式。实践中通常设置能量阈值，对低能量帧保留零向量或做特殊处理。

#### 5.3 Tuning Correction

真实录音可能不是标准 A4=440 Hz，也可能整体偏高或偏低几十 cents。如果 log-frequency bins 对准标准半音，而录音整体偏调，能量会泄漏到相邻音级，chroma 会变模糊。

常见策略：

- 估计全局调音偏移，再修正频率映射。
- 使用更细的 log-frequency 分辨率，如每半音 2 或 3 个 bin。
- 在聚合到 chroma 前做局部加权。

如果发现 chromagram 中每个音都拖着相邻音级一起亮，除了考虑混响和泛音，也要检查 tuning。

#### 5.4 Smoothing

帧级 chroma 可能受瞬态、装饰音、噪声和短时估计误差影响。时间平滑可以增强稳定结构：

```text
chroma sequence
-> moving average / median filter
-> smoother chroma sequence
```

平滑窗口越大，特征越稳，但时间定位越差。同步任务通常可以接受适度平滑，因为目标是对齐音乐结构，而不是精确到每个采样点。

#### 5.5 Downsampling

很多同步任务不需要每秒几十到上百帧的特征。先平滑再降采样可以：

- 减少计算量。
- 抑制局部噪声。
- 让 DTW 的 cost matrix 更小。
- 更关注和声/旋律轮廓。

但降采样太狠会丢失快速音符和短乐句。对于古典音乐快速段落、复杂装饰音，帧率过低会明显伤害对齐。

#### 5.6 Quantization

量化会把连续 chroma 值变成少数几个等级，例如：

```text
0, 1, 2, 3, 4
```

这样可以降低微小幅度差异的影响，突出“哪些 pitch class 重要”。量化常用于更稳健的匹配特征，但会牺牲细节。

#### 5.7 CENS: Chroma Energy Normalized Statistics

CENS 可以理解为“更稳健、更粗粒度的 chroma”。它的典型思路是：

```text
chroma
-> frame-wise normalization
-> quantization
-> temporal smoothing / statistics over a window
-> downsampling
-> CENS sequence
```

名字里的含义：

- Chroma：仍然基于 pitch class。
- Energy Normalized：降低总体能量差异。
- Statistics：不是只看单帧，而是看一段时间内的统计分布。

CENS 的目标是牺牲短时细节，换取对音色、力度、局部装饰、录音差异和小幅时间扰动的稳健性。它非常适合同步、音频匹配、版本识别等任务。

一个实用理解是：

```text
raw chroma 适合看细节
CENS 适合做稳健匹配
```

如果要对齐两个不同演奏版本，CENS 通常比未经处理的 chroma 更稳定；如果要精确定位到某个快速音符，过度平滑的 CENS 可能太迟钝。

### 6. Cost Matrix

有了两个特征序列：

```text
X = x_1, x_2, ..., x_N
Y = y_1, y_2, ..., y_M
```

下一步是计算局部距离：

```text
C[n, m] = cost(x_n, y_m)
```

这会得到一个 `N x M` 的 cost matrix。每个格子表示“X 的第 n 帧”和“Y 的第 m 帧”有多不像。值越小，越可能对应。

#### 6.1 常见 local cost

对 chroma/CENS，常用距离包括：

- Euclidean distance：直观，受幅度影响较明显。
- Cosine distance：关注方向，常配合 L2 normalization。
- Manhattan distance：对个别异常维度有时更稳。
- Binary distance：用于二值化或量化后的 chroma。

余弦距离的直觉是：两个 12 维向量的能量分布方向是否相似，而不太关心整体强度。对归一化 chroma，这通常是合理选择。

#### 6.2 cost matrix 怎么看

把 cost matrix 画成图时：

- 横轴：序列 X 的时间。
- 纵轴：序列 Y 的时间。
- 颜色越深或越亮表示成本越低，具体取决于 colormap。

如果两个序列非常相似且速度接近，会看到一条低成本对角带。如果一个版本更快，低成本路径会偏离主对角线。如果局部 rubato 明显，低成本路径会弯曲。

不要只看单个格子。同步依赖的是一条连续路径。某个格子低成本可能只是偶然相似，只有形成连续低成本通道，才说明两个片段在时间上稳定对应。

#### 6.3 cost matrix 的常见图像模式

典型模式：

- 清晰对角低成本带：特征和参数大致正确。
- 对角线断断续续：有噪声、特征不稳、局部装饰或配器差异大。
- 多条平行低成本线：音乐中有重复段或相似乐句。
- 整张图对比度很低：特征区分力不足或压缩/归一化过度。
- 整张图很随机：可能不是同一作品，或 tuning、转调、帧率、特征提取出错。
- 大块低成本区域：特征过于粗糙，很多时间点互相都像。

可视化 cost matrix 是调试同步系统的第一工具。

### 7. Dynamic Time Warping

#### 7.1 DTW 解决什么问题

DTW 解决的是：

```text
两个序列内容相似，但时间轴伸缩不同，如何找出整体最优对齐？
```

它不是用一条固定直线对齐，而是允许路径在矩阵中弯曲。

#### 7.2 Warping Path

一个 warping path 是 cost matrix 中的一串格子：

```text
P = (p_1, p_2, ..., p_L)
p_l = (n_l, m_l)
```

每个格子 `(n, m)` 表示把 `x_n` 和 `y_m` 对齐。

经典 DTW 通常要求路径满足：

- Boundary condition：从 `(1, 1)` 开始，到 `(N, M)` 结束。
- Monotonicity：时间不能倒退。
- Step size condition：每一步只能向右、向上或右上走。
- Continuity：不能跳过太远的区域。

常见步长集合是：

```text
(1, 0), (0, 1), (1, 1)
```

含义：

- `(1, 1)`：两个序列一起前进，正常匹配。
- `(1, 0)`：X 前进，Y 暂停；表示 X 中多个帧对应 Y 的一个帧。
- `(0, 1)`：Y 前进，X 暂停；表示 Y 中多个帧对应 X 的一个帧。

这就是 DTW 能处理局部速度变化的原因。

#### 7.3 动态规划直觉

如果暴力枚举所有可能路径，数量会爆炸。DTW 使用动态规划：把“到达当前格子的最优路径”分解成“到达前驱格子的最优路径 + 当前格子的代价”。

定义 accumulated cost matrix：

```text
D[n, m] = 到达 (n, m) 的最小累计成本
```

递推直觉：

```text
D[n, m] = C[n, m] + min(
    D[n-1, m],
    D[n, m-1],
    D[n-1, m-1]
)
```

也就是说，想知道到 `(n, m)` 的最佳路线，只需要看它可能来自的几个前驱位置中谁最好。

最后：

```text
D[N, M]
```

就是两个完整序列的 DTW 距离。然后从 `(N, M)` 反向回溯，每次走向贡献最小的前驱格子，就得到 optimal warping path。

#### 7.4 一个小例子

假设两个序列内容相同，但第二个序列中某个音被拉长。cost matrix 中低成本区域不会是一条完美对角线，而会出现一小段水平或垂直走势。DTW 会用水平/垂直步把这个“拉长”吸收掉，使前后内容仍然对齐。

这和现实演奏很像：一个演奏者在某个乐句末尾稍微放慢，后面又回到原速。线性时间缩放无法处理这种局部变化，而 DTW 可以。

### 8. DTW 的约束与参数

#### 8.1 Step Size

步长集合决定路径可以怎样弯曲。最简单的 `(1,0), (0,1), (1,1)` 很灵活，但也可能产生过多水平/垂直段，让一个很长片段对齐到另一个很短片段。

更严格的步长条件可以限制局部斜率。例如只允许某些组合步，避免路径太平或太陡。这相当于告诉算法：“两个版本速度可以不同，但不能差得离谱。”

#### 8.2 Global Constraint

如果知道两个序列大致同步，可以限制搜索区域，常见方法包括：

- Sakoe-Chiba band：只允许路径在主对角线附近一定宽度内。
- Itakura parallelogram：允许中间区域更宽、边界更受限。

优点：

- 降低计算量。
- 减少离谱路径。
- 提高对噪声的稳健性。

风险：

- 如果真实路径超出约束区域，算法会被迫给出错误对齐。

#### 8.3 Subsequence 与 Open-End 变体

经典 DTW 假设两个序列从头到尾完整对应。但实际任务经常不同：

- 查询片段只对应数据库音频的一小段。
- 现场演奏还没结束，需要在线对齐。
- 音频开头或结尾有沉默、掌声、引子。

这时可使用 subsequence DTW、open-begin/open-end DTW 或在线 DTW。它们改变边界条件，让路径不一定从 `(1,1)` 到 `(N,M)`。

#### 8.4 复杂度

经典 DTW 需要计算 `N x M` 个格子，时间和空间复杂度通常是：

```text
O(NM)
```

如果两个序列很长，这会很重。常见优化：

- 降采样特征。
- 使用 CENS 等低帧率特征。
- 使用全局约束带。
- 多尺度 DTW：先在粗尺度找路径，再在细尺度局部精修。
- 只保留必要行/列降低空间占用。

### 9. Alignment Path 怎么解释

alignment path 是同步结果的核心。

如果横轴是参考版本时间，纵轴是演奏版本时间：

- 路径斜率接近 1：两个版本局部速度接近。
- 路径更陡：纵轴版本相对更慢，花了更多时间。
- 路径更平：纵轴版本相对更快。
- 水平段：参考版本在前进，而演奏版本几乎停留。
- 垂直段：演奏版本在前进，而参考版本几乎停留。
- 突然跳跃或断裂：可能有重复、省略、结构差异，或特征匹配失败。

从路径还可以估计局部 tempo。若参考时间轴以 beat 表示，演奏时间轴以 seconds 表示，路径斜率变化就能反映演奏速度变化。

### 10. 常见参数建议

下面不是唯一正确配置，而是初学者可作为起点的实践范围。

#### 10.1 STFT / CQT

- 采样率：`22050 Hz` 或 `44100 Hz`。
- STFT window：`2048` 到 `8192`，和声分析可偏长。
- hop size：`512`、`1024` 或按目标帧率设置。
- CQT bins per octave：`12` 常用于 chroma，`24` 或 `36` 有助于 tuning/细分。
- 频率范围：覆盖目标音乐主要音域，避免过多低频噪声或超高频噪声。

#### 10.2 Chroma

- 维度：通常 12。
- 压缩：适度 log compression。
- 归一化：L2 或 L1，低能量帧单独处理。
- 平滑：几百毫秒到数秒，取决于是否追求稳健匹配。
- 降采样：同步/匹配可降到每秒 5 到 20 帧；精细对齐可更高。

#### 10.3 CENS

- 先归一化，再量化。
- 平滑窗口可比 raw chroma 更长。
- 输出帧率可低一些，用于稳健粗对齐。
- 如需精细时间定位，可先用 CENS 粗对齐，再用更高分辨率 chroma 局部精修。

#### 10.4 DTW

- local cost：chroma 常用 cosine distance。
- step size：从经典三步开始，再根据路径是否过度弯曲调整。
- global band：如果两段速度差不大，可加 Sakoe-Chiba band。
- path normalization：比较不同长度序列时，累计成本最好按路径长度归一化。
- silence handling：静音帧最好标记或降低权重。

### 11. 可视化应该怎么看

#### 11.1 Spectrogram

看这些问题：

- 是否能看到清晰谐波线？
- 是否有强低频噪声？
- 是否有大量打击乐瞬态？
- window 是否太短导致频率糊掉？
- window 是否太长导致 onset 拖尾？

#### 11.2 Log-Frequency Spectrogram

看这些问题：

- 音高轨迹是否沿半音网格出现？
- 相邻半音是否严重泄漏？
- 低频是否分辨不清？
- 高频是否时间定位过差？
- tuning 是否整体偏离格点？

#### 11.3 Chromagram

看这些问题：

- 12 个 pitch class 是否形成清晰模式？
- 和声变化是否能看出块状或带状结构？
- 是否所有维度都差不多亮，说明特征过糊或噪声太大？
- 是否只有低音对应 pitch class 特别强，说明低频支配过重？
- 两个版本的 chroma 是否在宏观轮廓上相似？

#### 11.4 Cost Matrix

看这些问题：

- 是否存在连续低成本通道？
- 是否有多条候选路径，对应重复段？
- 低成本通道是否被噪声打断？
- 主对角线附近是否合理？
- 是否需要转调处理或更稳健特征？

#### 11.5 Alignment Path

看这些问题：

- 路径是否单调连续？
- 是否出现长水平/垂直段？
- 是否过度贴近约束边界？
- 是否穿过低成本区域？
- 路径斜率是否符合音乐速度直觉？

如果路径穿过高成本区域，说明 DTW 是被约束或边界条件硬推过去的，不代表真实对应。

### 12. 实践练习

#### 练习 1：画出三个表示

选一段 20 到 40 秒的 tonal music，画：

```text
linear spectrogram
log-frequency spectrogram or CQT
chromagram
```

观察同一段音乐在三种表示中的差异。重点回答：

- 哪个表示最接近物理声音？
- 哪个表示最接近音高结构？
- 哪个表示最适合比较两个不同乐器版本？

#### 练习 2：改变 STFT 参数

固定同一段音频，改变 window length 和 hop size。观察：

- 窗口变长时，音高线是否更清楚？
- onset 是否更模糊？
- chroma 是否更稳定？
- cost matrix 是否更清晰？

#### 练习 3：手写 chroma 聚合

不用库函数的 chroma 接口，只使用一个 log-frequency spectrogram。把音高 `p` 按 `p mod 12` 聚合成 12 维 chroma。然后和库函数输出比较。

目标不是完全复现库，而是理解：

```text
pitch axis -> pitch class axis
```

#### 练习 4：比较 raw chroma 和 CENS

对两段同曲不同演奏提取：

```text
raw chroma
compressed normalized chroma
CENS
```

分别画 cost matrix。观察哪一种低成本路径更连续。再听对应音频，判断平滑是否损失了你关心的细节。

#### 练习 5：实现最小 DTW

输入两个短矩阵序列，自己实现：

```text
1. cost matrix
2. accumulated cost matrix
3. backtracking
4. warping path plot
```

先用一维数字序列验证，再换成 12 维 chroma。

#### 练习 6：路径斜率与 tempo

找两个不同速度的演奏版本，做 DTW 对齐。画出 alignment path，并标记：

- 哪些地方路径变陡？
- 哪些地方路径变平？
- 这些位置听起来是否对应 ritardando、accelerando 或停顿？

#### 练习 7：故意制造错误

尝试以下破坏条件：

- 不做归一化。
- 过度平滑。
- hop size 过大。
- 使用错误 tuning。
- 把两首不同歌拿来对齐。
- 给 DTW 加太窄的约束带。

观察每种错误如何体现在 chromagram、cost matrix 和 path 中。

### 13. 常见错误

#### 错误 1：直接比较 waveform

同一首曲子的不同演奏，波形几乎不会逐点一致。除非做的是同一录音的识别，否则 waveform 不是同步的合适表示。

#### 错误 2：把 chroma 当作音符转录

chroma 不是 transcription。它不会告诉你具体哪个八度、哪个声部、哪个乐器在演奏。它只是 pitch-class energy 的中层表示。

#### 错误 3：忽略 tuning

整体偏高或偏低的录音会导致 chroma 泄漏。同步效果差时，不要只调 DTW，也要检查前端特征。

#### 错误 4：盲目归一化静音帧

静音或低能量帧归一化后可能变成随机强模式，严重污染 cost matrix。

#### 错误 5：平滑越多越好

平滑能增强稳健性，但会降低时间分辨率。过度平滑会让短音符、快速和声变化和局部对齐点消失。

#### 错误 6：DTW 路径好看就认为特征正确

DTW 总会在允许区域内找一条最优路径。即使两段不相关，它也能给出路径。必须结合 cost matrix 的低成本通道、路径成本、音频听感和可视化判断。

#### 错误 7：不处理转调

如果两个版本整体转调，chroma 会循环平移。例如升高一个半音，C 维能量会移动到 C#。这时需要测试 12 种 chroma shift，或使用转调不变匹配。

#### 错误 8：把重复结构误认为错误

多条低成本斜线可能不是算法坏了，而是音乐本身有重复乐句。同步系统需要根据任务决定是做全局对齐、局部匹配，还是允许结构跳转。

#### 错误 9：约束带太窄

Sakoe-Chiba band 能加速并抑制离谱路径，但真实演奏差异如果超出带宽，正确路径会被排除。

#### 错误 10：只看最终 DTW distance

单个距离值很难解释。应该同时看：

- cost matrix
- accumulated cost matrix
- warping path
- path length normalized cost
- 对齐后的音频或事件检查

### 14. 本章应该形成的工程直觉

音乐同步不是“DTW 一招解决”。DTW 只是后端对齐器，真正决定效果的是前端表示和约束设计。

可以用下面的问题检查一个同步方案是否合理：

1. 输入之间主要差异是什么？速度、音色、配器、转调、结构，还是噪声？
2. 需要保留什么信息？旋律、和声、onset、节拍，还是音色？
3. 当前特征对哪些变化不敏感？这种不敏感是否符合任务？
4. local cost 是否匹配特征性质？
5. DTW 约束是否符合真实速度变化范围？
6. 可视化中是否存在连续低成本路径？
7. 输出路径能否被音乐听感解释？

对于 Chapter 3，最重要的一句话是：

```text
同步的本质，是先用 chroma/CENS 把不同音乐表示投影到可比较的中层特征空间，再用 DTW 在 cost matrix 中寻找一条符合时间顺序和局部伸缩约束的最优路径。
```

### 15. 与后续章节的连接

Chapter 3 的方法会在后续章节反复出现：

- Chapter 4 结构分析会继续使用 chroma 和相似度矩阵。
- Chapter 5 和弦识别会把 chroma 作为核心观测特征。
- Chapter 6 节拍跟踪也会使用动态规划思想。
- Chapter 7 音频匹配和版本识别会使用 CENS、局部匹配和对齐。
- Chapter 8 中 score-informed 分解也依赖同步结果把乐谱信息映射到音频时间轴。

所以本章不仅是“音乐同步”一章，也是全书中层特征、相似度矩阵和动态规划思想的第一次集中训练。

---

## 第三篇：结构与和弦：Chapter 4 + Chapter 5

> 适用对象：已经理解 waveform、spectrogram、chroma、DTW 基本概念的读者。  
> 本草稿面向从初学者到进阶学习者，不逐字摘录原书，而是把 Chapter 4 和 Chapter 5 的核心思想整理成可复习、可实现、可调试的中文讲义。

### 0. 本篇总览

这一篇连接两个高度相关的 MIR 任务：

```text
Chapter 4: 从相似关系中发现音乐结构
Chapter 5: 从和声特征中识别随时间变化的和弦
```

它们共享一条重要主线：

```text
audio
-> feature representation
-> similarity / probability model
-> temporal structure
-> labels or segments
-> evaluation
```

Chapter 4 的输出通常是“段落边界”和“段落关系”，例如：

```text
Intro | Verse | Chorus | Verse | Chorus | Outro
A1    | B1    | C1     | B2    | C2     | D
```

Chapter 5 的输出通常是“逐时间的和弦标签”，例如：

```text
0.0s - 2.0s: C
2.0s - 4.0s: G
4.0s - 6.0s: Am
6.0s - 8.0s: F
```

二者都不是“直接听出答案”的问题，而是先构造合适的中层表示，再在表示上做推断。结构分析常用 SSM、novelty curve、scape plot；和弦识别常用 chroma、模板匹配、HMM、Viterbi。

---

## Chapter 4. Music Structure Analysis

### 4.1 本章解决什么问题

音乐不是随机声音。一个作品通常由层级结构组织起来：音符组成动机，动机组成乐句，乐句组成段落，段落进一步组成整首作品的宏观布局。

结构分析要回答：

- 哪些时间段属于同一类材料？
- 哪些位置是结构边界？
- 哪些片段重复出现？
- 哪个短片段最能代表整首歌？
- 当前结构是从和声、音色、节奏、旋律还是能量变化中体现出来的？

常见结构标签包括：

- 古典音乐：exposition、development、recapitulation、theme、variation。
- 流行音乐：intro、verse、pre-chorus、chorus、bridge、solo、outro。
- 抽象标签：A、B、A'、C，或 A1、A2、B1、B2。

结构分析不是单纯的切分。切分只问“边界在哪里”；结构分析还问“切出来的段落之间有什么关系”。例如 `A1B1A2B2A3` 表示 A 类材料重复了三次，B 类材料重复了两次。

### 4.2 三个基本原则：repetition、homogeneity、novelty

结构分析常围绕三个互补原则。

#### 4.2.1 Repetition：重复

重复是音乐结构最强的线索之一。副歌重复、主题再现、动机模进、段落反复，都能在特征序列中产生相似模式。

重复不等于完全复制。真实音乐中的重复可能带有：

- 转调：同一旋律或和声关系整体升高/降低。
- 变速：同一材料演奏速度不同。
- 配器变化：第一次钢琴，第二次弦乐。
- 装饰音变化：旋律骨架相同但细节不同。
- 局部删改：只重复主题的一部分。

因此，结构分析需要“足够抽象”的特征。例如 chroma 对八度和部分音色变化较稳健，适合找和声/旋律轮廓的重复；MFCC 更关注音色，适合找配器或音色段落。

#### 4.2.2 Homogeneity：同质性

同质性指一个时间段内部在某个音乐维度上相对稳定。例如：

- 一段都在 G minor 附近。
- 一段都由人声和吉他主导。
- 一段都是密集鼓点。
- 一段都保持相似 tempo 或 groove。

如果某段内部特征彼此相似，在 SSM 中往往形成方块状结构。基于同质性的分割适合找“内部一致”的段落，但不一定能识别跨段重复关系。

#### 4.2.3 Novelty：新异性

novelty 指当前位置前后发生明显变化。比如：

- verse 进入 chorus。
- 弦乐进入铜管。
- minor 转 major。
- 鼓组突然加入。

novelty-based segmentation 的核心直觉是：

```text
边界前后越不相似，该位置越可能是结构边界。
```

它适合边界检测，但不直接告诉你边界两侧属于什么标签。

### 4.3 特征选择：你想看到哪一种“结构”

结构不是唯一的。使用不同特征，会看到不同结构。

| 特征 | 更容易看到的结构 | 容易忽略的内容 |
| --- | --- | --- |
| chroma | 和声、调性、旋律轮廓重复 | 音色、配器、鼓点细节 |
| MFCC / spectral features | 音色、配器、声部密度 | 具体和弦、转调关系 |
| onset / rhythm features | 节奏型、打击模式 | 和声内容 |
| tempogram | tempo、周期性、律动变化 | 音高与音色 |
| energy / loudness | 强弱、段落爆发 | 音乐语义较粗糙 |

因此，结构分析开始前要先问：

```text
我想根据什么来分段？
```

如果目标是流行歌副歌检测，chroma 和 timbre 都可能重要。副歌往往和声材料重复，同时音色、密度、响度也更突出。单一特征可能只看到一部分结构。

### 4.4 Self-Similarity Matrix（SSM）

SSM 是 Chapter 4 的核心工具。

给定特征序列：

```text
X = x1, x2, ..., xN
```

其中每个 `xi` 是某一帧或某一拍的特征向量。SSM 比较所有时间点两两之间的相似度：

```text
S[i, j] = similarity(xi, xj)
```

如果用距离，也可以先得到 cost matrix，再转换为 similarity。常见相似度包括：

- dot product
- cosine similarity
- negative Euclidean distance
- Gaussian kernel similarity

#### 4.4.1 如何阅读 SSM

SSM 是一个 `N x N` 矩阵，横轴和纵轴都是时间。

你需要掌握几种视觉模式：

- 主对角线：每个时间点和自身比较，通常最大。
- 平行于主对角线的亮线：某段材料在另一处重复出现。
- 方块：某个区间内部高度相似，说明该段在某个特征维度上同质。
- 方块之间的断裂：可能是结构边界。
- 网格状重复：多个段落互相相似，例如多次 verse/chorus。

典型例子：

```text
音乐结构: A B A B C

SSM 中可能出现：
- A1 与 A2 之间有斜向亮线或矩形相似区域
- B1 与 B2 之间也有亮线
- C 与其他段落相似度低
```

#### 4.4.2 路径结构与块结构

SSM 中有两类重要结构：

```text
path-like structure: 重复关系
block-like structure: 同质段落
```

路径结构常用于 repetition-based analysis。若 `[t1:t2]` 与 `[t3:t4]` 是相似片段，就会出现从 `(t1,t3)` 到 `(t2,t4)` 附近的斜线路径。

块结构常用于 homogeneity-based analysis。若 `[t1:t2]` 内部特征稳定，则该区间与自身互相比较形成亮方块。

同一首歌可能在 chroma SSM 中路径明显，在 MFCC SSM 中方块明显。这不是矛盾，而是说明不同音乐维度给出了不同结构证据。

### 4.5 SSM 的增强策略

真实 SSM 通常很脏：噪声、局部演奏变化、伴奏花样、短暂经过音都会干扰结构图。增强策略的目标是让关心的结构更清楚。

#### 4.5.1 平滑与降采样

先对特征序列做时间平滑，再降低帧率，可以突出宏观结构。

```text
frame-level chroma at 10 Hz
-> smoothing over several frames
-> downsample to 1-2 Hz
-> compute SSM
```

优点：

- 减少短时噪声。
- 减少计算量。
- 让段落级重复更明显。

代价：

- 边界时间定位变粗。
- 短小动机可能被抹掉。
- 如果平滑窗口过大，verse/chorus 的入口会被拖糊。

#### 4.5.2 对角线平滑

如果两个片段是连续重复，它们在 SSM 中形成斜线。沿对角线方向平滑可以增强这种路径。

直觉：

```text
如果 S[i,j], S[i+1,j+1], S[i+2,j+2] 连续都高，
比单个孤立高相似点更可信。
```

对角线平滑适合找相同速度下的重复。

#### 4.5.3 Tempo-invariant smoothing

如果重复片段速度不同，路径斜率不一定等于 1。tempo-invariant smoothing 会考虑多种斜率，相当于允许重复材料以不同速度出现。

适用场景：

- 古典演奏有 rubato。
- 现场版本速度不同。
- 同一主题在不同段落被拉长或压缩。

代价是参数更多，计算更复杂，也更容易把偶然相似误认为重复。

#### 4.5.4 Transposition invariance

如果使用 chroma，转调会表现为 chroma 向量循环移位。例如整体升高 2 个半音，chroma 的 12 维能量也整体循环移 2 格。

转调不变比较可以写成：

```text
similarity_transposition_invariant(x, y)
= max over shift k similarity(x, shift(y, k))
```

这可以找出“同一材料在不同调上出现”的重复。代价是可能把不同功能的和声关系混在一起，降低调性信息的辨别力。

#### 4.5.5 Thresholding

阈值化只保留强相似关系：

```text
if S[i,j] < threshold:
    S[i,j] = 0
```

或每行只保留 top-k 相似点。它能让结构图更稀疏、更清楚，但阈值过高会丢掉弱重复，阈值过低又无法去噪。

### 4.6 结构分割

结构分割的输出是一组边界：

```text
b0=0, b1, b2, ..., bK=end
```

形成时间段：

```text
[b0:b1], [b1:b2], ..., [bK-1:bK]
```

分割方法可以来自三类证据。

#### 4.6.1 基于 novelty 的边界

这是最常见的入门方法。

流程：

```text
audio
-> feature sequence
-> SSM
-> checkerboard kernel convolution along diagonal
-> novelty curve
-> peak picking
-> boundaries
```

checkerboard kernel 的直觉是：边界附近的 SSM 局部看起来像棋盘。

```text
左上：边界前内部相似，高
右下：边界后内部相似，高
右上/左下：边界前后互相比，低
```

当这个棋盘模式和 SSM 局部高度匹配时，novelty 值高，说明这里可能是边界。

#### 4.6.2 kernel size 的影响

kernel size 控制你寻找的变化尺度。

- 小 kernel：敏感于短时变化，如小乐句、局部音色变化。
- 大 kernel：敏感于段落级变化，如 verse 到 chorus。

常见错误是使用一个固定 kernel 期待找到所有层级边界。音乐结构是多尺度的，四小节边界、副歌入口、整段再现可能同时存在。

#### 4.6.3 Peak picking

novelty curve 只是变化强度曲线，最终边界还要峰值选择。

peak picking 需要考虑：

- 峰值是否超过阈值。
- 相邻峰之间最小距离。
- 是否保留 top-k 个峰。
- 是否根据节拍或小节网格吸附。

如果峰太多，分割碎片化；峰太少，漏掉重要边界。

### 4.7 Audio Thumbnailing

audio thumbnailing 的目标是找一个短片段，作为整首音乐的代表。

它不是找“最响的一段”或“第一段副歌”这么简单。一个好 thumbnail 通常应满足：

- 重复出现。
- 覆盖音乐的核心材料。
- 长度适中。
- 不只是噪声造成的偶然相似。

基本流程：

```text
compute SSM
-> search candidate segment alpha
-> find its non-overlapping repetitions
-> compute fitness(alpha)
-> choose alpha with maximal fitness
```

#### 4.7.1 fitness 的直觉

一个片段的 fitness 高，通常意味着：

- 它能在 SSM 中找到清楚的重复路径。
- 重复片段之间不大量重叠。
- 这些重复覆盖了音乐中较大比例的时间。
- 片段长度不靠极短投机取巧。

如果候选片段太短，可能任何地方都有偶然相似；如果太长，又很难完整重复。因此实践中常设置最小长度，例如至少 5 秒、10 秒或若干小节。

#### 4.7.2 Scape plot

scape plot 用二维图显示所有候选片段的质量：

```text
横轴：片段中心位置
纵轴：片段长度
颜色：fitness
```

它是理解 thumbnailing 的好工具，因为它同时展示不同尺度上的重复结构。

读法：

- 底部表示很短片段。
- 顶部表示很长片段。
- 高亮区域表示“这个中心和长度的片段很适合做 thumbnail”。

如果多个尺度都有高 fitness，说明这首歌可能有层级重复：短动机、乐句、副歌都重复。

### 4.8 结构分析评价

结构分析评价很难，因为“正确答案”本身不唯一。两个专家可能一个按大段标注：

```text
A B A B C
```

另一个按小乐句标注：

```text
a a b c | d d e f | a a b c | ...
```

评价前必须明确任务目标。

#### 4.8.1 Precision、Recall、F-measure

基础定义：

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F         = 2PR / (P + R)
```

含义：

- precision 高：预测出来的多数是对的。
- recall 高：参考答案中的多数被找到了。
- F-measure：二者折中，偏向较小者。

#### 4.8.2 Boundary evaluation

边界评价只关心“边界是否找对”。因为结构边界允许轻微误差，通常设置 tolerance：

```text
|estimated_boundary - reference_boundary| <= tau
```

常见 tolerance 是 0.5 秒、1 秒、3 秒，具体取决于任务尺度。

注意：

- tolerance 越大，分数越宽松。
- 如果算法输出大量边界，recall 可能高但 precision 低。
- 如果算法只输出几个大边界，precision 可能高但 recall 低。

#### 4.8.3 Labeling evaluation

标签评价关心“哪些时间点属于同一结构类别”。一种思路是比较成对时间点：

```text
参考中 i 和 j 是否同标签？
预测中 i 和 j 是否同标签？
```

这种评价不只看边界，还看段落关系。例如两个副歌是否都被标成同一类。

#### 4.8.4 Thumbnail evaluation

thumbnail 评价比较估计片段与参考 thumbnail family 的重叠。

如果参考认为所有 verse 都可作为 thumbnail，则估计片段只要与其中一个 verse 高度重叠，就应得高分。

可以计算：

```text
P = overlap / estimated_length
R = overlap / reference_length
F = 2PR / (P + R)
```

再对所有参考 thumbnail 取最大 F。

### 4.9 Chapter 4 实践练习

#### 练习 1：手工阅读 SSM

选择一首结构清楚的流行歌：

```text
audio -> chroma -> SSM
```

观察：

- 主对角线之外是否有斜线？
- verse 之间是否相似？
- chorus 之间是否相似？
- bridge 是否与其他段落低相似？

再用 MFCC 重新画 SSM，比较 chroma SSM 和 MFCC SSM 的差异。

#### 练习 2：novelty 分割

实现：

```text
1. 提取 chroma 或 MFCC
2. 计算 SSM
3. 用 checkerboard kernel 得到 novelty curve
4. peak picking 得到边界
5. 与手工标注比较
```

调整：

- kernel size
- smoothing length
- peak threshold
- minimum peak distance

记录这些参数如何影响过分割和欠分割。

#### 练习 3：audio thumbnailing 小实验

不用完整实现原书的优化算法，也可以做简化版：

```text
1. 枚举候选片段长度：5s, 10s, 15s, 20s
2. 对每个候选片段，计算它与整首歌各位置的相似度
3. 找非重叠高相似匹配
4. 用覆盖率和平均相似度构造简化 fitness
5. 选择最高者
```

目标不是一开始就做最优算法，而是理解“代表片段 = 重复 + 覆盖 + 长度约束”。

### 4.10 Chapter 4 常见错误

1. 把结构分割当作唯一答案问题。  
   音乐结构有多层级，评价必须说明尺度。

2. 只用一种特征就断言结构。  
   chroma 看和声结构，MFCC 看音色结构，二者可能不同。

3. 平滑过度。  
   图看起来干净了，但边界和短重复也被抹掉。

4. 忽视采样率和时间单位。  
   SSM 的 index 不等于秒，必须清楚 feature rate。

5. novelty peak 不等于音乐边界。  
   它只是变化强度，强鼓点、短暂停顿、噪声也可能产生峰。

6. 看到斜线就以为是重复段。  
   短斜线可能只是局部相似，不一定有结构意义。

7. 忽视 intro/outro、静音、掌声。  
   真实录音中这些部分会显著影响 SSM 和 novelty。

---

## Chapter 5. Chord Recognition

### 5.1 本章解决什么问题

和弦识别要从音频中估计随时间变化的和声标签：

```text
audio waveform
-> chroma features
-> chord labels over time
```

典型输出：

```text
Time      Chord
0-2s      C
2-4s      G
4-6s      Am
6-8s      F
```

它比“检测同时响了哪些音”更复杂。原因是：

- 和声是听觉和音乐语境形成的解释，不只是物理频率集合。
- 有些音是经过音、辅助音、延留音，不属于当前和弦。
- 分解和弦的音不一定同时响，但听者仍会整合成和声。
- 同一个 chroma 分布可能对应多个和弦解释。
- 和弦标签体系本身有不同粒度：major/minor triads、seventh chords、slash chords、no chord 等。

入门时通常先做 24 类三和弦：

```text
12 major: C, C#, D, ..., B
12 minor: Cm, C#m, Dm, ..., Bm
```

### 5.2 基础和声理论

#### 5.2.1 Pitch class 与 chroma

和弦识别通常不关心 C3、C4、C5 的八度差异，而关心它们都属于 pitch class C。

chroma 是 12 维 pitch-class 能量：

```text
C, C#, D, D#, E, F, F#, G, G#, A, A#, B
```

它天然适合和弦，因为和弦名称也主要由 pitch class 关系定义。

#### 5.2.2 音程

音程是两个音高之间的距离。在十二平均律中，可用半音数表示。

常用音程：

| 半音数 | 名称 | 从 C 出发 |
| --- | --- | --- |
| 0 | unison | C |
| 3 | minor third | Eb |
| 4 | major third | E |
| 5 | perfect fourth | F |
| 6 | tritone | F# |
| 7 | perfect fifth | G |
| 10 | minor seventh | Bb |
| 11 | major seventh | B |
| 12 | octave | C |

和弦类型主要由根音上方的音程组合决定。

#### 5.2.3 三和弦

常见三和弦：

| 类型 | 组成 | C 为根音时 |
| --- | --- | --- |
| major | root + major third + perfect fifth | C E G |
| minor | root + minor third + perfect fifth | C Eb G |
| diminished | root + minor third + diminished fifth | C Eb Gb |
| augmented | root + major third + augmented fifth | C E G# |

自动和弦识别常先限制在 major/minor，是因为：

- 标签数少。
- 模板简单。
- 数据集较容易统一。
- 很多流行音乐可用大/小三和弦近似。

但真实音乐中还有七和弦、挂留和弦、转位、slash chord、无和弦段落。简化标签集会带来系统性误差。

#### 5.2.4 调、音阶与功能

C major 和 G major 中都可能出现 C 和弦，但功能不同：

- 在 C major 中，C 是 tonic，记作 I。
- 在 G major 中，C 是 subdominant，记作 IV。

功能和声用罗马数字描述相对关系：

```text
I - IV - V - I
```

这比绝对和弦名更体现音乐语境。自动识别输出通常是绝对 chord labels，但 HMM 的 transition model 可以部分利用功能和声中的常见进行，例如 I 到 IV、V 到 I、自身保持等。

### 5.3 Template-Based Chord Recognition

模板法是最直接的和弦识别方法。

流程：

```text
audio
-> chromagram
-> for each frame:
       compare chroma vector with chord templates
       choose best matching chord
-> chord label sequence
```

#### 5.3.1 二值模板

以 C major 为例：

```text
C major = C E G
```

对应 12 维模板：

```text
C  C# D  D# E  F  F# G  G# A  A# B
1  0  0  0  1  0  0  1  0  0  0  0
```

A minor：

```text
A C E
```

模板：

```text
C  C# D  D# E  F  F# G  G# A  A# B
1  0  0  0  1  0  0  0  0  1  0  0
```

其他和弦通过循环移位得到。

#### 5.3.2 相似度计算

给定归一化 chroma `x` 和模板 `t`，可用：

```text
score = dot(x, t)
```

或：

```text
score = cosine_similarity(x, t)
```

选择最高分：

```text
chord_hat = argmax_c score(x, template_c)
```

如果使用距离：

```text
chord_hat = argmin_c distance(x, template_c)
```

#### 5.3.3 模板法优点

- 简单可解释。
- 不需要训练数据。
- 易于实现和调试。
- 适合教学和 baseline。

#### 5.3.4 模板法缺点

- 逐帧独立，标签容易抖动。
- 对经过音、旋律音、低音加花敏感。
- 对音色、泛音、调音偏差敏感。
- major/minor 容易混淆。
- 不利用和弦进行的时间规律。

模板法是理解和弦识别的入口，但不是完整系统的终点。

### 5.4 Beat-Synchronous Chroma

和弦通常不会每 100ms 改变一次。很多系统会把 chroma 对齐到 beat 或小节网格。

流程：

```text
audio
-> beat tracking
-> frame-level chroma
-> aggregate chroma between consecutive beats
-> beat-synchronous chroma
-> chord recognition
```

优点：

- 减少帧级抖动。
- 更接近音乐事件尺度。
- 降低序列长度，提高效率。
- 对短时装饰音更稳健。

聚合方式：

- mean：平均每个 beat 内 chroma。
- median：对异常值更稳健。
- max：保留强出现 pitch class，但可能放大噪声。

风险：

- beat tracking 错误会传递到和弦识别。
- 和弦可能在弱拍或半拍处变化。
- rubato 或无明确节拍音乐不适合强制 beat 网格。

实践中常比较 frame-level、beat-level、bar-level 三种粒度。

### 5.5 和弦识别中的 Ambiguities

和弦识别的困难很多不是算法差，而是任务本身有歧义。

#### 5.5.1 非和弦音

旋律中经常出现不属于当前和弦的音：

- passing tone：经过音。
- neighbor tone：辅助音。
- suspension：延留音。
- appoggiatura：倚音。

这些音会进入 chroma，干扰模板匹配。

例子：

```text
当前和声 C major: C E G
旋律经过音 D 很强
chroma 中 C D E G 都明显
```

系统可能误判为 G、Em7、Csus2 或其他标签，取决于标签集。

#### 5.5.2 泛音导致的混淆

一个 C 音不只在 C chroma 有能量。它的泛音会在 G、E、Bb 等 pitch class 产生能量，虽然强度通常递减。

结果：

- 单个低音 C 可能看起来像 C major 的一部分。
- C minor 中的 C、Eb、G 加上 C 的泛音 E，可能造成 C major / C minor 混淆。
- 低音乐器泛音强，影响尤其明显。

因此，二值模板太理想化。真实 chroma 不是“和弦音为 1，其他为 0”。

#### 5.5.3 Root 与 inversion

C/E 表示 C major 第一转位，低音是 E，但根音仍是 C。

如果系统只看 bass energy，可能把 C/E 误判为 Em 或 E 相关和弦。  
如果系统完全忽略低音，又无法区分 C、C/E、C/G 这类 slash chord。

是否识别转位，取决于任务定义。

#### 5.5.4 Major/minor confusion

major 与 minor 只差三音：

```text
C major: C E  G
C minor: C Eb G
```

如果三音很弱，或者泛音把 E/Eb 都带出来，系统就容易混淆。

这也是自动和弦识别最常见错误之一。

#### 5.5.5 Tuning mismatch

如果录音整体偏高或偏低，例如偏 50 cents，chroma binning 会把能量分散到相邻 pitch class。

解决方向：

- 估计全局 tuning offset。
- 调整 log-frequency binning。
- 使用更平滑的 pitch-class mapping。

#### 5.5.6 Segmentation ambiguity

同一个片段可以有不同和弦切分：

```text
每拍一个和弦
每两拍一个和弦
整小节一个和弦
```

和弦标签的时间边界往往没有唯一答案。短时局部音可能被解释为临时和弦，也可能只是装饰。

### 5.6 Enhancement Strategies

#### 5.6.1 Harmonic templates

二值模板可以扩展为带泛音权重的模板。

对一个根音，不只给自身 pitch class 权重，也给其泛音对应的 pitch class 较小权重。例如 C 的前若干泛音会贡献到：

```text
C, G, E, Bb ...
```

构造 C major 模板时，把 C、E、G 三个音各自的泛音模板相加。

优点：

- 更接近真实录音 chroma。
- 对泛音扩散更稳健。

缺点：

- 参数更多。
- 可能加重某些混淆，例如 major/minor。

#### 5.6.2 从数据学习模板

不用手工设计模板，而从带标注数据中学习每个和弦的平均 chroma 模式。

流程：

```text
labeled audio
-> chroma features
-> group frames by chord label
-> average / estimate distribution per chord
-> learned templates
```

优点：

- 能吸收真实音色、泛音、混音特点。
- 通常比纯二值模板更贴近数据。

风险：

- 依赖训练集风格。
- 标签映射会影响结果。
- 数据集调性分布不平衡会引入偏差。

#### 5.6.3 Log compression / spectral whitening

chroma 能量可能被强泛音或强低音支配。log compression 可以压缩动态范围：

```text
x_compressed = log(1 + gamma * x)
```

效果：

- 弱但重要的和弦音更可见。
- 强低音不至于完全支配相似度。
- 通常显著影响和弦识别准确率。

gamma 太小，压缩不足；gamma 太大，噪声和弱无关成分也被放大。

#### 5.6.4 Temporal smoothing / prefiltering

对 chroma 序列做时间平滑可减少局部离群：

```text
chroma[t] = average(chroma[t-L : t+L])
```

优点：

- 减少旋律经过音影响。
- 减少帧级标签跳变。

代价：

- 和弦边界变模糊。
- 快速和弦变化被抹掉。
- 固定窗口不能适应不同音乐速度。

HMM 可以看作更灵活的时间建模方式。

### 5.7 HMM-Based Chord Recognition

模板法逐帧独立，而音乐中的和弦序列有时间规律：

- 和弦通常会持续一段时间。
- 自身保持比频繁跳变更常见。
- 某些进行更常见，例如 I-IV-V-I。
- 某些远关系和弦转移较少。

HMM 用概率模型把“当前观测像什么”和“和弦如何随时间转移”结合起来。

#### 5.7.1 HMM 组成

HMM 包含：

| 组成 | 在和弦识别中的含义 |
| --- | --- |
| hidden states | 和弦标签，如 C、G、Am |
| observations | chroma vectors |
| emission probability | 某和弦生成某 chroma 的概率 |
| transition probability | 一个和弦转到另一个和弦的概率 |
| initial probability | 开始时各和弦的概率 |

记号上可以理解为：

```text
state sequence:       C -> C -> C -> G -> G -> Am
observation sequence: x1   x2   x3   x4   x5   x6
```

状态不可直接看到，只能看到 chroma；所以叫 hidden Markov model。

#### 5.7.2 Emission probability

emission 描述：

```text
P(observed chroma | chord)
```

实现方式：

- 用模板相似度转换成概率。
- 用 learned template 建模。
- 用 Gaussian 或 Gaussian mixture 建模连续 chroma。
- 离散 HMM 中先把 chroma 量化到 codebook。

简单实践中，可把模板距离转成分数：

```text
emission_score[c, t] = similarity(chroma[t], template[c])
```

再在 log domain 中与 transition score 相加。

#### 5.7.3 Transition probability

transition 描述：

```text
P(chord_t = j | chord_{t-1} = i)
```

常见设计：

- 高 self-transition：鼓励和弦持续。
- 功能和声转移：提高 I->IV、V->I 等常见进行。
- 数据驱动：从标注数据统计转移频率。
- transposition-invariant：按相对关系统计，避免训练集调性偏置。

进阶重点：很多 HMM 和弦识别的提升并不来自复杂和声知识，而来自高 self-transition，减少了不合理的帧级抖动。

#### 5.7.4 Viterbi

给定整段 chroma 观测，Viterbi 寻找最可能的和弦状态序列：

```text
best chord sequence
= argmax over state sequences P(states, observations)
```

直觉：

```text
每一帧局部最像的和弦，不一定组成全局最合理的和弦序列。
```

Viterbi 用动态规划避免枚举所有可能序列。

简化形式：

```text
D[c, t] = 到时间 t 且当前和弦为 c 的最佳路径分数

D[c, t] =
    emission[c, t] + max_prev (
        D[prev, t-1] + transition[prev, c]
    )
```

同时记录 backpointer：

```text
E[c, t] = argmax_prev(...)
```

最后从终点回溯得到完整和弦序列。

实际实现常用 log probability：

```text
log P(sequence, observations)
= sum log emission + sum log transition + log initial
```

这样避免很多小概率相乘导致数值下溢。

#### 5.7.5 HMM 与 prefiltering 的区别

prefiltering 是先平滑 chroma，再逐帧分类。它不知道当前候选和弦是什么，只是固定窗口平均。

HMM 是在标签层面做全局序列优化。它可以允许某些位置局部观测不强，但为了整体路径合理而保持同一和弦。

例子：

```text
观测: C, C, noisy, C
模板法: C, C, G, C
HMM:   C, C, C, C
```

如果 `noisy` 帧前后都强烈支持 C，且 self-transition 高，HMM 会倾向保留 C。

### 5.8 和弦识别评价

#### 5.8.1 Frame-wise accuracy

最常见做法是按时间帧比较：

```text
accuracy = 正确标签帧数 / 总帧数
```

如果每帧时长相同，这等价于时间加权准确率。

如果 segment 长度不等，更准确的写法是：

```text
weighted accuracy = 正确匹配时长 / 总时长
```

#### 5.8.2 标签映射

系统输出和参考标签集必须先统一。例如：

```text
C:maj7 -> C
G:7    -> G
N      -> no chord or ignored
C/E    -> C
```

不同映射会显著影响分数。只评 major/minor triads 时，很多复杂和弦会被压缩到近似三和弦。

#### 5.8.3 边界误差

和弦识别不只要标签对，还要时间边界合理。但 frame-wise 指标对边界附近非常敏感。

实践中要检查：

- 是否系统性提前或滞后。
- 是否过度切碎。
- 是否把短经过和弦当作真实和弦。

#### 5.8.4 数据集偏差

如果训练集主要是某种风格，例如 Beatles songs，模型可能对类似流行和声表现好，但对爵士、古典、金属、电子音乐泛化不足。

评价报告应说明：

- 标签集。
- 数据集。
- 是否训练/测试分离。
- 是否按歌曲分割，避免同一歌曲泄漏。
- 是否做 cross-validation。

### 5.9 Chapter 5 实践练习

#### 练习 1：24 类模板识别器

实现最小系统：

```text
1. 读取音频
2. 提取 chroma
3. 构造 12 major + 12 minor binary templates
4. 对每帧计算 cosine similarity
5. 输出最高分和弦
6. 可视化 chroma、score matrix、chord labels
```

观察：

- 标签是否频繁跳变？
- major/minor 是否混淆？
- bass 很强时结果是否偏向低音根音？

#### 练习 2：加入时间平滑

在 chroma 上做不同窗口长度平滑：

```text
L = 1, 5, 15, 30 frames
```

比较：

- 短窗口：边界清楚但抖动多。
- 长窗口：抖动少但边界拖糊。

记录不同音乐速度下最佳窗口是否不同。

#### 练习 3：beat-synchronous chroma

流程：

```text
beat tracking
-> aggregate chroma per beat
-> template recognition per beat
```

比较 frame-level 和 beat-level：

- 哪个更稳定？
- 哪个边界更准？
- beat tracking 错误时会发生什么？

#### 练习 4：HMM/Viterbi

在模板分数基础上加入 transition：

```text
self-transition = high
other-transition = low
```

先不用复杂和声知识，只测试高 self-transition 的效果。

再尝试：

- 提高 circle-of-fifths 邻近转移概率。
- 提高 V->I、I->IV 等功能进行概率。
- 比较是否真的比 uniform transition 更好。

#### 练习 5：错误分析表

手工听 30 秒识别结果，记录每个错误属于哪类：

| 时间 | 参考 | 预测 | 可能原因 |
| --- | --- | --- | --- |
| 12.0-13.5 | Am | C | 共享 C/E，A 弱 |
| 20.0-21.0 | G | Em | 旋律 E 强 |
| 32.0-33.0 | F | C | bass 不清楚 |

错误分析比单纯追求分数更能提高系统。

### 5.10 Chapter 5 常见错误

1. 把 chroma 当成真实音符集合。  
   chroma 是能量分布，包含泛音、噪声、混音和非和弦音。

2. 忽视调音偏差。  
   录音整体偏音会让 chroma 泄漏到相邻 bin。

3. 过度相信最高模板分。  
   局部最高不等于全局最合理。

4. HMM transition 设置过强。  
   self-transition 太高会漏掉真实快速和弦变化。

5. HMM transition 设置过弱。  
   会退化成逐帧模板法，标签抖动。

6. 不统一标签集就评价。  
   `C:maj7`、`C`、`C/E`、`N` 如何处理必须事先定义。

7. 忽视 no-chord。  
   静音、鼓 solo、噪声 intro 被强行分到某个和弦，会制造无意义错误。

8. 用训练集调参再报告训练集分数。  
   这不能说明泛化能力。

9. 只看总体 accuracy。  
   要看混淆矩阵、边界错误、不同歌曲/风格的表现。

---

## 6. 两章之间的连接

### 6.1 Chroma 是共同桥梁

Chapter 4 和 Chapter 5 都大量使用 chroma，但目的不同：

| 任务 | chroma 用法 |
| --- | --- |
| 结构分析 | 比较不同时间段的和声/旋律轮廓相似性 |
| 和弦识别 | 推断当前时间的和弦标签 |

结构分析不一定需要知道每一帧是什么和弦，只需要知道哪些片段相似。和弦识别则必须把 chroma 映射到离散和弦标签。

### 6.2 Similarity 与 Probability

Chapter 4 偏向 similarity：

```text
两个时间点/片段有多像？
```

Chapter 5 偏向 probability：

```text
这个 chroma 由哪个和弦生成最合理？
这条和弦序列整体有多可能？
```

但底层思想相通：都把音乐变成可比较、可优化的中层表示。

### 6.3 Dynamic Programming 的重复出现

两章都可见动态规划思想：

- thumbnailing 中寻找最优重复路径族，可借鉴 DTW 类优化。
- HMM 中 Viterbi 用 DP 找最可能状态序列。

统一模式：

```text
local evidence + transition/path constraint -> global optimum
```

这是 MIR 中非常重要的思维方式。

---

## 7. 推荐学习路线

### 7.1 初学者路线

先掌握：

```text
chroma
cosine similarity
SSM
novelty curve
binary chord templates
frame-wise accuracy
```

能完成：

- 画一首歌的 chromagram。
- 画 SSM 并指出重复段。
- 用 novelty curve 找大致边界。
- 用 24 个二值模板做简单和弦识别。

### 7.2 进阶路线

继续掌握：

```text
SSM enhancement
transposition-invariant matching
audio thumbnailing
beat-synchronous chroma
harmonic templates
HMM
Viterbi
boundary/labeling/thumbnail evaluation
```

能完成：

- 比较 chroma SSM 与 MFCC SSM。
- 调整 smoothing/downsampling/kernel size。
- 实现 beat-synchronous chord recognition。
- 实现 Viterbi 后处理。
- 做错误分析和评价报告。

### 7.3 高阶思维

每个任务都用以下问题约束自己：

```text
1. 输出到底是什么：边界、标签、thumbnail，还是关系？
2. 使用哪种时间尺度：帧、拍、小节、段落？
3. 特征保留了什么音乐信息？
4. 特征丢掉了什么信息？
5. 需要对哪些变化不敏感：音色、转调、速度、响度？
6. 使用 similarity、template、HMM 还是 DP？
7. 评价指标是否对应真实目标？
8. 错误来自特征、模型、参数、标签集还是数据？
```

---

## 8. 快速复习表

| 概念 | 所属章节 | 一句话 |
| --- | --- | --- |
| SSM | Ch.4 | 把每个时间点和每个时间点互相比 |
| path-like structure | Ch.4 | 重复片段在 SSM 中形成斜线路径 |
| block-like structure | Ch.4 | 同质段落在 SSM 中形成方块 |
| novelty curve | Ch.4 | 衡量当前位置前后变化强度 |
| checkerboard kernel | Ch.4 | 在 SSM 对角线附近检测前后差异 |
| audio thumbnail | Ch.4 | 最能代表整首音乐的重复片段 |
| scape plot | Ch.4 | 用中心和长度可视化候选片段质量 |
| boundary evaluation | Ch.4 | 评价边界是否在容忍范围内 |
| chord template | Ch.5 | 和弦在 chroma 空间中的理想模式 |
| beat-synchronous chroma | Ch.5 | 按拍聚合 chroma，减少帧级噪声 |
| emission probability | Ch.5 | 某和弦生成某 chroma 的可能性 |
| transition probability | Ch.5 | 一个和弦转到另一个和弦的可能性 |
| HMM | Ch.5 | 用隐藏状态表示和弦、用观测表示 chroma |
| Viterbi | Ch.5 | 找全局最可能和弦序列的动态规划算法 |

---

## 9. 最小项目：Structure + Chord Lab

可以把两章合成一个小项目。

### 输入

一首 2-4 分钟的流行歌或古典短曲音频。

### 输出

```text
1. chromagram
2. chroma SSM
3. novelty curve + estimated boundaries
4. candidate thumbnail
5. frame-level chord labels
6. beat-synchronous chord labels
7. HMM-smoothed chord labels
```

### 建议调试图

- waveform
- chromagram
- SSM
- enhanced SSM
- novelty curve with peaks
- chord score matrix
- raw vs smoothed chord labels

### 最终报告问题

```text
1. SSM 中哪些斜线对应实际重复？
2. novelty peaks 是否对应 verse/chorus 边界？
3. thumbnail 是否听起来像歌曲代表片段？
4. 和弦识别最常错哪些类型？
5. HMM 减少了哪些抖动？是否也抹掉了真实变化？
6. beat-synchronous chroma 比 frame-level 好在哪里，坏在哪里？
```

---

## 10. 本篇核心结论

Chapter 4 的核心是：

```text
音乐结构可以通过“时间点之间的相似关系”显现出来。
SSM 是观察 repetition、homogeneity、novelty 的核心表示。
```

Chapter 5 的核心是：

```text
和弦识别可以看作 chroma 到 chord label 的序列标注问题。
模板给出局部证据，HMM/Viterbi 给出时间上的全局一致性。
```

两章共同提醒我们：

```text
MIR 的关键不是盲目套模型，而是选择合适表示、明确不变性、理解时间尺度，并用匹配任务目标的指标评价结果。
```

---

## 第四篇：节拍与检索：Chapter 6 + Chapter 7

本篇覆盖《Fundamentals of Music Processing》第 6 章和第 7 章。两章看似分别讨论“节拍”和“检索”，但底层思路高度一致：先把音频转换成适合任务的中层表示，再在这个表示上寻找峰值、周期性、相似路径或索引命中。

第 6 章的主线是：

```text
audio waveform
-> onset / novelty function
-> local periodicity
-> tempogram
-> pulse / beat positions
```

第 7 章的主线是：

```text
audio waveform
-> robust feature / fingerprint
-> index or similarity matrix
-> matching / ranking
-> retrieval result
```

这两章需要特别注意三个区分：

- `onset` 不等于 `beat`。onset 是声音事件开始，beat 是人感知并愿意跟着拍手或点头的拍点。
- `tempo estimation` 不等于 `beat tracking`。tempo 只给速度，beat tracking 还要给每一个拍点的时间位置。
- `audio identification` 不等于 `version identification`。前者识别同一段录音，后者寻找同一作品的不同版本、翻唱、改编或重混。

### 6. Tempo and Beat Tracking

#### 6.1 本章解决什么问题

节拍跟踪要从音频中推断音乐的时间骨架。一个完整系统通常要回答：

- 哪些时间点出现了新的音乐事件？
- 当前局部速度大约是多少？
- 哪些事件构成稳定的脉冲层级？
- 听众最可能认为的拍点在哪里？
- 如果速度变化、弱拍、切分、rubato 或多声部同时存在，系统如何保持稳定？

直观地说，人听音乐时常常能跟着拍子点头。机器要模拟这个过程并不简单，因为音频里没有显式写着“这里是 beat”。机器看到的是波形或谱图，只能通过能量变化、频谱变化和周期性来推断。

#### 6.2 Onset、attack、transient

这三个词经常混用，但在节拍分析中必须分清。

`onset` 是音乐事件开始的时间点。它是一个时间瞬间，例如钢琴某个音被击键的起始时间、鼓槌击中鼓面的时间。

`attack` 是声音从开始到建立起来的一段过程。它不是一个点，而是一段时间。钢琴、吉他拨弦、鼓声通常 attack 很短；弦乐渐强、人声滑入、管乐连奏的 attack 可能比较长。

`transient` 是短暂、快速变化、通常带有噪声性的声音成分。很多 transient 出现在音符开头，比如钢琴击弦、吉他拨弦、鼓声冲击。但 transient 不一定只出现在开头，某些释放、换弓、换气、摩擦也可能产生 transient-like 成分。

可以用一个理想化包络理解：

```text
onset:    事件开始的点
attack:   能量快速建立的阶段
transient:短时、混乱、难预测的快速变化成分
decay:    初始冲击后能量回落
sustain:  相对稳定的持续阶段
release:  声音结束阶段
```

常见难点：

- 打击乐 onset 清楚，弦乐和人声的 onset 可能模糊。
- 复调音乐中，一个弱音的 onset 可能被另一个强音盖住。
- vibrato、颤音、混响尾巴会造成能量波动，但不一定是新事件。
- 同一时刻可能有多个事件同时开始，机器只看到混合信号。

#### 6.3 Novelty function：把“变化”变成曲线

Novelty function 是节拍分析的核心中层表示。它把音频转成一条随时间变化的曲线，曲线峰值表示“这里发生了明显变化”。onset detection 往往就是在 novelty function 上做 peak picking。

基本流程：

```text
audio
-> frame-based analysis
-> measure change between frames or local regions
-> novelty curve
-> smoothing / normalization
-> peak picking
-> onset candidates
```

Novelty function 的关键不是“声音有多大”，而是“声音内容变化有多强”。不同 novelty 只是在定义“变化”的方式上不同。

##### 6.3.1 Energy-based novelty

最直接的方法是看局部能量是否突然上升。

```text
waveform
-> windowed local energy
-> first-order difference
-> half-wave rectification
-> energy novelty
```

其中 half-wave rectification 的意思是只保留正增长，忽略能量下降。因为 onset 通常对应能量增加，而不是能量衰减。

优点：

- 简单，容易实现。
- 对鼓、钢琴、吉他拨弦等清晰 attack 的声音有效。

缺点：

- 对复调音乐不够稳健。
- 弱 onset 可能被强持续音掩盖。
- sustain 阶段的能量起伏可能造成误检。
- 渐强音可能没有清晰峰值。

适用场景：鼓点明显、单音事件清楚、教学演示、快速原型。

##### 6.3.2 Spectral-based novelty

Spectral novelty 不只看总能量，而是看频谱内容是否变化。常见做法是 spectral flux：

```text
audio
-> STFT magnitude spectrogram
-> compare adjacent frames per frequency bin
-> keep positive spectral increases
-> sum over frequency bins
-> spectral novelty
```

直觉是：一个新音出现时，不一定让总能量大幅增加，但通常会改变某些频带的能量分布。尤其在复调中，高频瞬态或局部谱变化比全局能量更可靠。

优点：

- 比 energy novelty 更适合复调。
- 能利用不同频带的变化。
- 对打击乐、钢琴、拨弦等 broadband transient 通常较敏感。

缺点：

- 对 vibrato、tremolo、音色变化也可能敏感。
- 频率分辨率和时间分辨率受 STFT 参数影响。
- 如果平滑太强，会牺牲 onset 时间精度。

实践中，spectral novelty 是最常用的 onset/beat 前端之一。

##### 6.3.3 Phase-based novelty

STFT 的每个系数不仅有 magnitude，也有 phase。稳定的正弦成分在相邻帧中的 phase 变化比较可预测；transient 区域更混乱，phase prediction error 会变大。

基本思路：

```text
complex STFT
-> estimate expected phase from previous frames
-> compare expected phase with observed phase
-> aggregate phase deviations
-> phase novelty
```

优点：

- 能捕捉 magnitude 不明显但相位结构突然变化的事件。
- 对某些软 onset 有帮助。

难点：

- phase wrapping 需要处理，否则相位跳变会被误解。
- 小 magnitude 区域的 phase 很不稳定，容易被噪声污染。
- 实现和调试比 energy/spectral novelty 更复杂。

##### 6.3.4 Complex-domain novelty

Complex-domain novelty 同时利用 magnitude 和 phase。它先根据前几帧预测下一帧的复数谱，再比较预测值和真实值的偏差。

```text
previous complex STFT coefficients
-> predict current complex coefficient
-> compare with observed current coefficient
-> aggregate prediction error
-> complex-domain novelty
```

它试图解决 phase-only 方法的问题：如果某个频率 bin 的 magnitude 很小，phase 本来就不可靠；用 complex domain 可以让 magnitude 对 phase 信息加权。

优点：

- 同时考虑能量和相位。
- 对稳态区域和瞬态区域的区分更细。

缺点：

- 参数和实现复杂。
- 在很多工程场景中，经过良好调参的 spectral flux 已经足够。

#### 6.4 Peak picking：从 novelty 到 onset

Novelty curve 只是候选证据，不能把所有局部起伏都当成 onset。Peak picking 通常包含：

- 平滑：去掉细碎噪声。
- 局部最大值检测：只保留邻域内最高点。
- 自适应阈值：局部峰值要高于邻域平均或中位数。
- 最小间隔：避免一个 attack 被检测成多个 onset。
- 延迟校正：平滑和窗口会造成时间偏移，需要对齐。

一个实用规则：

```text
onset candidate = local maximum
                  and novelty[t] > local_threshold[t]
                  and distance_from_previous_onset > min_interval
```

初学者最常见错误是直接对 novelty 做全局阈值。音乐的局部响度变化很大，安静段和高潮段需要不同阈值。

#### 6.5 Tempo analysis：从变化曲线到速度

Tempo 是 beat rate，常用 BPM 表示。

```text
period_seconds = 相邻 beat 的时间间隔
tempo_BPM = 60 / period_seconds
frequency_Hz = 1 / period_seconds
tempo_BPM = 60 * frequency_Hz
```

Tempo analysis 的输入通常不是 waveform，而是 novelty function。原因是 beat 常常对应事件变化，而不是波形的原始振荡。

基本思路：

```text
novelty function
-> local periodicity analysis
-> tempo candidates over time
-> tempogram
```

#### 6.6 Tempogram：时间-速度表示

Tempogram 类似 spectrogram，只是纵轴不是 frequency，而是 tempo。

```text
spectrogram: waveform -> time-frequency energy
tempogram:   novelty  -> time-tempo periodicity
```

Tempogram 中某个位置 `T(t, tau)` 很大，表示在时间 `t` 附近，novelty curve 具有接近 `tau` BPM 的周期性。

它能回答：

- 局部 tempo 是否稳定？
- 是否存在 tempo change、accelerando、ritardando？
- 是否有多个 pulse level 同时强，例如 60/120/240 BPM？
- 估计的 tempo 是不是发生倍速或半速混淆？

#### 6.7 Fourier tempogram

Fourier tempogram 用短时傅里叶分析 novelty curve。它把局部 novelty 片段与不同频率的正弦模板比较。

流程：

```text
novelty curve
-> choose local window around time t
-> compare with sinusoidal templates of different frequencies
-> convert frequency to BPM
-> Fourier tempogram
```

特点：

- 对周期性变化敏感。
- 容易显示 tempo harmonics。
- 如果真实 tactus 是 120 BPM，240 BPM 可能也很强，因为每拍里的细分也形成周期。

解释时要小心：tempogram 上最强峰不一定就是人感知的 beat level。它可能是 tatum、八分音符、十六分音符或小节层级。

#### 6.8 Autocorrelation tempogram

Autocorrelation tempogram 比较 novelty curve 与它自己的延迟版本。

```text
local novelty window
-> shift by lag l
-> compute similarity with original window
-> lag -> period -> BPM
-> autocorrelation tempogram
```

如果某个 lag 上相似度高，表示该局部区域存在对应周期的重复模式。

特点：

- 直观，和“找重复间隔”一致。
- 容易显示 subharmonics。
- 如果真实 120 BPM 很强，60 BPM 也可能强，因为隔一拍的模式也相似。

Fourier tempogram 和 autocorrelation tempogram 的偏差方向不同：前者常强调 harmonics，后者常强调 subharmonics。实际系统常需要额外先验来决定真正的 beat level。

#### 6.9 Cyclic tempogram

Cyclic tempogram 借鉴 chroma 的思想。

Chroma 把相差八度的音高折叠：

```text
C3, C4, C5 -> C
```

Cyclic tempogram 把相差 2 的幂倍的 tempo 折叠：

```text
30, 60, 120, 240, 480 BPM -> 同一 tempo class
```

它解决的是 tempo octave confusion，也就是倍速/半速混淆。它不关心到底是 60 还是 120 BPM，而关心它们属于同一速度类别。

适用场景：

- 结构分析中只需要节奏型变化，不需要精确 beat level。
- 检索或相似度任务中想弱化 tempo doubling/halving。
- 可视化局部节奏稳定性。

限制：

- 如果任务必须输出具体 BPM，cyclic tempogram 不够。
- 折叠会丢失 pulse level 信息。

#### 6.10 Beat tracking：估计拍点位置

Tempo estimation 只估计速度；beat tracking 还要估计 phase，即第一拍或某个拍点落在哪里。

```text
tempo:  120 BPM
beats:  0.43s, 0.93s, 1.43s, 1.93s, ...
```

Beat tracking 的目标不是找所有 onset，而是找符合音乐脉冲感的一串时间点。很多 onset 不是 beat，例如装饰音、切分音、快速分解和弦；很多 beat 也没有明显 onset，例如长音上的弱拍。

#### 6.11 PLP：Predominant Local Pulse

PLP 的目标是从 novelty function 中得到一条增强后的 pulse curve。它不是直接在 novelty 上找峰，而是先估计局部主导周期，再把局部周期性重建成脉冲曲线。

流程：

```text
novelty function
-> Fourier tempogram
-> for each time, choose predominant local tempo
-> construct windowed sinusoid aligned to local novelty
-> overlap-add all local sinusoids
-> PLP curve
-> peak picking
```

直觉：如果局部 novelty peaks 大致按某个周期出现，PLP 会把这个周期性增强；如果局部 tempo 估计互相矛盾，overlap-add 时会相互抵消，PLP 峰值会变弱。

优点：

- 能适应局部 tempo 变化。
- 能把 noisy novelty 转成更规整的 pulse representation。
- PLP 曲线的幅度可作为某种置信度：局部周期一致时峰值更强。

缺点：

- 默认会追随最强 pulse level，不一定是人感知的 tactus。
- tempo 范围设得太宽时，可能在 60/120/240 BPM 之间跳。
- 对复杂节奏、弱拍、rubato 仍然敏感。

实践建议：如果你知道目标音乐大致速度范围，应限制 tempogram 的 tempo range。例如只在 60-180 BPM 内找 quarter-note level，可以减少跳到八分音符或十六分音符层级的风险。

#### 6.12 Dynamic programming beat tracking

DP beat tracking 假设音乐有一个大致稳定的全局 tempo。它把 beat tracking 变成一个全局优化问题：选择一串拍点，使它们既落在 novelty peak 上，又保持相邻间隔接近预期 beat period。

输入：

- novelty function `Delta[1:N]`
- 预估 beat period `delta_hat`
- 权重参数 `lambda`

目标由两部分组成：

```text
score = sum of novelty values at chosen beats
        + lambda * sum of interval penalties
```

其中 interval penalty 惩罚相邻 beat 间距偏离 `delta_hat`。常见设计是在对数轴上惩罚：

```text
penalty(delta) = - (log2(delta / delta_hat))^2
```

这个设计有一个很重要的直觉：快一倍和慢一倍应该受到类似程度的惩罚，因为 tempo 偏差本质上是相对比例，而不是绝对差值。

动态规划递推可以理解为：

```text
D[n] = 以 n 作为最后一个 beat 时的最佳累计分数
D[n] = Delta[n] + max(
           0,
           max over previous m < n of D[m] + lambda * penalty(n - m)
       )
```

然后从 `D` 最大的位置开始回溯 predecessor，得到完整 beat sequence。

优点：

- 全局最优，不是逐帧贪心。
- 能在局部 novelty 弱时仍保持稳定拍点。
- 简洁、高效，适合 tempo 大致稳定的音乐。

缺点：

- 依赖全局 tempo 估计。
- 不擅长处理明显 accelerando、ritardando 或突然变速。
- `lambda` 太大时会过度机械，太小时会被 novelty 峰值牵着走。

#### 6.13 节拍跟踪评价

节拍评价不能只看“BPM 对不对”。两个系统可能 tempo 相同，但 phase 错半拍；也可能 beat positions 基本正确，但估计为双倍速度。

常见评价思路：

- Onset detection：precision、recall、F-measure，在很小 tolerance window 内判断命中。
- Tempo estimation：允许一定比例误差，例如预测 BPM 是否在参考 BPM 的某个百分比范围内。
- Beat tracking：预测 beat 是否落在参考 beat 附近的容忍窗口内。
- Continuity-based evaluation：不仅看单点命中，还看连续一段时间是否稳定跟踪。
- 倍速/半速容忍：有些指标允许 2x 或 1/2x tempo，有些不允许，必须提前说明。

评价前要问清：

- 参考标注是哪个 metrical level？
- 弱拍和强拍是否区分？
- 是否允许 half-tempo/double-tempo？
- rubato 和 expressive timing 的容忍范围是多少？
- 应用需要实时输出还是离线全局优化？

#### 6.14 Chapter 6 实践练习

练习 1：画 novelty curve。

```text
1. 取一段鼓点明显的音频。
2. 计算 STFT magnitude。
3. 实现 spectral flux。
4. 画 waveform、spectrogram、novelty curve。
5. 手动标几个 onset，对比 novelty peaks。
```

练习 2：比较不同 novelty。

```text
1. 对同一段音频计算 energy novelty 和 spectral novelty。
2. 找出 energy novelty 漏检但 spectral novelty 能检测的位置。
3. 找出 spectral novelty 误检的位置，观察是否来自 vibrato 或音色变化。
```

练习 3：画 tempogram。

```text
1. 用 novelty curve 做局部 autocorrelation。
2. 把 lag 转成 BPM。
3. 画 time-tempo 图。
4. 观察 60/120/240 BPM 是否同时出现。
```

练习 4：实现简化 DP beat tracker。

```text
1. 给定 novelty curve 和手动 tempo。
2. 根据 tempo 算 beat period。
3. 实现 D[n] 递推和 predecessor 回溯。
4. 在 waveform 上画预测 beats。
5. 调整 lambda，观察结果从“追峰”到“机械均匀”的变化。
```

练习 5：错误分析。

```text
1. 找一段 rubato 钢琴。
2. 找一段强鼓点流行歌。
3. 找一段切分明显的 funk 或 jazz。
4. 比较同一个 beat tracker 在三者上的失败模式。
```

#### 6.15 Chapter 6 常见错误

- 把所有 onset 当作 beat。快速装饰音、分解和弦、hi-hat 细分不一定是 tactus。
- 把最高 tempogram 峰当作真实 tempo。最高峰可能是 2x 或 1/2x。
- 忽略 STFT 参数。窗口太长会模糊 onset，窗口太短会影响频谱稳定性。
- 只用全局阈值做 peak picking。音乐局部响度变化会导致安静段漏检、高潮段误检。
- 把 DP 当成万能。DP 需要合理 novelty 和 tempo prior，不能修复前端特征错误。
- 评价时不说明 tolerance 和 metrical level。不同设置下分数差异很大。
- 只看 BPM 准确率，不看 beat phase。BPM 正确但整体错半拍，实际体验仍然很差。

### 7. Content-Based Audio Retrieval

#### 7.1 本章解决什么问题

Content-based audio retrieval 是根据音频内容进行检索，而不是根据标题、歌手、标签等元数据。

典型查询形式：

- 手机录到几秒餐厅背景音乐，想知道歌名。
- 给一段音频片段，想在大库中找出现位置。
- 给一首歌，想找翻唱、现场版、改编版。
- 给一段旋律或乐谱，想找对应音乐。

第 7 章按“相似性要求越来越宽松、难度越来越高”组织：

```text
audio identification
-> audio matching
-> version identification
```

#### 7.2 Audio identification：识别同一录音

Audio identification 的任务是：给一个短查询片段，找出它来自数据库中的哪一条具体录音，以及大约从哪个时间位置开始。

例子：手机听歌识曲。查询片段可能只有几秒，带有人声噪声、环境混响、手机麦克风失真、压缩损伤。

系统要求：

- Robustness：对噪声、混响、压缩、设备差异稳健。
- Specificity：不同歌曲不能轻易误匹配。
- Compactness：指纹要小，便于存储和传输。
- Scalability：数据库可能有百万级录音，不能逐段暴力比较。
- Locality：查询可能来自原曲任意位置，指纹应由局部片段产生。
- Translation invariance：同一局部内容出现在不同全局时间位置时，指纹仍能匹配。

关键思想：不要保存完整音频，而是保存能稳定重现、又足够区分不同录音的 audio fingerprint。

#### 7.3 Spectral-peak fingerprint

经典指纹方法使用谱峰。谱峰是 spectrogram 中局部时间-频率邻域内的显著峰值。

流程：

```text
audio
-> STFT / spectrogram
-> local peak picking
-> constellation map
-> peak pairing
-> hash generation
-> inverted index
-> offset voting
-> identification result
```

##### 7.3.1 Constellation map

把谱峰点表示为：

```text
(time_index, frequency_bin)
```

所有谱峰点构成 constellation map。它像星图一样，只保留少量稳定峰值，而不是完整谱图。

为什么谱峰适合做 fingerprint：

- 很多谱峰在 MP3 压缩后位置仍然稳定。
- 背景噪声会污染谱图，但部分强峰仍可保留。
- 谱峰是局部特征，适合短查询。
- 只存坐标，表示紧凑。

但只用单个谱峰不够具体。不同歌曲可能在相同频率 bin 上有很多峰，误匹配会多。

##### 7.3.2 Peak pairing 和 hash

为了提高 specificity，常用谱峰对构造 hash。

对每个 anchor peak，定义一个 target zone，在附近寻找若干 target peaks。每个峰对形成一个 hash：

```text
hash = (frequency_anchor, frequency_target, time_delta)
value = (track_id, time_anchor)
```

其中 `time_delta = time_target - time_anchor`。hash 不包含绝对时间，因此对查询片段在原曲中的平移位置不敏感。

一个数据库条目可以写成：

```text
hash -> (track_id, anchor_time)
```

查询音频也提取同样的 hash。只要查询片段来自某首歌，它的许多 hash 会在数据库中命中同一个 `track_id`，并且时间偏移一致。

#### 7.4 Inverted index：倒排索引

暴力匹配不可扩展。假设有百万首歌，每次查询都与每首歌每个时间位置比对，运行时间不可接受。

倒排索引的思想和书本索引类似：

```text
keyword -> pages where keyword appears
hash    -> list of occurrences where hash appears
```

对音频 fingerprint：

```text
inverted_index[hash] = [
    (track_id_1, time_1),
    (track_id_2, time_2),
    ...
]
```

查询时：

```text
for each query_hash at query_time tq:
    retrieve all (track_id, database_time td) from index
    offset = td - tq
    vote for (track_id, offset)
```

如果查询来自某首歌，那么大量 hash 会投给同一个 `(track_id, offset)`。最终找投票峰值即可。

这种 offset voting 很重要。单个 hash 命中不可靠，但大量 hash 在同一时间偏移上聚集，说明查询片段和数据库片段整体对齐。

#### 7.5 Fingerprint 系统的常见权衡

谱峰密度：

- 太少：鲁棒性差，短查询可能命中不足。
- 太多：存储大、查询慢、误匹配增加。

Hash specificity：

- hash 太粗：很多不同音频共享同一 hash，倒排列表很长。
- hash 太细：轻微失真就导致 hash 不一致。

Target zone：

- 太小：hash 数少，对噪声敏感。
- 太大：hash 数多，计算和索引负担增加。

时间/频率量化：

- 量化粗：更鲁棒但更容易碰撞。
- 量化细：更具体但更怕失真。

一个好的 fingerprint 不是“尽可能精确描述音频”，而是在 robustness、specificity、compactness、scalability 之间折中。

#### 7.6 Audio matching：匹配音乐内容片段

Audio matching 比 audio identification 更宽松。它不一定要求同一录音，而是希望找到音乐上对应的片段。

例子：

- 查询是 Beethoven 第五交响曲某个主题，数据库里有不同指挥版本。
- 查询片段速度略有变化。
- 查询和数据库音色、录音环境不同。
- 查询可能是同一作品的不同演奏。

这时 spectral-peak fingerprint 往往太具体。不同演奏的谱峰位置、音色、细节差异很大。需要更抽象、更音乐化的特征，例如 chroma 或 CENS。

典型流程：

```text
query audio
-> chroma / CENS sequence X

database audio
-> chroma / CENS sequence Y

X vs subsequences of Y
-> similarity or cost matrix
-> matching positions
```

#### 7.7 Feature design for audio matching

Audio matching 需要对以下变化更稳健：

- 不同音量。
- 不同音色和乐器。
- 轻微速度差。
- 局部演奏差异。
- 录音质量差异。

因此常用：

- chroma：保留和声/音级信息，弱化音色和八度。
- normalized chroma：弱化响度。
- smoothed chroma：弱化局部细节。
- CENS：通过统计、量化、降采样得到更稳健的 chroma variant。

但抽象也有代价。CENS 对不同演奏更稳健，但时间定位更粗，细节区分能力下降。

#### 7.8 Diagonal matching

Diagonal matching 假设查询和匹配片段速度大致一致。先计算 query sequence `X` 和 database sequence `Y` 的局部 cost matrix：

```text
C(n, m) = cost(x_n, y_m)
```

如果 chroma 已经归一化，常用 cosine distance：

```text
cost(x, y) = 1 - dot(x, y)
```

然后把 `X` 沿着 `Y` 平移。每个平移位置对应 cost matrix 中一条对角线，沿对角线求平均或求和：

```text
matching_cost(m) = average over n of C(n, m+n)
```

低 cost 的位置就是候选匹配。

优点：

- 简单。
- 快。
- 容易解释和可视化。

缺点：

- 不适合明显 tempo difference。
- 不适合查询内部有 rubato 或局部伸缩。
- 如果结构有插入、删除、重复，固定对角线会失败。

#### 7.9 DTW-based matching

DTW-based matching 允许时间伸缩。和 Chapter 3 的全局 DTW 不同，这里通常是 subsequence DTW：在长序列 `Y` 中寻找最适合短序列 `X` 的子序列。

思路：

```text
X = query feature sequence
Y = long database feature sequence
C(n, m) = local cost
find subsequence Y[a:b] minimizing DTW distance to X
```

关键修改：

- 允许 alignment 从 `Y` 的任意位置开始。
- 允许 alignment 在 `Y` 的任意位置结束。
- 对 `X` 仍然要完整匹配。
- 通过 accumulated cost matrix 和 backtracking 找最佳片段。

优点：

- 能处理 tempo difference。
- 能处理局部 timing variation。
- 比 diagonal matching 更灵活。

缺点：

- 计算更重。
- 如果特征太抽象，可能产生错误对齐。
- 需要路径约束，否则可能出现不合理伸缩。

实用经验：先用粗特征或索引找到候选区域，再对候选做 DTW 精排，比全库 DTW 更可行。

#### 7.10 Version identification：版本识别

Version identification 的目标是：给一首完整查询曲目，在数据库中找同一作品的不同版本。

版本可能包括：

- 翻唱。
- 现场版。
- 不同演奏家版本。
- 不同编曲或配器。
- remix。
- medley 中的片段。
- DJ mix 或采样使用。
- 转调、变速、结构删改。

它比 audio matching 更难，因为相似性不再只是“这段音频是否对应那段音频”，而是“这些录音是否共享某些音乐本质元素”。

版本之间可能变化：

- tempo：整体速度和局部 expressive timing 都可能不同。
- key：可能转调。
- instrumentation：乐器和音色完全不同。
- structure：前奏、间奏、重复段、solo 可能增删。
- melody：翻唱或即兴可能改动旋律。
- lyrics and texture：人声、伴奏、混音可能变化。
- noise：现场掌声、观众声、环境声。

#### 7.11 Version identification pipeline

一个常见版本识别流程：

```text
query recording
-> chroma / CENS sequence X

database recording
-> chroma / CENS sequence Y

X, Y
-> transposition handling
-> similarity matrix
-> enhancement / thresholding
-> local alignment
-> document-level similarity score
-> ranked retrieval list
```

为什么用 chroma/CENS：

- 同一作品通常保留某些 tonal progression。
- chroma 对音色和八度变化更稳健。
- CENS 进一步弱化局部演奏细节。

为什么做 local alignment：

- 两个版本不一定从同一结构开始。
- 可能只有副歌相似，前奏或间奏不同。
- 可能有插入、删除、重复。

#### 7.12 转调处理

如果版本发生转调，chroma 会循环移位。例如整体升高一个半音，12 维 chroma 向量整体循环移动一格。

处理方式：

```text
for shift in 0..11:
    shift one chroma sequence
    compute similarity / alignment score
choose best shift
```

也可以在计算 frame similarity 时直接取 12 种 shift 中的最大相似度。

代价：

- 计算量增加。
- 对本来不相关但局部和声常见的歌曲，误匹配风险增加。

#### 7.13 Local alignment 和 similarity score

版本识别常构造 similarity matrix：

```text
S(n, m) = similarity(x_n, y_m)
```

然后通过阈值和惩罚把矩阵变成适合局部路径搜索的分数矩阵：

- 相关位置给正分。
- 不相关位置给负分。
- 路径可以跳过开头和结尾。
- 路径中允许有限 gap，但 gap 会扣分。

这和生物序列中的 local alignment 思想相似：不要求整条序列全局对齐，而是寻找最高分的共同子序列区域。

输出的 document-level score 可以来自：

- 最优局部路径总分。
- 最优路径长度。
- 分数归一化后的相似度。
- 多个局部匹配片段的合并分数。

#### 7.14 检索评价

检索评价和分类评价不同，重点是排序质量。用户通常关心正确结果排在多靠前。

常见指标：

- Precision@k：前 k 个结果中有多少是相关结果。
- Recall@k：所有相关结果中有多少出现在前 k 个。
- Average Precision：沿排序列表累积计算 precision。
- MAP：Mean Average Precision，对多个 query 的 AP 求平均。
- MRR：Mean Reciprocal Rank，第一个正确结果排名的倒数平均。
- ROC / PR curve：看阈值变化下的误报和召回。

对 audio identification，还要看：

- top-1 accuracy。
- 识别延迟。
- 短查询长度下的成功率。
- 噪声、压缩、混响条件下的鲁棒性。
- false positive rate，因为误识别比“无法识别”更糟。

对 audio matching，还要看：

- 匹配片段边界是否准确。
- 时间偏移误差。
- 是否找全所有重复出现位置。
- tempo mismatch 下是否仍能匹配。

对 version identification，还要看：

- 相关版本是否排在前面。
- 不同风格、转调、改编程度下性能如何。
- 是否把同调性、常见和声走向但不同歌曲误判为版本。

#### 7.15 Chapter 7 实践练习

练习 1：做一个简易 spectral peak fingerprint。

```text
1. 对几首短音频计算 spectrogram。
2. 在局部邻域中选 spectral peaks。
3. 画 constellation map。
4. 从一首歌截取 5 秒作为 query。
5. 通过 peak coordinate matching 找时间偏移。
```

练习 2：加入 peak-pair hash。

```text
1. 为每个 anchor peak 设置 target zone。
2. 生成 (f1, f2, dt) hash。
3. 建立 hash -> (track_id, time) 的倒排索引。
4. 查询时统计 (track_id, offset) 投票。
5. 观察投票直方图是否出现尖峰。
```

练习 3：测试鲁棒性。

```text
1. 对 query 加白噪声。
2. 对 query 做 MP3 压缩。
3. 对 query 做 EQ 或音量变化。
4. 比较谱峰保留率和识别成功率。
```

练习 4：实现 diagonal matching。

```text
1. 选同一作品的两个不同录音。
2. 提取 CENS 或 smoothed chroma。
3. 计算 cost matrix。
4. 沿对角线求 matching function。
5. 找局部最小值并听对应片段。
```

练习 5：实现 subsequence DTW。

```text
1. 用短 query 和长 database chroma 序列。
2. 修改 DTW 初始化，使 query 可从 database 任意位置开始匹配。
3. 在最后一行找最小累计 cost。
4. 回溯得到匹配起止位置。
5. 和 diagonal matching 比较 tempo difference 下的表现。
```

练习 6：版本识别小实验。

```text
1. 找同一首歌的原版和翻唱。
2. 提取 CENS。
3. 测试 12 种 chroma shift。
4. 构造 similarity matrix。
5. 用 local alignment 找共同片段。
6. 把不相关歌曲作为负例，比较分数分布。
```

#### 7.16 Chapter 7 常见错误

- 用 waveform 直接做检索。除非是非常受控的同一录音，否则 waveform 对时间偏移、设备、压缩、噪声太敏感。
- 以为 fingerprint 能识别翻唱。谱峰 fingerprint 主要适合同一录音或非常接近的音频，不适合跨编曲版本。
- 倒排索引只看 hash 命中数，不看 offset 一致性。真正可靠的是同一 track 和同一 offset 的集中投票。
- hash 设计过细。轻微噪声或压缩会让 hash 全部失效。
- hash 设计过粗。倒排列表过长，误报和查询时间都会增加。
- 用 chroma 做所有检索。chroma 对和声有用，但丢掉音色、节奏、旋律细节；对无明显调性的音频效果有限。
- 把 diagonal matching 用在明显变速的场景。速度差大时，应考虑 DTW 或多尺度匹配。
- 版本识别只做全局 DTW。版本可能结构不同，局部对齐通常更合理。
- 评价只看某个 query 成功。检索系统必须看大量 query 上的排序指标和 false positive。

### 8. 两章之间的统一视角

Chapter 6 和 Chapter 7 的共同点是：都不直接处理原始 waveform，而是先构造任务相关的中层表示。

| 任务 | 中层表示 | 后续算法 |
| --- | --- | --- |
| onset detection | novelty function | peak picking |
| tempo estimation | tempogram | peak selection / tracking |
| beat tracking | novelty + tempo prior | PLP / dynamic programming |
| audio identification | spectral peak fingerprint | inverted index + offset voting |
| audio matching | chroma / CENS | diagonal matching / subsequence DTW |
| version identification | robust chroma + similarity matrix | transposition handling + local alignment |

更抽象地看：

```text
变化检测 -> novelty -> onset / beat
周期检测 -> tempogram -> tempo / pulse
稳定局部结构 -> fingerprint -> identification
音乐语义相似 -> chroma/CENS -> matching / version retrieval
```

真正的工程能力在于知道什么时候保留细节，什么时候丢掉细节：

- 识别同一录音：需要高 specificity，保留谱峰局部关系。
- 匹配不同演奏：需要弱化音色和局部 timing，使用 chroma/CENS。
- 找翻唱版本：需要更强不变性，但要小心误报。
- 跟踪 beat：需要既听局部 onset，也服从全局周期。

### 9. 最小项目路线

如果要把这两章学扎实，可以按以下顺序做项目：

1. Novelty visualizer：输入音频，输出 waveform、spectrogram、spectral novelty 和 onset peaks。
2. Tempogram explorer：输入 novelty，输出 Fourier/autocorrelation tempogram，标出候选 BPM。
3. DP beat tracker：给定 tempo prior，输出 beat sequence，并可视化 DP 选择。
4. Fingerprint identifier：建立小型 hash index，完成短片段识别。
5. Chroma matcher：用 diagonal matching 找不同录音中的相同主题。
6. Subsequence DTW matcher：处理不同 tempo 的片段匹配。
7. Cover/version retrieval demo：用 CENS、转调处理和 local alignment 给候选版本排序。

每个项目都要保留可视化。MIR 调试最重要的不是只听最终结果，而是看 novelty curve、tempogram、cost matrix、similarity matrix、vote histogram。很多错误一画出来就很明显。

---

## 第五篇：音频分解与全书实践路线：Chapter 8 + 总训练计划

本稿对应 `Fundamentals of Music Processing` 的 Chapter 8: Musically Informed Audio Decomposition，并补充全书实践路线、项目路线、训练计划、术语速查和常见错误。写法不是逐字摘录，而是把书中的关键概念转成适合中文学习者循序渐进掌握的笔记。

### 1. Chapter 8 的位置：从“分析音乐”走向“拆开音乐”

前面章节的大多数任务，是把音乐变成某种中层表示，然后做识别、对齐、检索或标注：

```text
audio
-> feature
-> similarity / model / dynamic programming
-> labels / beats / matches / sections
```

Chapter 8 的问题更进一步：音频不是一个干净对象，而是多个声源、多个声部、多个事件混在一起的结果。我们不只想知道“这段音乐是什么”，还想把它拆成更有意义的成分。

典型目标包括：

- 把音乐拆成 harmonic component 和 percussive component。
- 从复调录音中提取主旋律的 F0 轨迹。
- 用 melody contour 构造旋律/伴奏分离。
- 用 NMF 把谱图拆成频谱模板和时间激活。
- 在有乐谱或 MIDI 辅助时，把音频拆到音符、声部或左右手级别。

全章的总线索可以概括为：

```text
混合音频
-> 时间-频率表示
-> 利用音乐结构先验
-> mask / trajectory / matrix factorization
-> 重建或解释各个成分
```

这里的“musically informed”非常重要。它不是盲目地让算法自己发现一切，而是把音乐知识放进处理流程：谐波成分在谱图上常是水平线，打击成分常是垂直线；旋律通常有连续的 F0 轨迹；乐谱能提供音高、起止时间和声部分组；非负谱图适合用加性模板解释。

### 2. 音频分解的基本困难

#### 2.1 混合是容易的，反混合是困难的

录音制作中，多轨可以被混成一个 stereo 或 mono 文件：

```text
vocal track + guitar track + bass track + drums track
-> mixed audio
```

音频分解想做的是反方向：

```text
mixed audio
-> vocal / guitar / bass / drums
```

这在数学和工程上都困难，因为混合过程会丢失信息。两个声源在同一时间、同一频率区域出现时，谱能量叠在一起，单凭一个混合波形很难判断每个声源贡献了多少。

#### 2.2 音乐声源不满足很多理想假设

一些通用源分离方法希望声源统计独立，或者麦克风通道数足够多。但音乐里经常不是这样：

- 乐器数量可能多于录音通道数。
- 同一首歌里乐器节奏高度相关。
- 和声乐器的频率成分彼此有整数倍关系。
- 鼓、贝斯、吉他、键盘常常在同一拍点同时出现。
- 混响、压缩、母带处理会让声源边界更模糊。

所以音乐音频分解通常需要音乐先验，而不是只靠通用统计假设。

#### 2.3 分解结果既要“可听”，也要“可解释”

音频分解有两个层次：

- 分析层：得到 F0 轨迹、谱图成分、NMF 模板、mask 等。
- 合成层：把某个成分重建成可以播放的 waveform。

有些结果看起来合理，但听起来有金属感、泄漏、相位伪影；也有些结果听起来能用，但不一定对应清晰的音乐语义。学习 Chapter 8 时要同时关心可视化、可听性和任务目标。

### 3. HPSS：Harmonic-Percussive Source Separation

HPSS 是 Chapter 8 最直观、最适合入门实现的分解任务。它的目标不是分离每件乐器，而是把音频分为两大类：

- `harmonic`：有稳定音高、持续时间较长的成分，例如人声元音、弦乐长音、钢琴延音、吉他和弦。
- `percussive`：短促、宽频、时间定位强的成分，例如鼓、拍手、敲击声、钢琴击弦瞬态。

#### 3.1 谱图中的水平结构与垂直结构

STFT spectrogram 把音频展开成时间-频率平面：

```text
horizontal axis: time frames
vertical axis: frequency bins
value: magnitude / power
```

在这个平面上：

- harmonic sound 频率较稳定，所以能量沿时间方向延伸，表现为水平线。
- percussive sound 时间很短，但能量扩散到很多频率，表现为垂直线。

这就是 HPSS 的核心观察：

```text
horizontal structures -> harmonic component
vertical structures   -> percussive component
```

注意：这只是近似。真实乐器常同时包含两种成分。钢琴音一开始有强 transient，后面有 harmonic decay；吉他拨弦也一样；鼓中的 tom 可能有明显音高；人声中的辅音可能很 percussive。

#### 3.2 HPSS 的完整流程

基本流程如下：

```text
audio waveform
-> STFT
-> magnitude or power spectrogram Y
-> horizontal median filtering 得到 harmonic-enhanced spectrogram
-> vertical median filtering 得到 percussive-enhanced spectrogram
-> binary mask 或 soft mask
-> apply masks to original complex STFT
-> inverse STFT / overlap-add
-> harmonic waveform + percussive waveform
```

为什么 mask 要作用在 original complex STFT 上？因为重建 waveform 需要相位信息。只对 magnitude 做处理只能得到分析图，不能直接恢复高质量声音。

### 4. Median Filtering：用中值滤波增强水平/垂直结构

#### 4.1 中值滤波的直觉

median filtering 会用局部邻域的中位数替代当前值。它对尖峰和离群点不敏感。

在一维序列中，如果某个点突然很高，但前后点都不高，中值滤波会削弱这个突出的尖峰。反过来，如果一段连续区域都较高，中值滤波会保留它。

#### 4.2 横向中值滤波：保留 harmonic

对每个频率 bin，沿时间方向做中值滤波：

```text
fix frequency k
look across neighboring time frames
take median
```

如果某个频率持续存在，沿时间方向的邻域里很多点都高，中位数也高，因此水平结构被保留。短促的打击声只在少数时间帧很高，会被视为时间方向的离群点而削弱。

结果是 harmonic-enhanced spectrogram，常记作：

```text
Y_h_tilde
```

#### 4.3 纵向中值滤波：保留 percussive

对每个时间帧，沿频率方向做中值滤波：

```text
fix time n
look across neighboring frequency bins
take median
```

如果某个打击事件在同一时间扩散到很多频率，频率方向邻域里很多点都高，中位数也高，因此垂直结构被保留。某个稳定谐波只占少数频率 bin，会被视为频率方向的离群点而削弱。

结果是 percussive-enhanced spectrogram，常记作：

```text
Y_p_tilde
```

#### 4.4 滤波长度的影响

横向滤波长度 `L_h` 和纵向滤波长度 `L_p` 是关键参数。

`L_h` 太小：

- harmonic 增强不明显。
- 鼓点残留较多。

`L_h` 太大：

- 快速旋律、滑音、颤音可能被过度平滑。
- attack 和短音可能被削弱。

`L_p` 太小：

- percussive 增强不明显。
- 宽频瞬态保留不足。

`L_p` 太大：

- 低音鼓或带音高的打击乐可能被扩得太宽。
- 高频噪声可能被误当成 percussive。

初学者可以从库函数默认值开始，再用谱图和听感调参。不要只看一项指标；HPSS 的结果通常需要听 harmonic stem、percussive stem 和 residual leakage。

### 5. Mask：从增强谱图到分离谱图

中值滤波得到的是两个“增强版本”，不是最终分离结果。下一步要生成 time-frequency mask，决定每个时间-频率 bin 分给 harmonic 还是 percussive。

#### 5.1 Binary Mask

binary mask 是硬分配：

```text
if Y_h_tilde(n, k) >= Y_p_tilde(n, k):
    M_h(n, k) = 1
    M_p(n, k) = 0
else:
    M_h(n, k) = 0
    M_p(n, k) = 1
```

优点：

- 简单。
- 分离边界清楚。
- 适合教学和可视化。

缺点：

- 太武断。
- 一个 bin 里可能同时有 harmonic 和 percussive 能量，硬分配会造成伪影。
- 重建声音可能更粗糙。

#### 5.2 Soft Mask

soft mask 是比例分配：

```text
M_h(n, k) = Y_h_tilde(n, k) / (Y_h_tilde(n, k) + Y_p_tilde(n, k) + epsilon)
M_p(n, k) = Y_p_tilde(n, k) / (Y_h_tilde(n, k) + Y_p_tilde(n, k) + epsilon)
```

也可以加入 power 参数，让强者更强、弱者更弱：

```text
M_h = Y_h_tilde^p / (Y_h_tilde^p + Y_p_tilde^p + epsilon)
```

`p` 越大，越接近 binary mask。

优点：

- 更平滑。
- 听感通常更自然。
- 对混合 bin 更合理。

缺点：

- 分离不够干净。
- stem 之间会有更多泄漏。

#### 5.3 Mask 必须作用于复数 STFT

如果原始 STFT 是：

```text
X(n, k) = magnitude(n, k) * exp(i * phase(n, k))
```

则分离 STFT 通常写成：

```text
X_h(n, k) = M_h(n, k) * X(n, k)
X_p(n, k) = M_p(n, k) * X(n, k)
```

这样做保留了原始 phase。它不完美，因为两个真实声源的相位并不一定能被原始混合相位准确代表；但在很多工程场景中，这是一个简单有效的近似。

### 6. ISTFT 与 Reconstruction：为什么“变回声音”不只是反变换

#### 6.1 STFT 分析与 overlap-add

STFT 的基本过程：

```text
audio
-> split into overlapping frames
-> multiply each frame by window
-> DFT each windowed frame
```

inverse STFT 的基本过程：

```text
complex STFT
-> inverse DFT each frame
-> overlap-add frames
-> waveform
```

要可靠重建，window 和 hop size 要配合。直觉上，重叠窗口相加时不能在某些采样点全为零，也不能造成严重能量起伏。

#### 6.2 原始 STFT 的重建相对容易

如果 STFT 没有被修改，且 window/hop 满足重建条件，那么 overlap-add 可以恢复原始信号，最多只有数值误差。

典型可用组合：

- Hann window + 合理 hop size。
- sqrt-Hann analysis/synthesis 配合。
- 满足 COLA 或类似 overlap-add 条件的窗口设置。

实际使用库函数时，要确认：

- `center` 参数是否一致。
- `n_fft`、`win_length`、`hop_length` 是否一致。
- 分析窗和合成窗是否匹配。
- 输出长度是否裁剪或 padding。

#### 6.3 Modified STFT 的重建更麻烦

一旦你修改了 STFT，例如：

- 对某些 bin 乘 mask。
- 删除某些 frame。
- 改 magnitude。
- 保留 magnitude 但替换 phase。

修改后的矩阵可能不再是任何真实 waveform 的合法 STFT。这叫 STFT consistency 问题。换句话说，你手里的 time-frequency 矩阵看起来像谱图，但未必存在一个信号，其 STFT 正好等于它。

这会带来：

- 金属感。
- musical noise。
- transient smearing。
- pre-echo。
- harmonic/percussive 互相泄漏。
- 重建后再做 STFT 与目标谱图不一致。

#### 6.4 为什么只有 magnitude 不够

spectrogram 常指 magnitude 或 power，而 waveform 重建需要 complex STFT：

```text
complex STFT = magnitude + phase
```

如果只有 magnitude：

- 可以用原始 mixture phase 近似。
- 可以用 Griffin-Lim 等算法估计 phase。
- 可以使用神经声码器或专门的 phase reconstruction 方法。

初学者常见错误是把 `abs(STFT)` 当作能直接 `istft` 的对象。实际上 `istft` 需要复数谱，或者至少需要某种相位假设。

#### 6.5 HPSS 重建的实用建议

实践时建议遵守：

- mask 作用于原始 complex STFT，而不是只作用于 dB 谱图。
- 不要在 log/dB 频谱上直接做线性 mask。
- 保留分析参数，ISTFT 时完全复用。
- 分离后检查 `harmonic + percussive` 是否接近原音频。
- 同时听两个 stem，不只听其中一个。
- 可视化分离谱图，观察水平/垂直结构是否符合预期。

### 7. Melody / F0 Extraction：从复调音频中追踪主旋律

旋律提取的目标通常不是直接输出音符，而是估计主旋律的 fundamental frequency trajectory：

```text
time -> F0 in Hz or cents
```

它可以进一步转成：

- melody contour。
- note sequence。
- vocal pitch track。
- melody/accompaniment mask。
- query-by-humming 的输入。
- 自动扒谱或 lead sheet 生成的中间结果。

#### 7.1 F0 与 pitch 的区别

`F0` 是声学上的基频，单位 Hz。`pitch` 是人的听觉音高感知。二者强相关，但不是完全等同。

复杂音中，声音通常包含：

```text
F0, 2F0, 3F0, 4F0, ...
```

这些 partials 共同让我们听到某个音高。即使 F0 本身能量很弱，甚至被录音设备或乐器特性削掉，人耳仍可能从泛音关系中感知到对应音高，这就是 missing fundamental 相关现象。

#### 7.2 旋律提取为什么难

复调音乐中的 F0 提取困难包括：

- 泛音可能比基频更强。
- 多个乐器的 partials 会交叉。
- 伴奏可能比旋律更响。
- 人声有 vibrato，F0 会连续摆动。
- 滑音和弯音不是稳定半音格点。
- 鼓和噪声会产生强谱峰。
- octave error 很常见，算法可能把 `F0` 误判成 `2F0` 或 `F0/2`。
- 主旋律并不总是存在，每帧还要判断 voiced/unvoiced。

#### 7.3 旋律提取的基本 pipeline

一个典型流程：

```text
audio
-> STFT / CQT / log-frequency representation
-> spectral peak picking
-> instantaneous frequency refinement
-> salience representation
-> F0 candidates per frame
-> temporal tracking with continuity constraints
-> melody F0 trajectory
```

如果要做旋律分离，还会继续：

```text
F0 trajectory
-> include harmonic bands around F0, 2F0, 3F0...
-> construct melody mask
-> complement mask for accompaniment
-> ISTFT reconstruction
```

### 8. Instantaneous Frequency：用 phase 提高频率估计

#### 8.1 为什么 DFT bin 不够精细

DFT 的频率格点是离散的：

```text
F_bin(k) = k * Fs / N
```

真实 sinusoid 的频率不一定正好落在某个 bin 上。它可能在两个 bin 之间，导致 spectral leakage，也导致频率估计只能粗略定位。

例如采样率 `Fs = 44100`，`N = 2048`，bin spacing 约为：

```text
44100 / 2048 ≈ 21.53 Hz
```

在低频区，21 Hz 的误差可能已经非常大。旋律提取需要比 bin spacing 更细的频率估计。

#### 8.2 phase change 的直觉

一个稳定 sinusoid 在相邻 STFT frame 中，其 phase 会按频率稳定前进。若我们知道：

- 上一帧 phase。
- 当前帧 phase。
- 两帧间隔时间。
- bin center frequency 的预期 phase advance。

就可以比较“实际 phase advance”和“预期 phase advance”的差异，推断真实频率偏离 bin center 多少。

核心思想：

```text
frequency = phase change / time difference
```

实际处理中要处理 phase wrapping，因为 phase 通常只在一个周期范围内表示。两个 phase 数值看似差很大，可能只是跨过了周期边界。

#### 8.3 instantaneous frequency 的用途

在 Chapter 8 中，instantaneous frequency 主要用于：

- 细化谱峰频率。
- 构造更精确的 log-frequency spectrogram。
- 提高 F0 candidate 的定位。
- 改善 salience representation。

它也提醒我们：Chapter 2 中的 phase 不是可有可无。很多初级 MIR 特征只用 magnitude，但高级音频处理、变速、重建、频率细化会重新需要 phase。

#### 8.4 常见误区

- 误以为谱峰所在 bin 就是真实频率。
- 忽略 phase wrapping。
- hop size 太大，导致 phase advance 难以解释。
- 用 dB 谱图做 IF 估计。
- 对 percussive/noisy 成分强行估计稳定频率。

### 9. Salience Representation：把谱峰整合成 F0 候选图

#### 9.1 salience 是什么

salience representation 可以理解为“F0 候选强度图”：

```text
horizontal axis: time
vertical axis: candidate F0
value: how salient this F0 is
```

它不是普通 spectrogram。普通 spectrogram 的纵轴是频率成分；salience map 的纵轴是候选基频。一个候选 F0 的 salience 通常来自它的多个 harmonic partials。

#### 9.2 Harmonic Summation

如果候选 F0 是 `f`，则检查：

```text
f, 2f, 3f, 4f, ...
```

这些位置是否有能量。如果多个 harmonic 都有能量，则 `f` 作为基频的可能性增加。

直觉流程：

```text
for each time frame:
    for each candidate F0:
        salience = weighted sum of spectral energy near h * F0
```

权重通常会让低阶 harmonic 更重要，因为高阶 harmonic 更容易和其他声源混淆，也更容易受噪声和频率分辨率影响。

#### 9.3 为什么 salience 比直接找最大谱峰更好

直接找最大谱峰有很多问题：

- 最大峰可能是泛音，不是基频。
- 伴奏乐器可能产生更强峰。
- 基频能量可能很弱。
- 鼓或噪声可能产生短暂强峰。

salience 使用 harmonic pattern 而不是单个峰，因此更符合复合音的结构。

#### 9.4 从 salience 到 F0 trajectory

每帧最大 salience 不一定就是旋律，因为帧级估计会抖动。需要加入时间连续性：

```text
local score: salience at candidate F0
transition score: penalty for large F0 jumps
global objective: best path over time
```

这可以用 dynamic programming 或 Viterbi 风格算法实现：

```text
salience map
-> candidate graph
-> continuity constraints
-> optimal F0 path
```

这和全书反复出现的模式一致：

```text
局部证据 + 全局路径约束 = 稳定序列估计
```

### 10. Melody Separation：从 F0 轨迹到旋律/伴奏分离

如果已经得到主旋律 F0 轨迹，就可以构造 melody mask。

#### 10.1 基本方法

对每个时间帧：

1. 取当前 F0。
2. 找到 `F0, 2F0, 3F0...` 对应的频率区域。
3. 在这些 harmonic 附近保留能量。
4. 其他区域给 accompaniment。

流程：

```text
F0 trajectory
-> harmonic bands
-> melody mask
-> X_melody = M_melody * X
-> X_accompaniment = (1 - M_melody) * X
-> ISTFT
```

#### 10.2 主要限制

- 旋律与伴奏重叠在同一 harmonic 区域时无法干净分开。
- F0 轨迹错了，mask 会跟着错。
- vibrato、滑音需要足够宽的 frequency band。
- band 太宽会带入伴奏，太窄会削掉旋律音色。
- consonants 和 breath noise 不一定跟随 harmonic F0。
- 旋律静音段需要正确处理，否则会把伴奏误分给旋律。

#### 10.3 评价方式

旋律提取和旋律分离是两个不同评价问题。

旋律提取常看：

- voiced/unvoiced accuracy。
- raw pitch accuracy。
- raw chroma accuracy。
- overall accuracy。
- octave error。

旋律分离常看：

- SDR / SIR / SAR 等源分离指标。
- stem leakage。
- 听感质量。
- 下游任务表现，例如人声重混、卡拉 OK、歌词对齐。

### 11. NMF：Nonnegative Matrix Factorization

NMF 是 Chapter 8 的另一个核心技术。它把非负矩阵分解成两个非负矩阵的乘积：

```text
V ≈ W H
```

在音频中，`V` 通常是 magnitude spectrogram 或 power spectrogram：

```text
V: frequency bins x time frames
W: frequency bins x components
H: components x time frames
```

直觉解释：

- `W` 的每一列是一个 spectral template。
- `H` 的每一行是对应 template 的 activation curve。
- `R` 是 component 数量，也叫 rank。

即：

```text
谱图 ≈ 若干频谱形状 × 它们在时间上的出现强度
```

#### 11.1 为什么非负很适合音频谱图

magnitude/power spectrogram 没有负值。声音能量可以近似看作非负成分的叠加：

```text
kick template * kick activation
+ snare template * snare activation
+ piano-C4 template * C4 activation
+ vocal-vowel template * vocal activation
...
```

非负约束让分解更容易得到“部件组合”的解释，而不是正负抵消的抽象线性组合。

#### 11.2 NMF 的基本学习过程

给定 `V` 和 rank `R`：

1. 初始化 `W` 和 `H`，通常随机非负。
2. 计算 `WH` 与 `V` 的差异。
3. 用更新规则迭代改善 `W` 和 `H`。
4. 停止于固定迭代次数或收敛条件。

常用目标函数包括：

- Euclidean distance。
- KL divergence。
- Itakura-Saito divergence。

书中重点介绍了基础 NMF 和乘法更新规则。乘法更新的好处是，如果初始化非负，更新后仍保持非负。

#### 11.3 rank 的含义与风险

`R` 太小：

- 多个声源被迫混在一个 template。
- 分解欠拟合。
- 音符或鼓件区分不开。

`R` 太大：

- 一个声源被拆成多个 template。
- 结果难解释。
- 更容易过拟合噪声或局部事件。

在音乐中，rank 可以按任务设定：

- 如果分解 8 个不同钢琴音高，可以从 `R = 8` 开始。
- 如果分离鼓件，可以从 kick/snare/hat 等数量估计。
- 如果是无监督乐器分离，rank 需要实验和可视化辅助。

#### 11.4 标准 NMF 为什么不一定有音乐意义

NMF 的分解不唯一。即使 `WH` 很接近 `V`，`W` 和 `H` 也不一定对应真实音符或乐器。

常见问题：

- 一个 template 混合多个音高。
- 一个音高被拆成多个 template。
- transient 被分散到许多 template。
- harmonic template 不符合真实泛音结构。
- activation 不像乐谱中的 note event。
- 不同随机初始化得到不同结果。

所以 Chapter 8 强调引入音乐先验。

### 12. Score-Informed / Musically Informed NMF

#### 12.1 Template Constraints

如果知道某些音高可能出现，可以用 harmonic template 初始化或约束 `W`。

例如某个 MIDI note number 对应基频 `F0`，则 template 可以在：

```text
F0, 2F0, 3F0, ...
```

附近放置能量。这样 `W` 的列更像真实乐器音高，而不是随机频谱形状。

#### 12.2 Activation Constraints

如果有对齐乐谱或 MIDI，就知道某些音符大概在哪些时间响。可以用 piano-roll 初始化或约束 `H`：

```text
note active in score -> corresponding activation allowed / initialized high
note inactive in score -> corresponding activation suppressed
```

这会让 NMF 更稳定，也更容易得到 notewise decomposition。

#### 12.3 Onset Models

很多乐器的 onset 和 sustain 频谱差异很大。钢琴、吉他、鼓尤其明显。

如果只用 harmonic templates，transient 可能会污染所有音高的 activation。可以扩展 NMF 模型，为 onset 或噪声性成分加入额外 templates，使 attack 部分有更合适的解释。

#### 12.4 用 NMF 结果做音频分解

假设已经得到：

```text
V ≈ W H
```

如果想分离左手和右手，或分离某几个音符，可以把 `H` 按目标分组：

```text
H_left, H_right
```

然后得到各组的估计谱图：

```text
V_left_hat  = W H_left
V_right_hat = W H_right
```

直接用这些估计谱图重建声音通常会有伪影。更常见的做法是把它们转成 soft masks：

```text
M_left = V_left_hat / (V_left_hat + V_right_hat + epsilon)
M_right = V_right_hat / (V_left_hat + V_right_hat + epsilon)
```

再作用于原始 complex STFT：

```text
X_left = M_left * X
X_right = M_right * X
```

这样保留原始音频中的细节，听感通常比直接合成 `WH` 更自然。

### 13. Chapter 8 的三条主线对比

| 主线 | 主要先验 | 中间表示 | 输出 | 优点 | 局限 |
| --- | --- | --- | --- | --- | --- |
| HPSS | 水平/垂直谱图结构 | median-filtered spectrogram, mask | harmonic/percussive stems | 简单直观，容易实现 | 不能分离具体乐器 |
| Melody/F0 extraction | 主旋律 F0 连续、泛音结构 | salience map, F0 trajectory | melody contour 或旋律 stem | 适合主旋律分析 | octave error、复调干扰 |
| NMF decomposition | 谱图由非负模板叠加 | W templates, H activations | component spectrograms/stems | 可解释、可加入乐谱约束 | 分解不唯一，rank 敏感 |

### 14. 全书实践路线：从表示到系统

全书可以看成从底层表示到复杂系统的训练路线。

#### 14.1 第一层：音乐与音频表示

对应 Chapter 1 和 Chapter 2。

目标：

- 知道 waveform、MIDI、piano-roll、spectrogram 的区别。
- 理解 frequency、pitch、octave、chroma、timbre。
- 掌握 DFT、FFT、STFT、window、hop size、magnitude、phase。

实践重点：

- 画 waveform。
- 画 linear spectrogram。
- 画 log-frequency spectrogram。
- 对比不同 window size 的时间/频率折中。
- 听同一音频经过不同滤波和重建后的差异。

#### 14.2 第二层：中层特征

对应 Chapter 3、4、5、6、7、8 中反复出现的 feature engineering。

重要中层表示：

- chroma。
- CENS。
- novelty function。
- tempogram。
- self-similarity matrix。
- spectral peaks / fingerprints。
- salience map。
- NMF templates and activations。

实践重点：

- 不要直接拿 waveform 做相似度。
- 先问任务需要什么不变性。
- 可视化每个 feature，确认它确实保留了目标信息。

#### 14.3 第三层：序列与矩阵算法

全书反复出现：

- DTW：对齐两个时间序列。
- dynamic programming：找全局最优路径。
- HMM / Viterbi：平滑标签序列。
- self-similarity matrix：发现重复结构。
- inverted index：让检索可扩展。
- NMF：把非负谱图拆成模板和激活。

核心模式：

```text
局部证据 -> 矩阵或图 -> 全局约束 -> 最优路径/分解/匹配
```

#### 14.4 第四层：任务系统

每个 MIR 项目都可以按下面模板设计：

```text
1. 输入是什么？
2. 输出是什么？
3. 输出需要多精确？
4. 哪些变化应该忽略？
5. 哪些信息必须保留？
6. 用什么中层表示？
7. 用什么模型或算法？
8. 如何评价？
9. 如何可视化调试？
10. 失败案例是什么？
```

### 15. 推荐项目路线

#### Project 1: Spectrogram Explorer

目标：理解音频进入 MIR 的第一步。

输入：

- 任意 WAV/MP3。
- 最好准备鼓声、钢琴、人声、弦乐各一段。

实现：

- 读取音频。
- 画 waveform。
- 画 STFT magnitude spectrogram。
- 画 dB spectrogram。
- 改变 `n_fft` 和 `hop_length`。
- 对比同一声音的时间/频率分辨率变化。

验收：

- 能解释为什么短窗更适合 transient。
- 能解释为什么长窗更适合 pitch。
- 能在谱图中指出 harmonic 和 percussive 结构。

#### Project 2: Chroma + DTW Synchronizer

目标：理解中层特征和动态规划。

输入：

- 同一首曲子的两个版本。
- 或一段 MIDI 合成音频和真实录音。

实现：

- 提取 chroma 或 CENS。
- 计算 cost matrix。
- 用 DTW 找 warping path。
- 可视化对齐路径。

验收：

- 能解释为什么 chroma 比 waveform 更适合同步。
- 能看出速度变化如何影响 warping path。

#### Project 3: Structure Analyzer

目标：理解 self-similarity matrix。

输入：

- 一首结构清晰的流行歌。

实现：

- 提取 beat-synchronous chroma 或 MFCC。
- 构造 self-similarity matrix。
- 计算 novelty curve。
- 尝试检测段落边界。

验收：

- 能在 SSM 中看到重复段。
- 能解释 checkerboard kernel 或 novelty peak 的意义。

#### Project 4: Simple Chord Recognizer

目标：理解 chroma、模板匹配和 HMM。

输入：

- 简单和弦进行音频。

实现：

- 提取 chroma。
- 构造 major/minor chord templates。
- 做 frame-wise matching。
- 加 Viterbi 平滑。

验收：

- 能说明 HMM 解决的是标签抖动，不是特征错误本身。
- 能分析错分来自 bass、转位、非和弦音还是 chroma 泄漏。

#### Project 5: Beat Tracker

目标：理解 onset、novelty、tempogram 和 beat。

输入：

- 节奏稳定的流行歌或鼓循环。

实现：

- 计算 spectral novelty。
- 做 peak picking。
- 计算 tempogram。
- 估计 tempo。
- 用 DP 或规则方法输出 beat positions。

验收：

- 能区分 onset、beat、tempo。
- 能解释 tempo doubling / halving。

#### Project 6: Audio Fingerprint

目标：理解内容检索与索引。

输入：

- 一个小型音频库。
- 若干查询片段，可加入噪声或压缩。

实现：

- 计算 spectrogram。
- 选 spectral peaks。
- 构造 peak pairs 和 hash。
- 建 inverted index。
- 用 offset voting 找匹配曲目。

验收：

- 能解释为什么 fingerprint 适合识别同一录音。
- 能解释为什么它不适合识别翻唱或改编。

#### Project 7: HPSS Lab

目标：掌握 Chapter 8 的第一个完整分解系统。

输入：

- 含鼓和和声乐器的音乐。

实现：

- STFT。
- 横向/纵向 median filtering。
- binary mask 和 soft mask。
- ISTFT 重建。
- 对比 harmonic/percussive stems。

实验：

- 改变 `L_h` 和 `L_p`。
- 比较 binary 和 soft mask。
- 检查 `x_h + x_p` 与原音频的差异。

验收：

- 能解释每个参数对听感和泄漏的影响。
- 能指出哪些乐器成分被错误分配。

#### Project 8: Melody F0 Tracker

目标：理解 salience 和 F0 trajectory。

输入：

- 单旋律音频。
- 简单复调音频。
- 人声旋律片段。

实现：

- 计算 STFT 或 CQT。
- 提取 spectral peaks。
- 构造 salience map。
- 每帧选 F0 candidates。
- 用 continuity constraint 做路径跟踪。

验收：

- 能识别 octave error。
- 能解释 vibrato 对 F0 track 的影响。
- 能区分 unvoiced frame 和 low-confidence frame。

#### Project 9: Melody / Accompaniment Separation

目标：把分析结果转成可听 stem。

输入：

- 带主旋律和伴奏的音频。

实现：

- 使用 Project 8 的 F0 trajectory。
- 构造 harmonic-band melody mask。
- 生成 accompaniment complement mask。
- ISTFT。

验收：

- 能听出 melody leakage 和 accompaniment leakage。
- 能解释 mask band width 的取舍。

#### Project 10: NMF Decomposition

目标：理解谱图分解。

输入：

- 简单钢琴片段或鼓循环。

实现：

- 计算 magnitude spectrogram `V`。
- 选择 rank `R`。
- 初始化 `W, H`。
- 用 NMF 迭代更新。
- 可视化 templates 和 activations。
- 用 soft masks 重建 components。

验收：

- 能解释 `W` 和 `H`。
- 能说明 rank 变化如何影响结果。
- 能发现标准 NMF 的不可解释分解。

#### Project 11: Score-Informed NMF

目标：进入进阶 MIR 系统设计。

输入：

- 音频。
- 对齐 MIDI 或乐谱转 piano-roll。

实现：

- 用乐谱音高初始化 harmonic templates。
- 用 piano-roll 初始化或约束 activations。
- 加入 onset templates。
- 按声部或音符分组重建。

验收：

- 能说明 score information 如何稳定 NMF。
- 能比较无监督 NMF 和 score-informed NMF 的差异。

### 16. 从入门到大师的训练计划

#### 阶段 0：听觉与可视化热身

周期：1 到 2 周。

目标：

- 看到谱图能大致判断声音类型。
- 听到声音能预测谱图形状。

训练：

- 每天选 5 段声音，画 waveform 和 spectrogram。
- 标出 transient、harmonic line、noise band、silence。
- 记录不同乐器在谱图中的典型形状。

达标：

- 能解释鼓、人声、钢琴、弦乐在谱图上的差异。

#### 阶段 1：信号处理基础

周期：2 到 4 周。

目标：

- 掌握 STFT 参数和重建。
- 不再把 spectrogram 当成普通图片。

训练：

- 手写或调用 STFT/ISTFT。
- 改变 window、hop、FFT size。
- 做低通、高通、带通和简单 mask。
- 比较有 phase 和无 phase 的重建。

达标：

- 能解释 magnitude、phase、window、hop size、overlap-add。

#### 阶段 2：MIR 中层表示

周期：4 到 6 周。

目标：

- 能按任务选择特征。

训练：

- 实现 chroma、novelty、tempogram、SSM 的最小版本。
- 对每种特征做可视化。
- 记录它保留什么、丢掉什么。

达标：

- 能回答“为什么这个任务不用 waveform 直接比较”。

#### 阶段 3：经典算法

周期：6 到 8 周。

目标：

- 掌握 DTW、Viterbi、DP beat tracking、NMF。

训练：

- 手写 DTW 并可视化 cost matrix。
- 手写 Viterbi 平滑和弦标签。
- 手写简化 NMF 或调用库后解释 `W/H`。
- 做一个小型 fingerprint 检索系统。

达标：

- 能把“局部证据 + 全局约束”的问题建模成路径或矩阵优化。

#### 阶段 4：分解与重建

周期：4 到 8 周。

目标：

- 真正理解 Chapter 8。

训练：

- 完成 HPSS Lab。
- 完成 melody F0 tracker。
- 完成 NMF decomposition。
- 对每个项目做听感、谱图和错误案例分析。

达标：

- 能解释为什么某个分离结果失败。
- 能提出合理的参数或先验改进。

#### 阶段 5：论文复现与系统化评估

周期：长期。

目标：

- 从会调用库进入能判断方法优劣。

训练：

- 复现一个 HPSS 或 melody extraction baseline。
- 在公开数据集上跑评价。
- 做 ablation：去掉 median filter、去掉 continuity、改变 rank。
- 写实验报告，包含数据、指标、可视化和失败案例。

达标：

- 能区分“demo 可用”和“研究结论可靠”。

#### 阶段 6：大师级能力

长期目标：

- 面对新 MIR 任务，能设计完整 pipeline。
- 能判断问题适合规则、动态规划、概率模型、矩阵分解还是神经模型。
- 能设计评价指标和错误分析。
- 能把音乐知识转成可计算约束。

大师级问题清单：

- 这个任务的目标听众或用户是谁？
- 错误容忍度是多少？
- 输出是给人看、给模型用，还是给音频引擎播放？
- 特征需要对哪些变化不敏感？
- 哪些信息绝不能丢？
- 模型失败时，如何定位是数据、特征、参数、算法还是评价的问题？

### 17. 术语速查

| 术语 | 中文理解 | 要点 |
| --- | --- | --- |
| waveform | 波形 | 声音振幅随时间变化 |
| sample rate | 采样率 | 每秒采样点数，例如 44100 Hz |
| frequency | 频率 | 物理振动频率，单位 Hz |
| pitch | 音高 | 听觉感知，不完全等同 frequency |
| F0 | 基频 | 复合音的基础频率，常决定 pitch |
| partial | 分音 | 构成声音的频率成分 |
| harmonic | 谐波 | F0 的整数倍分音 |
| inharmonicity | 非谐性 | partial 不精确落在整数倍位置 |
| timbre | 音色 | 频谱、包络、噪声、演奏方式共同决定 |
| transient | 瞬态 | 短暂快速变化，常见于 attack |
| onset | 起音点 | 音乐事件开始的位置 |
| STFT | 短时傅里叶变换 | 把音频变成时间-频率复数表示 |
| spectrogram | 谱图 | 通常是 STFT magnitude 或 power |
| phase | 相位 | 复数 STFT 的角度信息，重建和 IF 很重要 |
| magnitude | 幅度 | 频率成分强度 |
| power spectrogram | 功率谱图 | 常为 magnitude 的平方 |
| window | 窗函数 | STFT 中截取局部音频的权重函数 |
| hop size | 帧移 | 相邻 STFT frame 的间隔 |
| overlap-add | 重叠相加 | ISTFT 重建中的核心过程 |
| ISTFT | 逆 STFT | 从 complex STFT 回到 waveform |
| STFT consistency | STFT 一致性 | 修改后的谱图是否对应某个真实信号 |
| HPSS | 谐波/打击分离 | 按水平/垂直谱图结构分离 |
| median filter | 中值滤波 | 用局部中位数抑制离群点 |
| binary mask | 二值掩膜 | 每个 time-frequency bin 硬分配 |
| soft mask | 软掩膜 | 每个 bin 按比例分配 |
| Wiener filtering | 维纳式滤波 | 软 mask 的一种统计解释 |
| instantaneous frequency | 瞬时频率 | 用相位变化估计更精细频率 |
| phase wrapping | 相位环绕 | 相位跨周期导致数值跳变 |
| salience map | 显著性图 | 时间-F0 候选强度表示 |
| harmonic summation | 谐波求和 | 汇聚 F0 多个泛音的能量 |
| F0 tracking | 基频跟踪 | 从候选中选连续 F0 轨迹 |
| melody extraction | 旋律提取 | 估计主旋律 F0 或音符 |
| melody separation | 旋律分离 | 从音频中分离旋律 stem |
| NMF | 非负矩阵分解 | 把非负矩阵近似为 `W H` |
| template | 模板 | NMF 中 `W` 的列，常解释为频谱模式 |
| activation | 激活 | NMF 中 `H` 的行，表示模板何时出现 |
| rank | 秩/成分数 | NMF 的 component 数量 |
| score-informed | 乐谱辅助 | 用乐谱/MIDI 约束音频处理 |
| piano-roll | 钢琴卷帘 | 时间-音高矩阵表示 |
| chroma | 色度 | 12 个 pitch class 的能量表示 |
| CENS | 平滑稳健 chroma | 常用于同步和版本识别 |
| novelty function | 新颖度曲线 | 表示局部变化强度 |
| tempogram | 速度图 | 时间-tempo 的局部周期表示 |
| DTW | 动态时间规整 | 对齐两个时间序列 |
| HMM | 隐马尔可夫模型 | 用状态转移平滑标签序列 |
| Viterbi | 维特比算法 | 找最可能状态路径 |
| SSM | 自相似矩阵 | 序列与自身比较得到结构图 |
| fingerprint | 音频指纹 | 用稳健局部特征做识别 |
| inverted index | 倒排索引 | 从特征 hash 指向曲目和时间位置 |
| SDR | 源分离失真比 | 分离评价指标之一 |
| leakage | 泄漏 | 一个 stem 中混入其他源 |
| artifact | 伪影 | 处理引入的非真实声音缺陷 |

### 18. 常见错误与排查

#### 18.1 把 MIDI、乐谱和音频混为一谈

错误：

- 以为 MIDI 里有真实音色和混响。
- 以为乐谱能直接告诉你录音里每个声源的精确时间。
- 以为音频里显式存在 note labels。

排查：

- 明确输入是 symbolic 还是 audio。
- 如果用 score-informed 方法，确认乐谱已和音频对齐。

#### 18.2 把 spectrogram 当成普通图片处理

错误：

- 直接在 dB 图上做线性运算。
- 忽略频率轴、时间轴和相位。
- 修改 magnitude 后直接期望无损重建。

排查：

- 确认当前谱图是 linear magnitude、power 还是 dB。
- 重建时使用 complex STFT。
- 保存 STFT 参数。

#### 18.3 HPSS 中滤波方向弄反

错误：

- 沿时间滤波却以为增强 percussive。
- 沿频率滤波却以为增强 harmonic。

记忆：

```text
time direction median -> preserves horizontal -> harmonic
frequency direction median -> preserves vertical -> percussive
```

#### 18.4 mask 用错对象

错误：

- 把 mask 乘到 dB spectrogram。
- 对 magnitude 做了 mask 后丢掉 phase。
- mask 尺寸和 STFT 尺寸不一致。

排查：

- mask 应该与 STFT 的 time-frequency grid 对齐。
- 重建时通常使用 `X_component = M * X_original_complex`。

#### 18.5 忽略 window/hop 的重建条件

错误：

- STFT 和 ISTFT 参数不一致。
- hop 太大导致重建能量起伏。
- 忘记处理 padding 和中心对齐。

排查：

- 先测试 `istft(stft(x))` 是否接近 `x`。
- 再加入 mask 或其他修改。

#### 18.6 以为 phase 不重要

错误：

- 只学 magnitude spectrogram。
- 遇到 IF、重建、time-scale modification 时无法解释问题。

排查：

- 复习 complex STFT。
- 画 phase 差分。
- 理解 phase wrapping。

#### 18.7 旋律提取只取最大谱峰

错误：

- 最大峰可能是泛音或伴奏。
- 基频可能缺失。

排查：

- 用 harmonic summation 构造 salience。
- 加 voiced/unvoiced 判断。
- 加时间连续性约束。

#### 18.8 不处理 octave error

错误：

- 把 `2F0` 当成 `F0`。
- 把低一倍频率当成基频。

排查：

- 同时看 raw pitch accuracy 和 raw chroma accuracy。
- 观察 salience map 中平行轨迹。
- 调整 harmonic weights 和候选范围。

#### 18.9 NMF rank 随便选

错误：

- rank 太小导致混源。
- rank 太大导致碎片化。
- 不看 `W/H` 可视化。

排查：

- 从音乐先验估计 rank。
- 对不同 rank 做实验。
- 可视化 templates 和 activations。

#### 18.10 以为 NMF 分解一定有语义

错误：

- 看到 `V ≈ WH` 误以为每列 `W` 就是一件乐器。
- 忽略分解不唯一。

排查：

- 多次随机初始化。
- 加 harmonic initialization。
- 使用 score-informed constraints。
- 听每个 component。

#### 18.11 只听成功案例

错误：

- demo 上可用就以为方法稳健。
- 不看失败样本。

排查：

- 建立小测试集，包含鼓强、鼓弱、无鼓、强人声、强伴奏、混响大等情况。
- 每次改参数都记录失败模式。

#### 18.12 评价指标和目标不匹配

错误：

- 做旋律提取只听分离音频。
- 做源分离只看谱图。
- 做检索只测一个查询。

排查：

- 分析任务用 pitch/frame 指标。
- 分离任务用听感和源分离指标。
- 检索任务用 precision、recall、MAP、rank。

### 19. 学习 Chapter 8 的最小代码路线

即使最终使用成熟库，也建议按下面顺序亲手跑通。

#### 19.1 最小 HPSS

```text
load audio
X = STFT(x)
Y = abs(X)^2
Y_h_tilde = median_filter(Y, axis=time)
Y_p_tilde = median_filter(Y, axis=frequency)
M_h = Y_h_tilde / (Y_h_tilde + Y_p_tilde + eps)
M_p = Y_p_tilde / (Y_h_tilde + Y_p_tilde + eps)
x_h = ISTFT(M_h * X)
x_p = ISTFT(M_p * X)
```

必须检查：

```text
x_h + x_p ≈ x
```

#### 19.2 最小 F0 Tracker

```text
load audio
X = STFT(x)
peaks = spectral_peak_picking(abs(X))
peaks_refined = instantaneous_frequency(peaks, phase(X))
Z = harmonic_summation(peaks_refined)
F0_path = dynamic_programming(Z, transition_penalty)
```

必须检查：

- F0 path 是否连续。
- 静音段是否被误判。
- octave error 出现在哪里。

#### 19.3 最小 NMF

```text
load audio
X = STFT(x)
V = abs(X)
choose R
initialize W >= 0, H >= 0
repeat:
    update H
    update W
normalize columns of W if needed
visualize W, H
component_masks = component_estimates / total_estimate
components = ISTFT(component_masks * X)
```

必须检查：

- `WH` 是否接近 `V`。
- `W` 是否像频谱模板。
- `H` 是否像时间激活。
- component 是否有可解释性。

### 20. 最终总括

Chapter 8 的核心不是“神奇地把音乐拆开”，而是把音乐知识转成计算约束：

```text
谐波持续 -> 水平结构 -> median filtering -> HPSS
打击短促 -> 垂直结构 -> median filtering -> HPSS
旋律连续 -> F0 trajectory -> salience + DP
复合音有泛音 -> harmonic summation -> F0 candidates
谱图非负叠加 -> W templates + H activations -> NMF
乐谱给出音高时间 -> score-informed constraints -> 更稳定分解
```

学习时要形成三个习惯：

1. 任何分解结果都同时看谱图、听音频、看参数。
2. 任何轨迹估计都同时看局部证据和全局连续性。
3. 任何矩阵分解都要问可解释性、非唯一性和约束来源。

如果能从 HPSS、F0 tracking、NMF 三个角度理解“音乐结构如何帮助音频分解”，就已经抓住了全书最后一章的关键，也能把前面章节的 Fourier、特征、动态规划、检索、评价串成一个完整的 MIR 实践框架。
