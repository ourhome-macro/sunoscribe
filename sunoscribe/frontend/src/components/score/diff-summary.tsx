import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatPatchType } from '@/lib/copy'
import type { RevisionDiffSummary } from '@/types/revision'

export function DiffSummary({ diff }: { diff: RevisionDiffSummary | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>本次修改摘要</CardTitle>
        <CardDescription>应用修正后，系统会创建新的乐谱版本，并记录改动了哪些音符。</CardDescription>
      </CardHeader>
      <CardContent>
        {diff ? (
          <div className="grid gap-3 md:grid-cols-3">
            <Item label="修改次数" value={diff.operation_count ?? 0} />
            <Item label="修改类型" value={(diff.operations ?? []).map((operation) => formatPatchType(operation).label).join('、') || '—'} />
            <Item label="改动的音符" value={(diff.changed_note_ids ?? []).join('、') || '—'} />
            <Item label="删除的音符" value={(diff.deleted_note_ids ?? []).join('、') || '—'} />
            <Item label="修改前音符数" value={diff.note_count_before ?? '—'} />
            <Item label="修改后音符数" value={diff.note_count_after ?? '—'} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">还没有应用任何修正。点击右侧“需要确认的音符”开始。</p>
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
