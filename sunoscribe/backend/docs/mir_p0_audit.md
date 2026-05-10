# MIR P0 Audit

## Current Pipeline Map

- Upload/API stores project media in `Project.audio_path`; score generation enters through `app.services.score_service.generate_or_regenerate_score`.
- `score_service._run_audio_analysis` materializes the project input and calls `AudioAnalysisService.process_audio`.
- `AudioAnalysisService.process_audio` copies the input into `ProjectWorkspace`, then runs media ingest through `MediaIngestService.ingest`, which writes canonical `preprocess/source.wav`.
- Perception runs required stem separation via `StemService.separate` on canonical audio. Pitch receives `PitchPipelineRequest.lead_audio_path` from `vocals.wav` and uses accompaniment/other/drums/bass stems for rhythm, key, harmony, and bass context where available.
- `MelodyTranscriptionService.transcribe` runs the configured pitch pipeline, persists frame-level `F0Track`, `vocal_activity`, semantic audio, and note candidate payloads. `RhythmQuantizationService` extracts `rhythm_grid` from semantic audio.
- `ScoreBuildService.build` builds `ScoreIR`; `ScoreIRSerializer` creates the compatibility `score_data` view from `ScoreIR`.
- `create_machine_score_revision` validates required vocals and non-fallback `ScoreIR`, creates `ScoreRevision`, registers typed analysis artifacts, and calls `RenderExportService.ensure_core_exports`.
- `RenderExportService` generates MIDI, MusicXML, and score view artifacts from a selected `ScoreRevision` and writes them under revision-scoped export directories.
- Benchmark execution uses `app.scripts.mp4_midi_benchmark`; debug packages are built by `app.modules.benchmark.debug_package.export_benchmark_debug_package`.

## Existing Source-of-Truth Objects

- `Project.audio_path`: source media reference.
- `ProjectWorkspace.canonical_audio_path`: canonical `source.wav` media-ingest artifact.
- `StemService` output: required `vocals.wav` plus accompaniment and optional multi-stems.
- `F0Track`: frame-level pitch data with `time_sec`, `f0_hz`, `midi_float`, `voiced`, and `confidence` when available.
- `note_candidates.json` and `rhythm_grid.json`: typed intermediate analysis artifacts.
- `ScoreIR`: canonical score semantics.
- `ScoreRevision.score_ir`: persisted revision-scoped score source of truth.
- `ScoreRevision.score_data`: compatibility export/view projection that must embed the matching `score_ir` and declare `source_of_truth=score_ir`.
- `Artifact`: revision-scoped export/debug artifact metadata.

## Direct Export Bypass Risks

- Found: `AudioAnalysisService._run_export_stage` previously generated `exports/final_score.mid` from `pitch_result.measures` and copied `raw_pitch.mid` as a fallback.
- Fix: `_run_export_stage` now only writes the legacy benchmark `final_score.mid` from `perception.score_data_dict`, which is derived from `ScoreIR`; it no longer exports from raw pitch measures or copies `raw_pitch.mid`.
- Found: `RenderExportService` generated payloads from `revision.score_data` without verifying its relationship to `revision.score_ir`.
- Fix: revision export now requires `revision.score_data.score_ir` to match `revision.score_ir` and `source_of_truth` to be `score_ir`.
- Compatibility retained: low-level `MidiExporter.export_from_measures` and pitch-pipeline `raw_pitch.mid` may still exist as helpers/diagnostics, but they are not main export sources.

## Required-Stage Fallback Risks

- `AudioAnalysisService._run_perception_stage` already raises `vocal_separation_failed:<reason>` when stem separation throws or when no vocals stem is produced.
- Pitch is not invoked after required separation failure in the covered path.
- `score_service._run_audio_analysis` rejects missing `vocals_path`, fallback `ScoreIR`, and missing lead-vocal notes.
- `create_machine_score_revision` rejects fallback `score_ir`, fallback `score_data`, missing notes, and missing vocals stem.
- No new fallback behavior was introduced.

## Missing Debug Artifacts

- Present/registered by workspace or debug package when available: `vocals.wav`, `produced.mid`, `expected_notes.json`, `predicted_notes.json`, `f0_track.json`, `vocal_activity.json`, `note_candidates.json`, `score_ir.json`, `match_debug.json`, `alignment_debug.json`, `derived_diagnostics.json`, `debug_summary.md`.
- Fixed: `rhythm_grid.json` is now part of benchmark debug package expected files and copy candidates.
- Still optional/missing unless the pipeline produces them: `quantized_notes.json`, `match_debug.json`, `alignment_debug.json`, `timeline_debug.png`, `mdx_diagnostics.json`.
- Missing artifacts are recorded as missing rather than fabricated.

## Proposed Minimal Changes

- Keep existing service boundaries; do not create a parallel pipeline.
- Treat `ScoreRevision.score_ir` as the export source of truth; keep `score_data` only as a derived compatibility projection.
- Keep required vocal separation failure as pipeline failure, not quality failure.
- Preserve frame-level `F0Track`; normalize persisted frames with `time_sec`, `f0_hz`, `midi_float`, `voiced`, and `confidence`/`confidence_status`.
- Keep debug package found/missing reporting explicit and include `rhythm_grid.json`.
- Defer P1 work: formal `PitchContourIR`, `MelodySelector` refinement, DP quantizer, and short-note-loss tuning.
