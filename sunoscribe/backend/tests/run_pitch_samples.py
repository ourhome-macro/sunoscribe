from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.pitch.pipeline import PitchPipeline
from app.modules.pitch.beat_tracker import BeatTracker
from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.exceptions import PitchModelUnavailableError
from app.modules.pitch.key_analyzer import KeyAnalyzer

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
VOCAL_KEYS = ("vocal", "voice", "人声", "纯人声", "acapella")
INST_KEYS = ("inst", "accompaniment", "伴奏", "纯伴奏", "music")


def _find_files(samples_dir: Path) -> tuple[Path | None, Path | None]:
    audio_files = [p for p in samples_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

    vocal = None
    inst = None

    for p in audio_files:
        lower = p.name.lower()
        if vocal is None and any(k in lower for k in VOCAL_KEYS):
            vocal = p
        if inst is None and any(k in lower for k in INST_KEYS):
            inst = p

    # fallback: 如果未命中关键字，取前两个音频
    if vocal is None and len(audio_files) >= 1:
        vocal = audio_files[0]
    if inst is None and len(audio_files) >= 2:
        inst = audio_files[1]

    return vocal, inst


def _run_case(label: str, audio_path: Path, pipeline: PitchPipeline) -> None:
    print(f"\n===== {label} =====")
    print(f"file: {audio_path}")
    try:
        result = pipeline.run(str(audio_path))
        payload = result.to_dict()

        # 控制终端输出大小：展示核心摘要 + 前10个音符
        summary = {
            "mode": "full_pipeline",
            "version": payload["version"],
            "meta": payload["meta"],
            "analysis_info": payload.get("analysis_info", {}),
            "raw_notes_count": len(payload.get("raw_notes", [])),
            "raw_notes_preview": payload.get("raw_notes", [])[:10],
            "warnings": payload.get("warnings", []),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except PitchModelUnavailableError as exc:
        # 降级：在无法加载 basic-pitch 时，仍输出 BPM + 调式，保证两类样本都有终端结果。
        cfg = PitchDetectionConfig()
        beat_result = BeatTracker(cfg).track(str(audio_path))
        key_result = KeyAnalyzer(cfg).analyze(str(audio_path))
        summary = {
            "mode": "fallback_without_basic_pitch",
            "error": str(exc),
            "meta": {
                "bpm": beat_result.bpm,
                "bpm_confidence": beat_result.confidence,
                "key": key_result.key,
                "key_confidence": key_result.confidence,
            },
            "raw_notes_count": 0,
            "raw_notes_preview": [],
            "warnings": ["basic-pitch unavailable, raw note detection skipped"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    repo_backend = BACKEND_ROOT
    samples_dir = repo_backend / "app" / "modules" / "pitch" / "samples"

    if not samples_dir.exists():
        print(f"samples 目录不存在: {samples_dir}")
        return 1

    vocal_file, inst_file = _find_files(samples_dir)

    if vocal_file is None or inst_file is None:
        print("未找到可测试的纯人声/纯伴奏文件。")
        print(f"请将音频文件放入: {samples_dir}")
        print("建议命名示例: pure_vocal.wav / pure_accompaniment.wav")
        return 1

    pipeline = PitchPipeline()

    failed = False
    for label, path in (("纯人声测试结果", vocal_file), ("纯伴奏测试结果", inst_file)):
        try:
            _run_case(label, path, pipeline)
        except Exception as exc:
            failed = True
            print(f"\n===== {label} =====")
            print(f"file: {path}")
            print("执行失败:", repr(exc))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
