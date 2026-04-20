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
