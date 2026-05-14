import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudioAnalysisPanel } from '@/components/audio-analysis/audio-analysis-panel'
import { ArtifactSummary } from '@/components/artifacts/artifact-summary'
import { StageProgress } from '@/components/diagnostics/stage-progress'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { TaskStatusCard } from '@/components/tasks/task-status-card'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { RevisionList } from '@/features/revisions/revision-list'
import { apiClient } from '@/lib/api/client'
import { formatDateTime } from '@/lib/utils'

export function ProjectDetailPage() {
  const queryClient = useQueryClient()
  const { projectId = '' } = useParams()
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => apiClient.getProject(projectId),
    refetchInterval: (query) => (query.state.data?.analysis_status === 'running' ? 3000 : false),
  })
  const trackedTaskQuery = useQuery({
    queryKey: ['project-task', projectId],
    queryFn: () => apiClient.getTrackedProjectTask(projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' || status === 'retrying' ? 2000 : false
    },
  })
  const revisionsQuery = useQuery({ queryKey: ['project-revisions', projectId], queryFn: () => apiClient.listProjectRevisions(projectId) })
  const artifactsQuery = useQuery({ queryKey: ['project-artifacts', projectId], queryFn: () => apiClient.listArtifacts(projectId) })

  const project = projectQuery.data
  const latestRevision = revisionsQuery.data?.[0]
  const task = trackedTaskQuery.data

  const retryMutation = useMutation({
    mutationFn: () => apiClient.retryTask(trackedTaskQuery.data?.task_id ?? project?.current_task_id ?? ''),
    onSuccess: (task) => {
      queryClient.setQueryData(['project-task', projectId], task)
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      toast.success('任务已重新入队', { description: `task_id: ${task.task_id}` })
    },
  })

  return (
    <div>
      <PageHeader
        title={project?.name ?? '歌曲详情'}
        description="查看这首歌的处理进度、乐谱版本和系统生成的文件。"
        actions={
          <Button asChild disabled={!latestRevision}>
            <Link to={`/workspace?project=${projectId}&revision=${latestRevision?.id ?? ''}`}>进入乐谱工作台</Link>
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>歌曲信息</CardTitle>
            <CardDescription>{project?.description ?? '这首歌的主唱旋律会被整理成可检查的乐谱版本。'}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Detail label="歌曲 ID" value={project?.project_id ?? projectId} />
            <Detail label="处理状态" value={<StatusBadge status={project?.status} />} />
            <Detail label="分析进度" value={<StatusBadge status={project?.analysis_status} />} />
            <Detail label="上传时间" value={formatDateTime(project?.created_at)} />
            <Detail label="最新乐谱版本" value={project?.latest_revision ?? '—'} />
            <Detail label="导出文件" value={<StatusBadge status={project?.export_status} />} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>这首歌处理到了哪一步？</CardTitle>
            <CardDescription>成功表示该步骤已经留下可追踪结果；失败会显示明确原因，不会伪装成成功。</CardDescription>
          </CardHeader>
          <CardContent>
            <StageProgress stages={project?.stage_progress ?? []} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 space-y-6">
        <TaskStatusCard
          task={task}
          isLoading={trackedTaskQuery.isFetching || projectQuery.isFetching}
          isRetrying={retryMutation.isPending}
          onRetry={() => retryMutation.mutate()}
        />
        <RevisionList revisions={revisionsQuery.data ?? []} />
        <AudioAnalysisPanel revisionId={latestRevision?.id} />
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
