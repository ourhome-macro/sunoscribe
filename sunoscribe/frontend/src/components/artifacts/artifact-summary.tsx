import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatArtifactType } from '@/lib/copy'
import { formatDateTime } from '@/lib/utils'
import type { PublicArtifactResponse } from '@/types/artifact'

export function ArtifactSummary({ artifacts }: { artifacts: PublicArtifactResponse[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>生成文件</CardTitle>
        <CardDescription>这里列出系统处理这首歌时留下的文件和摘要；只显示公开信息，不显示后端存储路径。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>文件类型</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>文件名</TableHead>
              <TableHead>格式</TableHead>
              <TableHead>生成时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {artifacts.map((artifact) => (
              <TableRow key={artifact.id}>
                <TableCell>
                  <div className="font-medium">{formatArtifactType(artifact.artifact_type)}</div>
                  <div className="font-mono text-xs text-muted-foreground">{artifact.artifact_type}</div>
                </TableCell>
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
