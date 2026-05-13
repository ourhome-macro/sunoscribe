import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api/client'
import { formatDateTime, formatPercent } from '@/lib/utils'
import type { AudioAnalysisReportResponse } from '@/types/audio-analysis'

interface AudioAnalysisPanelProps {
  revisionId: string | null | undefined
}

export function AudioAnalysisPanel({ revisionId }: AudioAnalysisPanelProps) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['audio-analysis-report', revisionId],
    queryFn: () => apiClient.getAudioAnalysisReport(revisionId ?? ''),
    enabled: Boolean(revisionId),
    retry: false,
  })
  const mutation = useMutation({
    mutationFn: () => apiClient.generateAudioAnalysisReport(revisionId ?? ''),
    onSuccess: (data) => {
      queryClient.setQueryData(['audio-analysis-report', revisionId], data)
    },
  })

  const response = mutation.data ?? query.data
  const report = response?.report
  const isBusy = query.isLoading || mutation.isPending

  return (
    <Card>
      <CardHeader className="gap-3 md:flex-row md:items-start md:justify-between md:space-y-0">
        <div>
          <CardTitle>音频分析</CardTitle>
          <CardDescription>基于当前乐谱版本、F0、节奏网格和歌词生成的可选分析报告。</CardDescription>
        </div>
        <Button size="sm" onClick={() => mutation.mutate()} disabled={!revisionId || isBusy}>
          {response ? '重新生成' : '生成分析'}
        </Button>
      </CardHeader>
      <CardContent>
        {!revisionId ? (
          <EmptyState text="生成 ScoreRevision 后才能运行音频分析。" />
        ) : query.isError ? (
          <EmptyState text="读取音频分析失败，可以重新生成一份报告。" />
        ) : isBusy && !report ? (
          <EmptyState text="正在加载音频分析报告…" />
        ) : report ? (
          <ReportView response={response} />
        ) : (
          <EmptyState text="还没有音频分析报告。它不会影响转谱主流程，可以随时生成。" />
        )}
        {mutation.isError ? <div className="mt-3 text-sm text-destructive">生成音频分析失败，请查看后端日志或缺失 artifact。</div> : null}
      </CardContent>
    </Card>
  )
}

function ReportView({ response }: { response: AudioAnalysisReportResponse | null | undefined }) {
  const report = response?.report
  if (!report) return null

  return (
    <div className="space-y-5">
      <div className="rounded-lg border bg-muted/30 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={report.status} />
          <span className="text-xs text-muted-foreground">置信度 {formatPercent(report.summary.confidence)}</span>
          <span className="text-xs text-muted-foreground">生成于 {formatDateTime(response?.artifact_created_at ?? null)}</span>
        </div>
        <p className="mt-3 font-medium">{report.summary.headline}</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {report.summary.highlights.slice(0, 4).map((item) => (
            <div key={item} className="rounded-md bg-background px-3 py-2 text-sm text-muted-foreground">
              {item}
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="音域"
          primary={report.range.available ? `${report.range.lowest_pitch ?? '?'} – ${report.range.highest_pitch ?? '?'}` : '证据不足'}
          secondary={report.range.span_semitones !== null ? `${report.range.span_semitones} 个半音` : report.range.evidence}
        />
        <MetricCard
          title="音高走势"
          primary={directionLabel(report.pitch.melodic_direction)}
          secondary={report.pitch.available ? `音符 ${report.pitch.note_count}，常用 ${report.pitch.most_common_pitch_classes.join(' / ') || '?'}` : report.pitch.evidence}
        />
        <MetricCard
          title="演唱表现"
          primary={report.expression.available ? `${report.expression.vibrato_segment_count} 颤音 / ${report.expression.slide_segment_count} 滑音` : '证据不足'}
          secondary={report.expression.long_note_stability !== null ? `长音稳定度 ${formatPercent(report.expression.long_note_stability)}` : report.expression.evidence}
        />
        <MetricCard
          title="节奏律动"
          primary={report.rhythm.bpm ? `${report.rhythm.bpm} BPM` : '证据不足'}
          secondary={report.rhythm.stability_score !== null ? `稳定性 ${formatPercent(report.rhythm.stability_score)}` : report.rhythm.evidence}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-lg border p-4">
          <div className="text-sm font-medium">歌词情绪</div>
          {report.lyrics.available ? (
            <div className="mt-2 space-y-2 text-sm text-muted-foreground">
              <div>倾向：{sentimentLabel(report.lyrics.sentiment_label)}，歌词行数 {report.lyrics.line_count}</div>
              <div>关键词：{report.lyrics.keyword_candidates.slice(0, 8).join(' / ') || '—'}</div>
              <div>正向词：{report.lyrics.positive_keyword_hits.join(' / ') || '—'}；负向词：{report.lyrics.negative_keyword_hits.join(' / ') || '—'}</div>
            </div>
          ) : (
            <div className="mt-2 text-sm text-muted-foreground">未提供歌词，已跳过歌词情绪分析。</div>
          )}
        </div>

        <div className="rounded-lg border p-4">
          <div className="text-sm font-medium">注意事项</div>
          {report.warnings.length ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {report.warnings.slice(0, 8).map((warning) => (
                <span key={warning} className="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">
                  {warning}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-sm text-muted-foreground">没有明显缺失项。</div>
          )}
        </div>
      </div>
    </div>
  )
}

function MetricCard({ title, primary, secondary }: { title: string; primary: string; secondary: string }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="mt-2 text-lg font-semibold">{primary}</div>
      <div className="mt-1 text-xs text-muted-foreground">{secondary}</div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">{text}</div>
}

function directionLabel(value: string | null | undefined) {
  if (value === 'ascending_bias') return '偏上行'
  if (value === 'descending_bias') return '偏下行'
  if (value === 'balanced') return '上下行均衡'
  return '证据不足'
}

function sentimentLabel(value: string | null | undefined) {
  if (value === 'positive') return '偏积极'
  if (value === 'negative') return '偏消极'
  if (value === 'mixed') return '正负交织'
  if (value === 'neutral') return '较中性'
  return '未判断'
}
