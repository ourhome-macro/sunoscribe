import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'

export function DiagnosticsPage() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101'
  const { data } = useQuery({ queryKey: ['diagnostics', projectId], queryFn: () => apiClient.getDiagnostics(projectId) })

  const rhythmLooksStable = !data?.quantization.fallback_used && (data?.quantization.p95_error_beats ?? 1) < 0.25
  const shortNoteRisk = (data?.short_notes.too_short_count ?? 0) + (data?.short_notes.suspected_vibrato_count ?? 0)
  const continuity = data?.continuity
  const referenceAlignment = data?.reference_alignment
  const gapRisk = (continuity?.gap50_ratio ?? 0) > 0.8 || (continuity?.big_gap_count ?? 0) > 40
  const localJumpRisk = (continuity?.local_large_jump_ratio ?? 0) > 0.08
  const referenceSuspect = Boolean(referenceAlignment?.reference_suspect)

  return (
    <div>
      <PageHeader title="Diagnostics" description="Read musical conclusions first, then inspect engineering details for troubleshooting." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Musical summary</CardTitle>
            <CardDescription>Use these signals to decide whether the score is worth manual correction.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Finding title="Rhythm alignment" ok={rhythmLooksStable} text={rhythmLooksStable ? 'Most notes align with the rhythm grid.' : 'Rhythm alignment is unstable; measures or beats may need review.'} />
            <Finding title="Short-note risk" ok={shortNoteRisk < 8} text={shortNoteRisk < 8 ? 'Short notes and vocal-style risks are under control.' : 'Short-note or vibrato risk is high; inspect phrase by phrase.'} />
            <Finding title="Fragmented playback" ok={!gapRisk} text={gapRisk ? 'Many inter-note gaps may make MIDI playback sound broken; judge with phrase context and original vocal audio.' : 'Inter-note gap risk is under control.'} />
            <Finding title="Phrase-local jumps" ok={!localJumpRisk} text={localJumpRisk ? 'Large jumps inside phrases are high; inspect pitch or octave jumps first.' : 'Most large jumps are cross-phrase, so avoid aggressive smoothing.'} />
            <Finding title="Reference MIDI" ok={!referenceSuspect} text={referenceSuspect ? 'Reference MIDI may have time-origin, octave, or track-selection issues. This is diagnostic only and does not mutate the score.' : 'Reference MIDI is not currently marked suspect.'} />
            <Finding title="Lead-vocal lineage" ok={!data?.stage_failure_reason} text={data?.stage_failure_reason ? 'A required stage failed; do not treat this as a complete result.' : 'No required-stage failure is recorded.'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Derived diagnostics summary</CardTitle>
            <CardDescription>
              The frontend reads summaries and availability only; it never requests a full <GlossaryTerm term="F0Track" />.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">{data?.derived_diagnostics.summary}</p>
            <Metric label="Score revision" value={data?.derived_diagnostics.score_revision_id ?? '?'} />
            <Metric label="F0 summary available" value={data?.derived_diagnostics.f0_track_available ? 'yes' : 'no'} />
            <Metric label="Note candidates available" value={data?.derived_diagnostics.note_candidates_available ? 'yes' : 'no'} />
            <Metric label="Rhythm grid available" value={data?.derived_diagnostics.rhythm_grid_available ? 'yes' : 'no'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Technical: quantization</CardTitle>
            <CardDescription>Backend diagnostic fields for engineering investigation.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="Fallback used" value={data?.quantization.fallback_used ? 'yes' : 'no'} />
            <Metric label="Fallback reason" value={data?.quantization.fallback_reason ?? '?'} />
            <Metric label="Mean error (beats)" value={data?.quantization.mean_error_beats ?? '?'} />
            <Metric label="P95 error (beats)" value={data?.quantization.p95_error_beats ?? '?'} />
            <Metric label="Max error (beats)" value={data?.quantization.max_error_beats ?? '?'} />
            <Metric label="Fragmentation risk" value={data?.quantization.fragmentation ?? '?'} />
            <Metric label="Overmerge risk" value={data?.quantization.overmerge ?? '?'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Technical: short notes and vocal style</CardTitle>
            <CardDescription>Short notes, weak voicing, vibrato, and glides all affect transcription quality.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="Too-short notes" value={data?.short_notes.too_short_count ?? '?'} />
            <Metric label="Low voiced ratio" value={data?.short_notes.low_voiced_ratio_count ?? '?'} />
            <Metric label="Suspected vibrato" value={data?.short_notes.suspected_vibrato_count ?? '?'} />
            <Metric label="Suspected glide" value={data?.short_notes.suspected_glide_count ?? '?'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Technical: gaps and jumps</CardTitle>
            <CardDescription>These values come from Lead Vocal MIDI diagnostics and are used only for listening-risk evaluation.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label=">50ms gap ratio" value={formatPercent(continuity?.gap50_ratio)} />
            <Metric label=">500ms big gaps" value={continuity?.big_gap_count ?? '?'} />
            <Metric label="Short-note ratio" value={formatPercent(continuity?.short_note_ratio)} />
            <Metric label="Large-jump ratio" value={formatPercent(continuity?.large_jump_ratio)} />
            <Metric label="Phrase-local jumps" value={formatCountRatio(continuity?.local_large_jump_count, continuity?.local_adjacent_pair_count, continuity?.local_large_jump_ratio)} />
            <Metric label="Cross-phrase jumps" value={formatCountRatio(continuity?.cross_phrase_large_jump_count, continuity?.cross_phrase_adjacent_pair_count, continuity?.cross_phrase_large_jump_ratio)} />
            <Metric label="Median pitch" value={continuity?.median_pitch ?? '?'} />
            <Metric label="Pitch range" value={formatPitchRange(continuity?.pitch_range)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Reference MIDI suspect diagnostics</CardTitle>
              <StatusBadge status={referenceSuspect ? 'partial' : 'success'} />
            </div>
            <CardDescription>Benchmark/debug evidence only; it never transposes, shifts, or mutates production ScoreRevision.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <Metric label="Diagnostic only" value={referenceAlignment?.diagnostic_only ? 'yes' : 'no'} />
              <Metric label="First-note delay" value={formatSeconds(referenceAlignment?.first_note_delay_sec)} />
              <Metric label="Possible global offset" value={formatSeconds(referenceAlignment?.possible_global_time_offset_sec)} />
              <Metric label="Possible octave shift" value={formatSemitones(referenceAlignment?.best_octave_shift_semitones)} />
              <Metric label="Median pitch delta" value={formatSemitones(referenceAlignment?.median_pitch_delta_raw)} />
              <Metric label="DTW recall lift" value={formatPercent(referenceAlignment?.dtw_recall_lift)} />
            </div>
            <div>
              <div className="mb-2 text-xs text-muted-foreground">Triggered reasons</div>
              <div className="flex flex-wrap gap-2">
                {(referenceAlignment?.reason_codes.length ? referenceAlignment.reason_codes : ['none']).map((reason) => (
                  <Badge key={reason} variant={reason === 'none' ? 'secondary' : 'warning'}>{formatDiagnosticReason(reason)}</Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Failure reason</CardTitle>
            <CardDescription>If a required stage fails, the UI must show it clearly instead of masking it with fake success.</CardDescription>
          </CardHeader>
          <CardContent>
            {data?.stage_failure_reason ? (
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="Failed stage" value={data.stage_failure_reason.stage} />
                <Metric label="Error code" value={data.stage_failure_reason.error_code} />
                <Metric label="Error message" value={data.stage_failure_reason.error_message} />
                <div className="rounded-lg border bg-muted/30 p-3">
                  <div className="text-xs text-muted-foreground">Retryable</div>
                  <div className="mt-1"><StatusBadge status={data.stage_failure_reason.retryable ? 'retryable' : 'failed'} /></div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No required-stage failure is recorded for this sample project.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Finding({ title, ok, text }: { title: string; ok: boolean; text: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium">{title}</div>
        <StatusBadge status={ok ? 'success' : 'partial'} />
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{text}</p>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-all font-mono text-sm">{value}</div>
    </div>
  )
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return '?'
  return `${(value * 100).toFixed(1)}%`
}

function formatSeconds(value: number | null | undefined) {
  if (value === null || value === undefined) return '?'
  return `${value.toFixed(3)}s`
}

function formatSemitones(value: number | null | undefined) {
  if (value === null || value === undefined) return '?'
  return `${value > 0 ? '+' : ''}${value.toFixed(0)} st`
}

function formatCountRatio(count: number | null | undefined, total: number | null | undefined, ratio: number | null | undefined) {
  if (count === null || count === undefined || total === null || total === undefined) return '?'
  return `${count}/${total} ? ${formatPercent(ratio)}`
}

function formatPitchRange(range: [number | null, number | null] | null | undefined) {
  if (!range || range[0] === null || range[1] === null) return '?'
  return `${range[0]}?${range[1]}`
}

const diagnosticReasonLabels: Record<string, string> = {
  reference_first_note_offset_suspect: 'first-note delay suspect',
  reference_time_origin_needs_review: 'time origin needs review',
  possible_global_time_offset: 'possible global time offset',
  smart_onset_alignment_improves_recall: 'smart onset alignment improves recall',
  possible_octave_or_reference_pitch_mismatch: 'possible octave/reference pitch mismatch',
  possible_global_octave_shift: 'possible global octave shift',
  octave_normalized_matching_improves: 'octave-normalized matching improves',
  dtw_sequence_alignment_suspect: 'DTW sequence alignment suspect',
  possible_wrong_reference_track_or_pitch_source: 'possible wrong reference track/pitch source',
  none: 'none',
}

function formatDiagnosticReason(reason: string) {
  return diagnosticReasonLabels[reason] ?? reason
}
