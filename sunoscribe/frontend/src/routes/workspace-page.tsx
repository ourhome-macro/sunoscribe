import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, FileJson, FileMusic } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { NoteDetailSheet } from '@/components/notes/note-detail-sheet'
import { UncertainNotesPanel } from '@/components/notes/uncertain-notes-panel'
import { DiffSummary } from '@/components/score/diff-summary'
import { OsmdPlaceholder } from '@/components/score/osmd-placeholder'
import { WaveformPlaceholder } from '@/components/score/waveform-placeholder'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { apiClient } from '@/lib/api/client'
import type { UncertainNoteDiagnosis } from '@/types/agents'
import type { RevisionDiffSummary } from '@/types/revision'

export function WorkspacePage() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? '6db4af60-1f69-4f74-b7c8-9c0e4c7fb101'
  const revisionParam = searchParams.get('revision') ?? undefined
  const projectQuery = useQuery({ queryKey: ['project', projectId], queryFn: () => apiClient.getProject(projectId) })
  const revisionsQuery = useQuery({ queryKey: ['project-revisions', projectId], queryFn: () => apiClient.listProjectRevisions(projectId) })
  const selectedRevisionId = revisionParam ?? revisionsQuery.data?.[0]?.id ?? ''
  const diagnosisQuery = useQuery({ queryKey: ['diagnose', selectedRevisionId], queryFn: () => apiClient.diagnoseRevision(selectedRevisionId), enabled: Boolean(selectedRevisionId) })
  const [selectedNote, setSelectedNote] = useState<UncertainNoteDiagnosis | null>(null)
  const [latestDiff, setLatestDiff] = useState<RevisionDiffSummary | null>(null)
  const [newRevisionId, setNewRevisionId] = useState<string | null>(null)

  const revisionOptions = useMemo(
    () =>
      (revisionsQuery.data ?? []).map((revision) => ({
        label: `r${revision.revision_number} · ${revision.revision_type}`,
        value: revision.id,
      })),
    [revisionsQuery.data],
  )

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Score Workspace</h1>
          <p className="mt-1 text-sm text-muted-foreground">{projectQuery.data?.name ?? 'Lead-vocal transcription workspace'}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select className="min-w-64" value={selectedRevisionId} options={revisionOptions} onChange={() => undefined} />
          <Button variant="outline">
            <FileMusic className="h-4 w-4" /> MusicXML
          </Button>
          <Button variant="outline">
            <Download className="h-4 w-4" /> MIDI
          </Button>
          <Button variant="outline">
            <FileJson className="h-4 w-4" /> score view JSON
          </Button>
        </div>
      </div>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(460px,0.85fr)]">
        <OsmdPlaceholder />
        <UncertainNotesPanel notes={diagnosisQuery.data?.uncertain_notes ?? []} onSelectNote={setSelectedNote} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <WaveformPlaceholder />
        <Card>
          <CardHeader>
            <CardTitle>Debug Summary</CardTitle>
            <CardDescription>只读诊断摘要，复杂 F0Track 不在 UI summary 中请求。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="rounded-lg border bg-muted/30 p-3">{diagnosisQuery.data?.summary ?? '等待诊断摘要'}</div>
            <div className="rounded-lg border bg-muted/30 p-3">new revision id: {newRevisionId ?? '—'}</div>
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
