# MP4->MIDI Benchmark Summary

- Created at: `2026-05-06T18:02:34.492323+00:00`
- Samples run: `1`
- Success: `1`
- Failed: `0`
- Mean note F1: `0.03656307129798903`
- Mean pitch accuracy: `0.1`
- Readiness: `ok`

| Sample | Status | Note F1 | Pitch Acc | Onset MAE ms | Error |
| --- | --- | ---: | ---: | ---: | --- |
| mojito | success | 0.0366 | 0.1000 | 70.9091 |  |

## Dataset Completeness

- MP4 files: `22`
- MIDI files: `23`
- Paired files: `19`
- Enabled samples: `19`
- MP4 only: `2`
- MIDI only: `4`

## MVP Readiness

- `python`: `ok` — Python 3.10 is recommended for backend runtime.
- `ffmpeg`: `ok` — ffmpeg is available.
- `pretty_midi`: `ok` — pretty_midi is importable.
- `mido`: `ok` — mido is importable.
- `librosa`: `ok` — librosa is importable.
- `soundfile`: `ok` — soundfile is importable.
- `rmvpe_pitch`: `ok` — RMVPE production runtime is ready.
- `vocal_separator`: `ok` — MDX-Net vocal separator package and cached model are available.
