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
        <CardTitle>Generated files</CardTitle>
        <CardDescription>
          Files are derived from a specific ScoreRevision. Quality-failed MIDI can still be available for diagnostic listening, but it is not marked as a clean transcription.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>File</TableHead>
              <TableHead>Format</TableHead>
              <TableHead>Generated</TableHead>
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
                  <div className="space-y-1">
                    <StatusBadge status={artifact.metadata?.export_scope ?? artifact.status} />
                    {artifact.metadata?.quality_gate_status ? (
                      <div className="text-xs text-muted-foreground">quality gate: {artifact.metadata.quality_gate_status}</div>
                    ) : null}
                    {artifact.metadata?.quality_failed_checks?.length ? (
                      <div className="text-xs text-muted-foreground">failed checks: {artifact.metadata.quality_failed_checks.join(', ')}</div>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  <div>{artifact.filename ?? '?'}</div>
                  {artifact.metadata?.diagnostic_message ? (
                    <div className="mt-1 max-w-xs text-xs text-muted-foreground">{artifact.metadata.diagnostic_message}</div>
                  ) : null}
                </TableCell>
                <TableCell>{artifact.mime_type ?? '?'}</TableCell>
                <TableCell>{formatDateTime(artifact.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
