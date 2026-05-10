import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { ArtifactSummary } from '@/components/artifacts/artifact-summary'
import { StageProgress } from '@/components/diagnostics/stage-progress'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { RevisionList } from '@/features/revisions/revision-list'
import { apiClient } from '@/lib/api/client'
import { formatDateTime } from '@/lib/utils'

export function ProjectDetailPage() {
  const { projectId = '' } = useParams()
  const projectQuery = useQuery({ queryKey: ['project', projectId], queryFn: () => apiClient.getProject(projectId) })
  const revisionsQuery = useQuery({ queryKey: ['project-revisions', projectId], queryFn: () => apiClient.listProjectRevisions(projectId) })
  const artifactsQuery = useQuery({ queryKey: ['project-artifacts', projectId], queryFn: () => apiClient.listArtifacts(projectId) })

  const project = projectQuery.data
  const latestRevision = revisionsQuery.data?.[0]

  return (
    <div>
      <PageHeader
        title={project?.name ?? 'Project Detail'}
        description="项目信息、当前分析状态、revision 和 artifact 摘要。"
        actions={
          <Button asChild disabled={!latestRevision}>
            <Link to={`/workspace?project=${projectId}&revision=${latestRevision?.id ?? ''}`}>进入 Score Workspace</Link>
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>项目信息</CardTitle>
            <CardDescription>{project?.description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Detail label="project_id" value={project?.project_id ?? projectId} />
            <Detail label="status" value={<StatusBadge status={project?.status} />} />
            <Detail label="analysis_status" value={<StatusBadge status={project?.analysis_status} />} />
            <Detail label="created_at" value={formatDateTime(project?.created_at)} />
            <Detail label="latest_revision" value={project?.latest_revision ?? '—'} />
            <Detail label="export_status" value={<StatusBadge status={project?.export_status} />} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>当前分析状态</CardTitle>
            <CardDescription>typed data lineage 的阶段性占位展示。</CardDescription>
          </CardHeader>
          <CardContent>
            <StageProgress stages={project?.stage_progress ?? []} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 space-y-6">
        <RevisionList revisions={revisionsQuery.data ?? []} />
        <ArtifactSummary artifacts={artifactsQuery.data ?? []} />
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-all font-medium">{value}</div>
    </div>
  )
}
