class PitchDetectionError(Exception):
    """音高检测基础异常。"""


class AudioTooLongError(PitchDetectionError):
    """音频超过最大长度。"""


class PitchModelUnavailableError(PitchDetectionError):
    """basic-pitch 不可用或加载失败。"""


class PitchDetectionFailedError(PitchDetectionError):
    """音高检测失败。"""


class NoBeatsDetectedError(PitchDetectionError):
    """无法检测到 BPM。"""


class KeyAnalysisLowConfidenceError(PitchDetectionError):
    """调式分析置信度过低。"""


class DownbeatTrackingError(PitchDetectionError):
    """Downbeat 检测失败。"""


class MidiExportError(PitchDetectionError):
    """MIDI 导出失败。"""
