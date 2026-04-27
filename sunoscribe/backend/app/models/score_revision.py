import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ScoreRevisionType, ScoreType


class ScoreRevision(Base):
    __tablename__ = "score_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("score_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_type: Mapped[str] = mapped_column(
        String(20),
        default=ScoreRevisionType.MACHINE.value,
        index=True,
        nullable=False,
    )
    score_type: Mapped[str] = mapped_column(String(20), default=ScoreType.JIANPU.value, nullable=False)
    key: Mapped[str] = mapped_column(String(50), default="C Major", nullable=False)
    vocal_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommended_voice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emotion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score_ir: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    score_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    patch_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    revision_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    score = relationship("Score", back_populates="revisions", foreign_keys=[score_id])
    project = relationship("Project")
    parent_revision = relationship(
        "ScoreRevision",
        remote_side=[id],
        back_populates="child_revisions",
        foreign_keys=[parent_revision_id],
    )
    child_revisions = relationship("ScoreRevision", back_populates="parent_revision")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    artifacts = relationship("Artifact", back_populates="score_revision")
