"""add artifacts and score revisions

Revision ID: 20260427_0003
Revises: 20260427_0002
Create Date: 2026-04-27 01:00:00
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260427_0003"
down_revision = "20260427_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "score_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_type", sa.String(length=20), nullable=False),
        sa.Column("score_type", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("vocal_range", sa.String(length=100), nullable=True),
        sa.Column("recommended_voice", sa.String(length=100), nullable=True),
        sa.Column("emotion", sa.String(length=100), nullable=True),
        sa.Column("score_ir", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("patch_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["score_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("score_id", "revision_number", name="uq_score_revisions_score_id_revision_number"),
    )
    op.create_index(op.f("ix_score_revisions_created_by_user_id"), "score_revisions", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_score_revisions_parent_revision_id"), "score_revisions", ["parent_revision_id"], unique=False)
    op.create_index(op.f("ix_score_revisions_project_id"), "score_revisions", ["project_id"], unique=False)
    op.create_index(op.f("ix_score_revisions_revision_type"), "score_revisions", ["revision_type"], unique=False)
    op.create_index(op.f("ix_score_revisions_score_id"), "score_revisions", ["score_id"], unique=False)

    op.add_column("scores", sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_scores_current_revision_id"), "scores", ["current_revision_id"], unique=False)
    op.create_foreign_key(
        "fk_scores_current_revision_id_score_revisions",
        "scores",
        "score_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("artifact_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_revision_id"], ["score_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_artifact_type"), "artifacts", ["artifact_type"], unique=False)
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"], unique=False)
    op.create_index(op.f("ix_artifacts_score_id"), "artifacts", ["score_id"], unique=False)
    op.create_index(op.f("ix_artifacts_score_revision_id"), "artifacts", ["score_revision_id"], unique=False)
    op.create_index(op.f("ix_artifacts_status"), "artifacts", ["status"], unique=False)
    op.create_index(op.f("ix_artifacts_task_id"), "artifacts", ["task_id"], unique=False)

    _backfill_initial_score_revisions()


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_task_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_status"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_score_revision_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_score_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_project_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_artifact_type"), table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_constraint("fk_scores_current_revision_id_score_revisions", "scores", type_="foreignkey")
    op.drop_index(op.f("ix_scores_current_revision_id"), table_name="scores")
    op.drop_column("scores", "current_revision_id")

    op.drop_index(op.f("ix_score_revisions_score_id"), table_name="score_revisions")
    op.drop_index(op.f("ix_score_revisions_revision_type"), table_name="score_revisions")
    op.drop_index(op.f("ix_score_revisions_project_id"), table_name="score_revisions")
    op.drop_index(op.f("ix_score_revisions_parent_revision_id"), table_name="score_revisions")
    op.drop_index(op.f("ix_score_revisions_created_by_user_id"), table_name="score_revisions")
    op.drop_table("score_revisions")


def _backfill_initial_score_revisions() -> None:
    bind = op.get_bind()

    scores = sa.table(
        "scores",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("project_id", postgresql.UUID(as_uuid=True)),
        sa.column("score_type", sa.String(length=20)),
        sa.column("key", sa.String(length=50)),
        sa.column("vocal_range", sa.String(length=100)),
        sa.column("recommended_voice", sa.String(length=100)),
        sa.column("emotion", sa.String(length=100)),
        sa.column("score_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("current_revision_id", postgresql.UUID(as_uuid=True)),
    )
    score_revisions = sa.table(
        "score_revisions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("project_id", postgresql.UUID(as_uuid=True)),
        sa.column("score_id", postgresql.UUID(as_uuid=True)),
        sa.column("parent_revision_id", postgresql.UUID(as_uuid=True)),
        sa.column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.column("revision_number", sa.Integer()),
        sa.column("revision_type", sa.String(length=20)),
        sa.column("score_type", sa.String(length=20)),
        sa.column("key", sa.String(length=50)),
        sa.column("vocal_range", sa.String(length=100)),
        sa.column("recommended_voice", sa.String(length=100)),
        sa.column("emotion", sa.String(length=100)),
        sa.column("score_ir", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("score_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("patch_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("revision_metadata", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    existing_scores = bind.execute(
        sa.select(
            scores.c.id,
            scores.c.project_id,
            scores.c.score_type,
            scores.c.key,
            scores.c.vocal_range,
            scores.c.recommended_voice,
            scores.c.emotion,
            scores.c.score_data,
            scores.c.created_at,
            scores.c.updated_at,
        )
    ).mappings()

    revision_rows: list[dict[str, object]] = []
    revision_ids_by_score_id: dict[uuid.UUID, uuid.UUID] = {}
    for row in existing_scores:
        revision_id = uuid.uuid4()
        revision_rows.append(
            {
                "id": revision_id,
                "project_id": row["project_id"],
                "score_id": row["id"],
                "parent_revision_id": None,
                "created_by_user_id": None,
                "revision_number": 1,
                "revision_type": "machine",
                "score_type": row["score_type"],
                "key": row["key"],
                "vocal_range": row["vocal_range"],
                "recommended_voice": row["recommended_voice"],
                "emotion": row["emotion"],
                "score_ir": _extract_score_ir(row["score_data"]),
                "score_data": row["score_data"],
                "patch_data": {},
                "revision_metadata": {},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
        revision_ids_by_score_id[row["id"]] = revision_id

    if not revision_rows:
        return

    bind.execute(sa.insert(score_revisions), revision_rows)

    for score_id, revision_id in revision_ids_by_score_id.items():
        bind.execute(
            sa.update(scores)
            .where(scores.c.id == score_id)
            .values(current_revision_id=revision_id)
        )


def _extract_score_ir(score_data: object) -> dict[str, object]:
    if isinstance(score_data, dict):
        nested = score_data.get("score_ir")
        if isinstance(nested, dict):
            return nested
    return {}
