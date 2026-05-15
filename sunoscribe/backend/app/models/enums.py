from enum import Enum


class ScoreType(str, Enum):
    JIANPU = "jianpu"
    STAFF = "staff"


class SourceType(str, Enum):
    UPLOAD = "upload"
    BILIBILI = "bilibili"


class ProjectStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    TRANSCRIPTION = "transcription"
    SCORE_GENERATION = "score_generation"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class ScoreRevisionType(str, Enum):
    MACHINE = "machine"
    USER = "user"


class ArtifactType(str, Enum):
    SOURCE_MEDIA = "source_media"
    CANONICAL_AUDIO = "canonical_audio"
    VOCALS_STEM = "vocals_stem"
    ACCOMPANIMENT_STEM = "accompaniment_stem"
    F0_TRACK = "f0_track"
    PITCH_ANALYSIS = "pitch_analysis"
    NOTE_CANDIDATES = "note_candidates"
    RHYTHM_GRID = "rhythm_grid"
    ANALYSIS_IR = "analysis_ir"
    SCORE_IR = "score_ir"
    LYRICS_SEGMENTS = "lyrics_segments"
    ALIGNMENT = "alignment"
    MIDI = "midi"
    MUSICXML = "musicxml"
    SCORE_VIEW = "score_view"
    AUDIO_ANALYSIS_REPORT = "audio_analysis_report"
    PDF = "pdf"
    DEBUG_IMAGE = "debug_image"
    DEBUG_JSON = "debug_json"
    CORRECTED_F0_TRACK = "corrected_f0_track"
    RVC_VOCAL = "rvc_vocal"
    RVC_MIX = "rvc_mix"
    OTHER = "other"


class ArtifactStatus(str, Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class ArtifactStorageBackend(str, Enum):
    WORKSPACE = "workspace"
    MINIO = "minio"
    EXTERNAL = "external"
