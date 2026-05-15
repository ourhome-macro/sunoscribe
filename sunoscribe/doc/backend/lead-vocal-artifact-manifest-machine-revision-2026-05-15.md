# Lead Vocal MVP Artifact Manifest And Machine Revision State

Date: 2026-05-15

## Purpose

The lead-vocal MVP now records a minimal file-backed product state for pipeline-only runs before database task integration is mandatory. The state is intentionally narrow: it binds one immutable machine score revision to its typed MIR artifacts and revision-scoped exports.

## Runtime Contract

For each `AudioAnalysisService.process_audio` run:

1. Existing typed stage files are written under the project workspace.
2. A new machine revision directory is created under `projects/<project_id>/revisions/<revision_id>/`.
3. `score_ir.json` and `score_data.json` are copied into that immutable revision directory.
4. `artifact_manifest.json` records required lead-vocal artifacts and their `score_revision_id`.
5. MIDI and MusicXML are generated from that revision's `score_data`, not from raw pitch MIDI or an arbitrary in-memory intermediate.

## Required Lead-Vocal Artifacts

The MVP manifest requires these typed outputs:

- `f0_track`
- `pitch_contours`
- `note_candidates`
- `selected_melody`
- `rhythm_grid`
- `quantized_notes`
- `score_ir`
- `score_data`
- `midi`
- `musicxml`

Source media, canonical audio, and vocal stem paths are also attached where available. Diagnostic artifacts such as vocal activity and semantic audio remain optional.

## Immutability And Reruns

Machine revision IDs are monotonic per project workspace and include a random suffix:

```text
machine-0001-<suffix>
machine-0002-<suffix>
```

A rerun creates a new machine revision directory and manifest. It does not overwrite an existing machine revision. Legacy stage files under `pitch/`, `score/`, and `exports/` may still represent the latest pipeline scratch state, but product exports for MVP consumption are revision-scoped under `revisions/<revision_id>/exports/`.

## Boundary

This change does not modify MIR algorithms and does not touch `ContourToCandidateBridge`. It is a product-state wiring change only. The existing SQL `Artifact` and `ScoreRevision` models remain the target durable persistence layer; this file-backed state is the minimum manifest bridge for the lead-vocal MVP orchestration path.
