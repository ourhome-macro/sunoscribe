import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { RevisionDiffSummary } from '@/types/revision'

export function DiffSummary({ diff }: { diff: RevisionDiffSummary | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Diff Summary</CardTitle>
        <CardDescription>Patch apply 成功后由新 ScoreRevision 返回。</CardDescription>
      </CardHeader>
      <CardContent>
        {diff ? (
          <div className="grid gap-3 md:grid-cols-3">
            <Item label="operation_count" value={diff.operation_count ?? 0} />
            <Item label="operations" value={(diff.operations ?? []).join(', ') || '—'} />
            <Item label="changed_note_ids" value={(diff.changed_note_ids ?? []).join(', ') || '—'} />
            <Item label="deleted_note_ids" value={(diff.deleted_note_ids ?? []).join(', ') || '—'} />
            <Item label="note_count_before" value={diff.note_count_before ?? '—'} />
            <Item label="note_count_after" value={diff.note_count_after ?? '—'} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">尚未应用 patch。</p>
        )}
      </CardContent>
    </Card>
  )
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-all font-mono text-sm">{value}</div>
    </div>
  )
}
