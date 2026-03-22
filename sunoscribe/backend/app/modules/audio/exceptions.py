class AudioProcessorError(Exception):
    """Base exception for audio processor module."""


class FFmpegNotFoundError(AudioProcessorError):
    """Raised when ffmpeg executable cannot be found."""


class AudioProcessingError(AudioProcessorError):
    """Raised when ffmpeg processing fails."""


class InvalidTimeRangeError(AudioProcessorError):
    """Raised when slice time range is invalid."""
