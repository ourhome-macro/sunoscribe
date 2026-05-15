# Required pitch/candidate error semantics

## Scope

- `backend/app/modules/pitch/pipeline.py`
- `backend/app/services/melody_transcription_service.py`
- `backend/tests/test_pitch_pipeline.py`
- `backend/tests/test_audio_analysis_service.py`

## Changes

- Required `melody` detection no longer swallows detector exceptions into empty candidate lists.
- Raised errors now include `role`, `backend`, `path`, and detector `reason`.
- Optional support detection (`basic_pitch_support`, harmony/bass support path) still degrades as warning + empty list.
- `MelodyTranscriptionService` now treats missing final lead-vocal notes as a hard failure based on selected lead output, not raw candidate presence.
- No-lead-notes failures now carry compact diagnostics, including candidate counts and pipeline warnings when available.

## Intended behavior

- Required production stages fail explicitly and traceably.
- Optional support stages remain non-fatal.
- A successful-but-empty lead pipeline still fails with a precise `no lead-vocal notes` error instead of masking upstream semantics.
