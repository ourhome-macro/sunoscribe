import { Link } from 'react-router-dom'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatStatus } from '@/lib/copy'
import { formatDateTime } from '@/lib/utils'
import type { ScoreRevisionSummary } from '@/types/revision'

export function RevisionList({ revisions }: { revisions: ScoreRevisionSummary[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>乐谱版本</CardTitle>
        <CardDescription>
          每次机器生成、人工修改或助手修正都会创建新的 <GlossaryTerm term="ScoreRevision" />，不会覆盖原始结果。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>版本 ID</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>音符数</TableHead>
              <TableHead>待确认音符</TableHead>
              <TableHead>导出状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {revisions.map((revision) => (
              <TableRow key={revision.id}>
                <TableCell className="font-mono text-xs">{revision.id}</TableCell>
                <TableCell>{formatStatus(revision.revision_type).label}</TableCell>
                <TableCell>{revision.client_summary?.note_count ?? '—'}</TableCell>
                <TableCell>{revision.client_summary?.uncertain_note_count ?? '—'}</TableCell>
                <TableCell>
                  <StatusBadge status={revision.client_summary?.export_status} />
                </TableCell>
                <TableCell>{formatDateTime(revision.created_at)}</TableCell>
                <TableCell className="text-right">
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/workspace?revision=${revision.id}&project=${revision.project_id}`}>打开乐谱</Link>
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
