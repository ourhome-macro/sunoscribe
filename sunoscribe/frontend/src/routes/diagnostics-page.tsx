import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'

export function DiagnosticsPage() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101'
  const { data } = useQuery({ queryKey: ['diagnostics', projectId], queryFn: () => apiClient.getDiagnostics(projectId) })

  const rhythmLooksStable = !data?.quantization.fallback_used && (data?.quantization.p95_error_beats ?? 1) < 0.25
  const shortNoteRisk = (data?.short_notes.too_short_count ?? 0) + (data?.short_notes.suspected_vibrato_count ?? 0)

  return (
    <div>
      <PageHeader title="诊断报告" description="先给出音乐上能理解的结论，再保留技术详情方便排查。" />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>给音乐用户看的结论</CardTitle>
            <CardDescription>这些结论帮助你判断这份乐谱是否值得继续人工修正。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Finding title="节拍对齐" ok={rhythmLooksStable} text={rhythmLooksStable ? '大部分音符和拍子对齐较稳定。' : '节拍对齐不够稳定，部分音符的小节或拍点可能需要检查。'} />
            <Finding title="短音风险" ok={shortNoteRisk < 8} text={shortNoteRisk < 8 ? '短音和颤音风险数量可控。' : '短音或颤音风险偏多，可能需要逐句听辨。'} />
            <Finding title="主唱旋律链路" ok={!data?.stage_failure_reason} text={data?.stage_failure_reason ? '处理链路有失败步骤，不能把当前结果当成完整成功。' : '当前没有 required stage 失败记录。'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>派生诊断摘要</CardTitle>
            <CardDescription>
              前端只读取摘要和可用性，不请求完整 <GlossaryTerm term="F0Track" />。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">{data?.derived_diagnostics.summary}</p>
            <Metric label="当前乐谱版本" value={data?.derived_diagnostics.score_revision_id ?? '—'} />
            <Metric label="人声音高摘要可用" value={data?.derived_diagnostics.f0_track_available ? '是' : '否'} />
            <Metric label="候选音符可用" value={data?.derived_diagnostics.note_candidates_available ? '是' : '否'} />
            <Metric label="节拍网格可用" value={data?.derived_diagnostics.rhythm_grid_available ? '是' : '否'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>技术详情：节拍对齐</CardTitle>
            <CardDescription>保留后端诊断字段，便于工程排查。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="是否用了备用路径" value={data?.quantization.fallback_used ? '是' : '否'} />
            <Metric label="备用原因" value={data?.quantization.fallback_reason ?? '—'} />
            <Metric label="平均误差（拍）" value={data?.quantization.mean_error_beats ?? '—'} />
            <Metric label="95% 误差（拍）" value={data?.quantization.p95_error_beats ?? '—'} />
            <Metric label="最大误差（拍）" value={data?.quantization.max_error_beats ?? '—'} />
            <Metric label="疑似切太碎" value={data?.quantization.fragmentation ?? '—'} />
            <Metric label="疑似合并过头" value={data?.quantization.overmerge ?? '—'} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>技术详情：短音与唱法</CardTitle>
            <CardDescription>短音、弱发声、颤音和滑音都会影响自动扒谱。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Metric label="短音数量" value={data?.short_notes.too_short_count ?? '—'} />
            <Metric label="有效人声少" value={data?.short_notes.low_voiced_ratio_count ?? '—'} />
            <Metric label="疑似颤音" value={data?.short_notes.suspected_vibrato_count ?? '—'} />
            <Metric label="疑似滑音" value={data?.short_notes.suspected_glide_count ?? '—'} />
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>失败原因</CardTitle>
            <CardDescription>如果 required stage 失败，必须明确展示，不用假结果冒充成功。</CardDescription>
          </CardHeader>
          <CardContent>
            {data?.stage_failure_reason ? (
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="失败步骤" value={data.stage_failure_reason.stage} />
                <Metric label="错误编码" value={data.stage_failure_reason.error_code} />
                <Metric label="错误信息" value={data.stage_failure_reason.error_message} />
                <div className="rounded-lg border bg-muted/30 p-3">
                  <div className="text-xs text-muted-foreground">是否可重试</div>
                  <div className="mt-1"><StatusBadge status={data.stage_failure_reason.retryable ? 'retryable' : 'failed'} /></div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">当前示例项目没有 required stage 失败。</p>
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
