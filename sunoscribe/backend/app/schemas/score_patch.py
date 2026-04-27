from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ScorePatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _BaseScorePatchOperation(_ScorePatchModel):
    type: str | None = None
    reason: str | None = Field(default=None, max_length=500)


class ReplaceNotePitchOperation(_BaseScorePatchOperation):
    op: Literal["replace_note_pitch"]
    note_id: str = Field(min_length=1, max_length=128)
    pitch_midi: int = Field(ge=0, le=127)


class AdjustNoteTimingOperation(_BaseScorePatchOperation):
    op: Literal["adjust_note_timing"]
    note_id: str = Field(min_length=1, max_length=128)
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _validate_time_range(self) -> "AdjustNoteTimingOperation":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self


class AdjustNoteDurationOperation(_BaseScorePatchOperation):
    op: Literal["adjust_note_duration"]
    note_id: str = Field(min_length=1, max_length=128)
    duration_sec: float | None = Field(default=None, gt=0.0)
    duration_beats: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _validate_duration_payload(self) -> "AdjustNoteDurationOperation":
        if self.duration_sec is None and self.duration_beats is None:
            raise ValueError("either duration_sec or duration_beats must be provided")
        return self


class DeleteNoteOperation(_BaseScorePatchOperation):
    op: Literal["delete_note"]
    note_id: str = Field(min_length=1, max_length=128)


class MergeNotesOperation(_BaseScorePatchOperation):
    op: Literal["merge_notes"]
    note_ids: list[str] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def _validate_unique_note_ids(self) -> "MergeNotesOperation":
        unique_ids = {note_id.strip() for note_id in self.note_ids if str(note_id).strip()}
        if len(unique_ids) != len(self.note_ids):
            raise ValueError("note_ids must be unique and non-empty")
        return self


class BindLyricTokenOperation(_BaseScorePatchOperation):
    op: Literal["bind_lyric_token"]
    note_id: str = Field(min_length=1, max_length=128)
    lyric_token_id: str = Field(min_length=1, max_length=128)


ScorePatchOperation = Annotated[
    Union[
        ReplaceNotePitchOperation,
        AdjustNoteTimingOperation,
        AdjustNoteDurationOperation,
        DeleteNoteOperation,
        MergeNotesOperation,
        BindLyricTokenOperation,
    ],
    Field(discriminator="op"),
]


class ScorePatch(_ScorePatchModel):
    operations: list[ScorePatchOperation] = Field(min_length=1, max_length=128)
    summary: str | None = Field(default=None, max_length=500)
