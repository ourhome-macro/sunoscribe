from __future__ import annotations

from pathlib import Path


def get_audio_duration(audio_path: str | Path) -> float:
    path = str(audio_path)

    try:
        import soundfile as sf

        return float(sf.info(path).duration)
    except Exception:
        pass

    try:
        import audioread

        with audioread.audio_open(path) as handle:
            return float(handle.duration)
    except Exception:
        pass

    try:
        import torchaudio

        info = torchaudio.info(path)
        sample_rate = float(getattr(info, "sample_rate", 0) or 0)
        num_frames = float(getattr(info, "num_frames", 0) or 0)
        if sample_rate > 0 and num_frames >= 0:
            return num_frames / sample_rate
    except Exception:
        pass

    raise RuntimeError(f"failed to read audio duration for {path}")
