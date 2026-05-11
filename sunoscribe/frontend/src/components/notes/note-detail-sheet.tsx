import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { ReasonCodeBadges } from '@/components/notes/reason-code-badges'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { apiClient } from '@/lib/api/client'
import { formatPatchType } from '@/lib/copy'
import { formatPercent } from '@/lib/utils'
import type { AgentPatchOperation, UncertainNoteDiagnosis } from '@/types/agents'
import type { RevisionDiffSummary } from '@/types/revision'

interface NoteDetailSheetProps {
  note: UncertainNoteDiagnosis | null
  revisionId: string
  onOpenChange: (open: boolean) => void
  onApplied: (result: { revisionId: string; diffSummary: RevisionDiffSummary }) => void
}

export function NoteDetailSheet({ note, revisionId, onOpenChange, onApplied }: NoteDetailSheetProps) {
  const mutation = useMutation({
    mutationFn: (operation: AgentPatchOperation) =>
      apiClient.applyScorePatch(revisionId, {
        base_revision_id: revisionId,
        operations: [operation],
        rationale: `Quick patch for ${operation.op}`,
        confidence: 0.72,
      }),
    onSuccess: (revision) => {
      toast.success('已创建新的乐谱版本', {
        description: `新版本 ID：${revision.id}`,
      })
      onApplied({ revisionId: revision.id, diffSummary: revision.diff_summary })
    },
  })

  const apply = (operation: AgentPatchOperation) => mutation.mutate(operation)

  return (
    <Sheet open={Boolean(note)} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto">
        {note ? (
          <>
            <SheetHeader>
              <SheetTitle>确认音符 · {note.note_id}</SheetTitle>
              <SheetDescription>
                这些按钮会提交受控修改，并由后端校验后生成新的 <GlossaryTerm term="ScoreRevision" />。
              </SheetDescription>
            </SheetHeader>
            <div className="mt-6 space-y-6">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Detail label="音高" value={note.pitch} />
                <Detail label="可信度" value={formatPercent(note.confidence)} />
                <Detail label="第几小节" value={note.measure ?? '—'} />
                <Detail label="拍点" value={note.beat ?? '—'} />
                <Detail label="起点 tick" value={note.onset_tick ?? '—'} />
                <Detail label="时值 tick" value={note.duration_tick ?? '—'} />
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">为什么不确定？</div>
                <ReasonCodeBadges codes={note.reason_codes} />
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">系统建议</div>
                <div className="grid gap-2">
                  {note.suggested_patch_types.map((patchType) => {
                    const copy = formatPatchType(patchType)
                    return (
                      <div key={patchType} className="rounded-lg border bg-muted/30 p-3 text-sm">
                        <div className="font-medium">{copy.label}</div>
                        <div className="text-xs text-muted-foreground">{copy.description}</div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium">快速修正</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Button disabled={mutation.isPending} onClick={() => apply({ op: 'shift_octave', note_id: note.note_id, octaves: 1, reason: 'raise one octave' })}>
                    升高八度
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'shift_octave', note_id: note.note_id, octaves: -1, reason: 'lower one octave' })}>
                    降低八度
                  </Button>
                  <Button disabled={mutation.isPending} variant="secondary" onClick={() => apply({ op: 'mark_uncertain', note_id: note.note_id, reason: 'needs manual review' })}>
                    标记待确认
                  </Button>
                  <Button disabled={mutation.isPending} variant="destructive" onClick={() => apply({ op: 'delete_note', note_id: note.note_id, reason: 'remove uncertain note' })}>
                    删除这个音
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'adjust_duration', note_id: note.note_id, duration_beats: 0.5, reason: 'shorten to half beat' })}>
                    改短：半拍
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'adjust_duration', note_id: note.note_id, duration_beats: 1, reason: 'set to one beat' })}>
                    改长/对齐：一拍
                  </Button>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm">{value}</div>
    </div>
  )
}
