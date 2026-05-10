import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import type { PublicArtifactResponse } from '@/types/artifact'

export function ArtifactSummary({ artifacts }: { artifacts: PublicArtifactResponse[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Artifact 摘要</CardTitle>
        <CardDescription>仅展示公开 metadata；不展示后端存储路径。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>type</TableHead>
              <TableHead>status</TableHead>
              <TableHead>filename</TableHead>
              <TableHead>mime</TableHead>
              <TableHead>created_at</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {artifacts.map((artifact) => (
              <TableRow key={artifact.id}>
                <TableCell className="font-medium">{artifact.artifact_type}</TableCell>
                <TableCell>
                  <StatusBadge status={artifact.status} />
                </TableCell>
                <TableCell>{artifact.filename ?? '—'}</TableCell>
                <TableCell>{artifact.mime_type ?? '—'}</TableCell>
                <TableCell>{formatDateTime(artifact.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
