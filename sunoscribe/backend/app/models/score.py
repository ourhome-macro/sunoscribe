import uuid

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ScoreType


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    score_type: Mapped[str] = mapped_column(String(20), default=ScoreType.JIANPU.value, nullable=False)
    key: Mapped[str] = mapped_column(String(50), default="C Major", nullable=False)
    vocal_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommended_voice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emotion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="score")
