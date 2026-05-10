import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'

export function DiagnosticsPage() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101'
  const { data } = useQuery({ queryKey: ['diagnostics', projectId], queryFn: () => apiClient.getDiagnostics(projectId) })

  return (
    <div>
      <PageHeader title="Diagnostics" description="展示派生诊断摘要、量化质量、短音问题与 stage failure reason。" />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>derived_diagnostics</CardTitle>
            <CardDescription>只看 summary 和 artifact 可用性，不请求完整 F0Track。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">{data?.derived_diagnostics.summary}</p>
            <Metric label="score_revision_id" value={data?.derived_diagnostics.score_revision_id ?? '—'} />
            <Metric label="f0_track_available" value={String(data?.derived_diagnostics.f0_track_available ?? false)} />
            <Metric label="note_candidates_available" value={String(data?.derived_diagnostics.note_candidates_available ?? false)} />
            <Metric label="rhythm_grid_available" value={String(data?.derived_diagnostics.rhythm_grid_available ?? false)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>quantization diagnostics</CardTitle>
            <CardDescription>DP Quantizer 质量摘要。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="fallback_used" value={String(data?.quantization.fallback_used ?? false)} />
            <Metric label="fallback_reason" value={data?.quantization.fallback_reason ?? '—'} />
            <Metric label="mean_error" value={data?.quantization.mean_error_beats ?? '—'} />
            <Metric label="p95_error" value={data?.quantization.p95_error_beats ?? '—'} />
            <Metric label="max_error" value={data?.quantization.max_error_beats ?? '—'} />
            <Metric label="fragmentation" value={data?.quantization.fragmentation ?? '—'} />
            <Metric label="overmerge" value={data?.quantization.overmerge ?? '—'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>short-note diagnostics</CardTitle>
            <CardDescription>短音、voiced ratio、颤音与滑音风险。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="too_short_count" value={data?.short_notes.too_short_count ?? '—'} />
            <Metric label="low_voiced_ratio_count" value={data?.short_notes.low_voiced_ratio_count ?? '—'} />
            <Metric label="suspected_vibrato_count" value={data?.short_notes.suspected_vibrato_count ?? '—'} />
            <Metric label="suspected_glide_count" value={data?.short_notes.suspected_glide_count ?? '—'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>stage failure reason</CardTitle>
            <CardDescription>required stage 失败时必须显式展示。</CardDescription>
          </CardHeader>
          <CardContent>
            {data?.stage_failure_reason ? (
              <div className="space-y-3">
                <Metric label="stage" value={data.stage_failure_reason.stage} />
                <Metric label="error_code" value={data.stage_failure_reason.error_code} />
                <Metric label="error_message" value={data.stage_failure_reason.error_message} />
                <StatusBadge status={data.stage_failure_reason.retryable ? 'retryable' : 'failed'} />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">当前 mock 项目没有 required stage failure。</p>
            )}
          </CardContent>
        </Card>
      </div>
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
