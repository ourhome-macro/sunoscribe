from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_SAMPLE_RATE: int = 16_000
DEFAULT_OUTPUT_FORMAT: str = "wav"
FFMPEG_PATH: str = "ffmpeg"


@dataclass(slots=True)
class AudioConfig:
	"""Audio processing configuration."""

	sample_rate: int = DEFAULT_SAMPLE_RATE
	output_format: str = DEFAULT_OUTPUT_FORMAT
	ffmpeg_path: str = FFMPEG_PATH
	channels: int = 1
	overwrite: bool = True
	timeout_sec: Optional[float] = 600.0
	extra_args: list[str] = field(default_factory=list)

	def normalize_output_path(self, output_path: str | Path) -> Path:
		path = Path(output_path)
		if path.suffix:
			return path
		return path.with_suffix(f".{self.output_format}")

	def validate(self) -> None:
		if self.sample_rate <= 0:
			raise ValueError("sample_rate must be > 0")
		if self.channels <= 0:
			raise ValueError("channels must be > 0")
		if not self.output_format:
			raise ValueError("output_format must not be empty")
