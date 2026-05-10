import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ReasonCodeBadges } from '@/components/notes/reason-code-badges'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { apiClient } from '@/lib/api/client'
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
      toast.success('Patch applied', {
        description: `New revision ${revision.id}`,
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
              <SheetTitle>Note Detail · {note.note_id}</SheetTitle>
              <SheetDescription>基于 ScoreRevision 的受控 ScorePatch 操作，不直接改写整份 score。</SheetDescription>
            </SheetHeader>
            <div className="mt-6 space-y-6">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Detail label="pitch" value={note.pitch} />
                <Detail label="confidence" value={formatPercent(note.confidence)} />
                <Detail label="measure" value={note.measure ?? '—'} />
                <Detail label="beat" value={note.beat ?? '—'} />
                <Detail label="onset_tick" value={note.onset_tick ?? '—'} />
                <Detail label="duration_tick" value={note.duration_tick ?? '—'} />
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">reason_codes</div>
                <ReasonCodeBadges codes={note.reason_codes} />
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">suggested_patch_types</div>
                <div className="flex flex-wrap gap-2">
                  {note.suggested_patch_types.map((patchType) => (
                    <span key={patchType} className="rounded-md bg-muted px-2 py-1 text-xs">
                      {patchType}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium">Quick patch</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Button disabled={mutation.isPending} onClick={() => apply({ op: 'shift_octave', note_id: note.note_id, octaves: 1, reason: 'quick shift +12' })}>
                    shift_octave +12
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'shift_octave', note_id: note.note_id, octaves: -1, reason: 'quick shift -12' })}>
                    shift_octave -12
                  </Button>
                  <Button disabled={mutation.isPending} variant="secondary" onClick={() => apply({ op: 'mark_uncertain', note_id: note.note_id, reason: 'needs manual review' })}>
                    mark_uncertain
                  </Button>
                  <Button disabled={mutation.isPending} variant="destructive" onClick={() => apply({ op: 'delete_note', note_id: note.note_id, reason: 'remove uncertain note' })}>
                    delete_note
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'adjust_duration', note_id: note.note_id, duration_beats: 0.5, reason: 'preset half beat duration' })}>
                    adjust_duration 0.5 beat
                  </Button>
                  <Button disabled={mutation.isPending} variant="outline" onClick={() => apply({ op: 'adjust_duration', note_id: note.note_id, duration_beats: 1, reason: 'preset one beat duration' })}>
                    adjust_duration 1 beat
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
