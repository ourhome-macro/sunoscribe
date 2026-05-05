from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MediaIngestResult:
    source_media_path: Path
    canonical_audio_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class MediaIngestService:
    """Convert uploaded audio/video media into the canonical audio artifact."""

    def __init__(self, audio_processor: Any) -> None:
        self.audio_processor = audio_processor

    def ingest(self, source_media_path: str | Path, canonical_audio_path: str | Path) -> MediaIngestResult:
        if self.audio_processor is None:
            raise RuntimeError("MediaIngestService requires an audio processor")

        source_path = Path(source_media_path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"source media file not found: {source_path}")

        canonical_path = Path(canonical_audio_path)
        converted_path = Path(self.audio_processor.convert(str(source_path), str(canonical_path)))
        if not converted_path.exists() or not converted_path.is_file():
            raise RuntimeError("media ingest did not produce canonical audio")

        return MediaIngestResult(
            source_media_path=source_path,
            canonical_audio_path=converted_path,
            metadata={
                "stage": "media_ingest",
                "source_media_path": str(source_path),
                "canonical_audio_path": str(converted_path),
                "canonical_mime_type": "audio/wav",
            },
        )
