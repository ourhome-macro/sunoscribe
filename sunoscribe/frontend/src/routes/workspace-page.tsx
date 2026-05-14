import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, FileJson, FileMusic } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { NoteDetailSheet } from '@/components/notes/note-detail-sheet'
import { UncertainNotesPanel } from '@/components/notes/uncertain-notes-panel'
import { DiffSummary } from '@/components/score/diff-summary'
import { OsmdScoreViewer } from '@/components/score/osmd-score-viewer'
import { WaveformPlaceholder } from '@/components/score/waveform-placeholder'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { apiClient } from '@/lib/api/client'
import { formatStatus } from '@/lib/copy'
import type { ScoreExportFormat } from '@/types/artifact'
import type { UncertainNoteDiagnosis } from '@/types/agents'
import type { RevisionDiffSummary, ScoreRevisionSummary } from '@/types/revision'

export function WorkspacePage() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101'
  const revisionParam = searchParams.get('revision') ?? undefined
  const projectQuery = useQuery({ queryKey: ['project', projectId], queryFn: () => apiClient.getProject(projectId) })
  const revisionsQuery = useQuery({ queryKey: ['project-revisions', projectId], queryFn: () => apiClient.listProjectRevisions(projectId) })
  const selectedRevisionId = revisionParam ?? revisionsQuery.data?.[0]?.id ?? ''
  const selectedRevision = revisionsQuery.data?.find((revision) => revision.id === selectedRevisionId) ?? revisionsQuery.data?.[0]
  const diagnosisQuery = useQuery({ queryKey: ['diagnose', selectedRevisionId], queryFn: () => apiClient.diagnoseRevision(selectedRevisionId), enabled: Boolean(selectedRevisionId) })
  const musicXmlQuery = useQuery({
    queryKey: ['score-export', selectedRevision?.score_id, selectedRevisionId, 'musicxml'],
    queryFn: async () => {
      if (!selectedRevision) return null
      const download = await apiClient.downloadScoreExport(selectedRevision.score_id, selectedRevision.id, 'musicxml')
      return await download.blob.text()
    },
    enabled: Boolean(selectedRevision?.score_id && selectedRevisionId),
    retry: false,
  })
  const [selectedNote, setSelectedNote] = useState<UncertainNoteDiagnosis | null>(null)
  const [latestDiff, setLatestDiff] = useState<RevisionDiffSummary | null>(null)
  const [newRevisionId, setNewRevisionId] = useState<string | null>(null)

  const exportMutation = useMutation({
    mutationFn: async ({ revision, format }: { revision: ScoreRevisionSummary; format: ScoreExportFormat }) => apiClient.downloadScoreExport(revision.score_id, revision.id, format),
    onSuccess: (download) => {
      const href = URL.createObjectURL(download.blob)
      const anchor = document.createElement('a')
      anchor.href = href
      anchor.download = download.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(href)
      toast.success('导出文件已开始下载', { description: download.filename })
    },
    onError: (error) => {
      toast.error('导出失败', { description: error instanceof Error ? error.message : '后端没有返回可用导出。' })
    },
  })

  const downloadExport = (format: ScoreExportFormat) => {
    if (!selectedRevision) {
      toast.error('没有选中的乐谱版本')
      return
    }
    exportMutation.mutate({ revision: selectedRevision, format })
  }

  const revisionOptions = useMemo(
    () =>
      (revisionsQuery.data ?? []).map((revision) => ({
        label: `版本 ${revision.revision_number} · ${formatStatus(revision.revision_type).label}`,
        value: revision.id,
      })),
    [revisionsQuery.data],
  )

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">乐谱工作台</h1>
          <p className="mt-1 text-sm text-muted-foreground">当前歌曲：{projectQuery.data?.name ?? '主唱旋律扒谱'}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            当前乐谱版本用于检查、修正和导出；<GlossaryTerm term="MIDI" /> 与 <GlossaryTerm term="MusicXML" /> 都从它生成。
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select className="min-w-64" value={selectedRevisionId} options={revisionOptions} onChange={() => undefined} />
          <Button variant="outline" disabled={!selectedRevision || exportMutation.isPending} onClick={() => downloadExport('musicxml')}>
            <FileMusic className="h-4 w-4" /> 导出 MusicXML
          </Button>
          <Button variant="outline" disabled={!selectedRevision || exportMutation.isPending} onClick={() => downloadExport('midi')}>
            <Download className="h-4 w-4" /> 导出 MIDI
          </Button>
          <Button variant="outline" disabled={!selectedRevision || exportMutation.isPending} onClick={() => downloadExport('view')}>
            <FileJson className="h-4 w-4" /> 导出前端显示数据
          </Button>
        </div>
      </div>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(460px,0.85fr)]">
        <OsmdScoreViewer
          musicXml={musicXmlQuery.data}
          isLoading={musicXmlQuery.isFetching}
          error={musicXmlQuery.error instanceof Error ? musicXmlQuery.error.message : null}
        />
        <UncertainNotesPanel notes={diagnosisQuery.data?.uncertain_notes ?? []} onSelectNote={setSelectedNote} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <WaveformPlaceholder />
        <Card>
          <CardHeader>
            <CardTitle>诊断摘要</CardTitle>
            <CardDescription>这里只显示帮助听辨和修谱的摘要，不请求完整的人声音高轨迹。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-lg border bg-muted/30 p-3">{diagnosisQuery.data?.summary ?? '正在等待诊断摘要'}</div>
            <div className="rounded-lg border bg-muted/30 p-3">新乐谱版本：{newRevisionId ?? '—'}</div>
            <div className="rounded-lg border bg-muted/30 p-3">
              MIDI 浏览器播放尚未接入；当前提供后端受控下载，不伪装播放成功。
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <DiffSummary diff={latestDiff} />
      </div>

      <NoteDetailSheet
        note={selectedNote}
        revisionId={selectedRevisionId}
        onOpenChange={(open) => !open && setSelectedNote(null)}
        onApplied={({ revisionId, diffSummary }) => {
          setNewRevisionId(revisionId)
          setLatestDiff(diffSummary)
          setSelectedNote(null)
        }}
      />
    </div>
  )
}
