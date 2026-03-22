from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import AudioConfig
from .exceptions import AudioProcessingError, FFmpegNotFoundError

logger = logging.getLogger(__name__)


def ensure_ffmpeg_available(ffmpeg_path: str) -> str:
	"""Ensure ffmpeg executable exists and is runnable."""
	candidate = Path(ffmpeg_path)
	if candidate.exists() and candidate.is_file():
		return str(candidate)

	resolved = shutil.which(ffmpeg_path)
	if resolved:
		return resolved

	raise FFmpegNotFoundError(
		f"FFmpeg executable not found: '{ffmpeg_path}'. "
		"Please install FFmpeg or set an absolute ffmpeg_path."
	)


def _creation_flags_no_window() -> int:
	if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
		return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
	return 0


def run_ffmpeg_command(command: list[str], timeout_sec: Optional[float] = None) -> None:
	"""Run ffmpeg command safely and raise custom exception on failures."""
	logger.debug("Executing FFmpeg command: %s", command)

	try:
		completed = subprocess.run(
			command,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			encoding="utf-8",
			errors="replace",
			creationflags=_creation_flags_no_window(),
			check=False,
			timeout=timeout_sec,
		)
	except FileNotFoundError as exc:
		raise FFmpegNotFoundError(
			f"FFmpeg executable not found when running command: {command[0]}"
		) from exc
	except subprocess.TimeoutExpired as exc:
		raise AudioProcessingError(
			f"FFmpeg execution timed out after {timeout_sec} seconds."
		) from exc
	except Exception as exc:
		raise AudioProcessingError(f"Unexpected error while running FFmpeg: {exc}") from exc

	if completed.returncode != 0:
		stderr = (completed.stderr or "").strip()
		short_err = _extract_ffmpeg_error(stderr)
		raise AudioProcessingError(
			f"FFmpeg failed with return code {completed.returncode}: {short_err}"
		)


def _extract_ffmpeg_error(stderr_text: str) -> str:
	if not stderr_text:
		return "Unknown FFmpeg error."

	lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
	if not lines:
		return "Unknown FFmpeg error."

	keywords = ("error", "invalid", "failed", "unable", "not found", "cannot")
	for line in reversed(lines):
		low = line.lower()
		if any(keyword in low for keyword in keywords):
			return line

	return lines[-1]


def build_convert_command(
	input_path: Path,
	output_path: Path,
	config: AudioConfig,
) -> list[str]:
	"""Build ffmpeg command for audio extraction + resample + transcode."""
	ffmpeg_exec = ensure_ffmpeg_available(config.ffmpeg_path)

	command: list[str] = [ffmpeg_exec]
	if config.overwrite:
		command.append("-y")

	command.extend(
		[
			"-i",
			str(input_path),
			"-vn",
			"-ar",
			str(config.sample_rate),
			"-ac",
			str(config.channels),
		]
	)

	if config.extra_args:
		command.extend(config.extra_args)

	command.append(str(output_path))
	return command


def build_slice_command(
	input_path: Path,
	output_path: Path,
	start_sec: float,
	duration_sec: float,
	config: AudioConfig,
	fast_seek: bool = True,
) -> list[str]:
	"""Build ffmpeg command for slicing by timestamp."""
	ffmpeg_exec = ensure_ffmpeg_available(config.ffmpeg_path)

	command: list[str] = [ffmpeg_exec]
	if config.overwrite:
		command.append("-y")

	if fast_seek:
		command.extend(["-ss", f"{start_sec:.3f}", "-i", str(input_path)])
	else:
		command.extend(["-i", str(input_path), "-ss", f"{start_sec:.3f}"])

	command.extend(
		[
			"-t",
			f"{duration_sec:.3f}",
			"-vn",
			"-ar",
			str(config.sample_rate),
			"-ac",
			str(config.channels),
		]
	)

	if config.extra_args:
		command.extend(config.extra_args)

	command.append(str(output_path))
	return command
