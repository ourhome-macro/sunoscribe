from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import AudioConfig
from .exceptions import AudioProcessingError, InvalidTimeRangeError
from .utils import build_convert_command, build_slice_command, run_ffmpeg_command

logger = logging.getLogger(__name__)


class AudioProcessor:
	"""Core audio preprocessing service."""

	def __init__(self, default_config: Optional[AudioConfig] = None) -> None:
		self.default_config = default_config or AudioConfig()

	def convert(
		self,
		input_path: str,
		output_path: str,
		options: Optional[AudioConfig] = None,
	) -> str:
		"""Convert arbitrary media file to standardized audio."""
		config = options or self.default_config
		config.validate()

		src = Path(input_path)
		if not src.exists() or not src.is_file():
			raise AudioProcessingError(f"Input file does not exist: {src}")

		dst = config.normalize_output_path(output_path)
		dst.parent.mkdir(parents=True, exist_ok=True)

		logger.info("Audio conversion started: input=%s output=%s", src, dst)
		command = build_convert_command(src, dst, config)
		run_ffmpeg_command(command, timeout_sec=config.timeout_sec)
		logger.info("Audio conversion completed: %s", dst)

		return str(dst)

	def slice(
		self,
		input_path: str,
		output_path: str,
		start_sec: float,
		end_sec: float,
		options: Optional[AudioConfig] = None,
		fast_seek: bool = True,
	) -> str:
		"""Slice audio by [start_sec, end_sec]."""
		if start_sec < 0:
			raise InvalidTimeRangeError("start_sec must be >= 0")
		if end_sec <= start_sec:
			raise InvalidTimeRangeError("end_sec must be greater than start_sec")

		config = options or self.default_config
		config.validate()

		src = Path(input_path)
		if not src.exists() or not src.is_file():
			raise AudioProcessingError(f"Input file does not exist: {src}")

		dst = config.normalize_output_path(output_path)
		dst.parent.mkdir(parents=True, exist_ok=True)

		duration = end_sec - start_sec

		logger.info(
			"Audio slicing started: input=%s output=%s start=%.3f end=%.3f fast_seek=%s",
			src,
			dst,
			start_sec,
			end_sec,
			fast_seek,
		)

		command = build_slice_command(
			input_path=src,
			output_path=dst,
			start_sec=start_sec,
			duration_sec=duration,
			config=config,
			fast_seek=fast_seek,
		)
		run_ffmpeg_command(command, timeout_sec=config.timeout_sec)

		logger.info("Audio slicing completed: %s", dst)
		return str(dst)
