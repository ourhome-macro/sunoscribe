import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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
        <CardTitle>Uncertain Notes</CardTitle>
        <CardDescription>来自 agent diagnose 与 ScoreRevision client summary。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>note_id</TableHead>
              <TableHead>measure</TableHead>
              <TableHead>beat</TableHead>
              <TableHead>pitch</TableHead>
              <TableHead>confidence</TableHead>
              <TableHead>reason_codes</TableHead>
              <TableHead>suggested_patch_types</TableHead>
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
                        {patchType}
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
