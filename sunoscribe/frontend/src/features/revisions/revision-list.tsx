import { Link } from 'react-router-dom'

import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import type { ScoreRevisionSummary } from '@/types/revision'

export function RevisionList({ revisions }: { revisions: ScoreRevisionSummary[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Revision 列表</CardTitle>
        <CardDescription>机器 revision 与用户/agent revision 分离，不覆盖原始转写。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>revision</TableHead>
              <TableHead>type</TableHead>
              <TableHead>notes</TableHead>
              <TableHead>uncertain</TableHead>
              <TableHead>export_status</TableHead>
              <TableHead>created_at</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {revisions.map((revision) => (
              <TableRow key={revision.id}>
                <TableCell className="font-mono text-xs">{revision.id}</TableCell>
                <TableCell>{revision.revision_type}</TableCell>
                <TableCell>{revision.client_summary?.note_count ?? '—'}</TableCell>
                <TableCell>{revision.client_summary?.uncertain_note_count ?? '—'}</TableCell>
                <TableCell>
                  <StatusBadge status={revision.client_summary?.export_status} />
                </TableCell>
                <TableCell>{formatDateTime(revision.created_at)}</TableCell>
                <TableCell className="text-right">
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/workspace?revision=${revision.id}&project=${revision.project_id}`}>进入 Score Workspace</Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
