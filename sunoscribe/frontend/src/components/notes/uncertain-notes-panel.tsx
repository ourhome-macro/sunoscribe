import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatPatchType } from '@/lib/copy'
import { formatPercent } from '@/lib/utils'
import type { UncertainNoteDiagnosis } from '@/types/agents'

import { ReasonCodeBadges } from './reason-code-badges'

interface UncertainNotesPanelProps {
  notes: UncertainNoteDiagnosis[]
  onSelectNote: (note: UncertainNoteDiagnosis) => void
}

export function UncertainNotesPanel({ notes, onSelectNote }: UncertainNotesPanelProps) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>需要确认的音符</CardTitle>
        <CardDescription>这些音符可能有八度、时值或节拍问题。点一行可以听辨后快速修正。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>音符 ID</TableHead>
              <TableHead>第几小节</TableHead>
              <TableHead>拍点</TableHead>
              <TableHead>音高</TableHead>
              <TableHead>可信度</TableHead>
              <TableHead>为什么不确定</TableHead>
              <TableHead>建议操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {notes.map((note) => (
              <TableRow key={note.note_id} className="cursor-pointer" onClick={() => onSelectNote(note)}>
                <TableCell className="font-mono text-xs">{note.note_id}</TableCell>
                <TableCell>{note.measure ?? '—'}</TableCell>
                <TableCell>{note.beat ?? '—'}</TableCell>
                <TableCell className="font-medium">{note.pitch}</TableCell>
                <TableCell>{formatPercent(note.confidence)}</TableCell>
                <TableCell>
                  <ReasonCodeBadges codes={note.reason_codes} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {note.suggested_patch_types.map((patchType) => (
                      <Button key={patchType} size="sm" variant="secondary" className="h-7 text-xs" onClick={(event) => event.preventDefault()}>
                        {formatPatchType(patchType).label}
                      </Button>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
