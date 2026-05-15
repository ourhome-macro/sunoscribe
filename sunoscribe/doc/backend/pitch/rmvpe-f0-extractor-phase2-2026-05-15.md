# RMVPE F0 Extractor Phase 2 Migration Note (2026-05-15)

## Change

Added `RMVPEF0Extractor.extract()` as the first explicit production entry point for the `vocals.wav -> F0Track` stage.

The extractor:

- Forces `pitch_backend="rmvpe"` for the extraction call.
- Disables backend fallbacks even if a permissive config is passed in.
- Reuses existing RMVPE model loading, audio loading, frame coercion, voiced/unvoiced masking, and vocal-activity artifact code.
- Returns typed `F0Track` data only.
- Does not call `_frames_to_notes()` and does not perform note segmentation.

## Failure Semantics

`RMVPEF0Extractor` treats RMVPE as a required production stage:

- Missing audio raises `PitchDetectionFailedError`.
- Missing RMVPE runtime/model raises `PitchModelUnavailableError`.
- Empty audio raises `PitchDetectionFailedError` with `rmvpe_audio_empty`.
- Empty RMVPE frame output raises `PitchDetectionFailedError` with `rmvpe_returned_no_frames`.
- CREPE and basic-pitch are never called as fallbacks from this extractor.

This follows the no-silent-fallback policy: required-stage failure is preferable to a fake or downgraded transcription.

## Migration Status

This is a small, reversible Phase 2 slice. Existing `PitchDetector.detect()` behavior is left intact so the current pipeline can continue running while downstream typed stages are tightened.

Next migration step:

```text
PitchPipeline lead vocal path
  -> RMVPEF0Extractor.extract()
  -> PitchContourBuilder.build(F0Track)
  -> NoteCandidateBuilder.build(F0Track + PitchContourSet)
```

`PitchDetector._frames_to_notes()` should remain legacy compatibility until `NoteCandidateSet -> MelodySelection -> QuantizedNoteSet -> ScoreRevision` becomes the only production path.

## Contract Tests

Added focused tests for:

- Extractor returns authoritative `F0Track` metadata and frame data.
- Extractor does not call note segmentation.
- RMVPE unavailability fails explicitly without invoking CREPE/basic-pitch.
- Empty RMVPE frame output fails explicitly and stores diagnostic extraction artifacts.
