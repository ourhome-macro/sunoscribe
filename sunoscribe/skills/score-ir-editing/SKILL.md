---
name: score-ir-editing
description: Controlled ScoreIR editing and revision workflow for SunoScribe. Use when implementing or reviewing agent-assisted score edits, frontend note editing, ScorePatch schemas, patch validators, machine/user ScoreRevision behavior, lyrics-to-note edits, export regeneration, or any code that mutates score data.
---

# ScoreIR Editing

Use this skill when a change can alter the musical score after transcription.

## Core Rule

Never let an agent or UI overwrite the machine transcription directly. Every edit must become a validated patch that creates a new revision.

```text
ScoreRevision + ScorePatch -> validate -> new ScoreRevision -> regenerate artifacts
```

## Revision Model

Use separate revision types:

- `machine`: produced by the deterministic MIR pipeline.
- `user`: produced by a human or accepted agent edit.

Keep `parent_revision_id` so the project can compare, revert, and audit changes.

## Patch Shape

Prefer small operations over whole-score replacement. Valid operations should be specific and auditable, for example:

```json
{
  "operations": [
    {
      "op": "replace_note_pitch",
      "note_id": "n000123",
      "pitch_midi": 64,
      "reason": "likely octave correction"
    }
  ]
}
```

Useful first-version operations:

- `replace_note_pitch`
- `adjust_note_timing`
- `adjust_note_duration`
- `delete_note`
- `merge_notes`
- `split_note`
- `bind_lyric_token`
- `set_measure_issue_status`

## Validation Rules

Reject patches that:

- Reference missing note IDs or lyric token IDs.
- Produce invalid MIDI pitch values.
- Create negative or zero durations where a note is expected.
- Move notes outside project duration.
- Break measure ordering.
- Make MusicXML export impossible.
- Replace the full score when a narrow patch can express the change.

## Agent Behavior

Agents may propose patches and explain the musical evidence. Agents must not:

- Write directly to `scores.score_data`.
- Edit database rows directly.
- Generate final MIDI or MusicXML by hand.
- Bypass patch validation.
- Hide uncertainty when evidence is weak.

## Export Rule

After a patch is accepted:

1. Create a new `ScoreRevision`.
2. Regenerate MIDI and MusicXML from that revision.
3. Register regenerated files as artifacts.
4. Keep old artifacts tied to their original revision.

## Review Checklist

Before accepting a score-editing change, confirm:

- Machine and user revisions remain separate.
- Patch operations are narrow and typed.
- Validators run before mutation.
- Exports are revision-scoped.
- The frontend can display which revision is active.
