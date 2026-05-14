import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { StageProgress } from '@/components/diagnostics/stage-progress'
import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { TaskStatusCard } from '@/components/tasks/task-status-card'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { apiClient } from '@/lib/api/client'
import type { StageProgressItem } from '@/types/project'

const uploadStages: StageProgressItem[] = [
  { stage: 'Media Ingest', status: 'pending' },
  { stage: 'StemService', status: 'pending' },
  { stage: 'F0Track', status: 'pending' },
  { stage: 'PitchContourIR', status: 'pending' },
  { stage: 'MelodySelector', status: 'pending' },
  { stage: 'DP Quantizer', status: 'pending' },
  { stage: 'ScoreIR', status: 'pending' },
  { stage: 'Exports', status: 'pending' },
]

export function UploadPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [mediaKind, setMediaKind] = useState<'audio' | 'video'>('audio')
  const [file, setFile] = useState<File | null>(null)
  const [started, setStarted] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)

  const stages = useMemo(
    () => uploadStages.map((stage, index) => ({ ...stage, status: started && index === 0 ? 'running' : stage.status }) as StageProgressItem),
    [started],
  )

  const mutation = useMutation({
    mutationFn: () => apiClient.createProject({ name, media_kind: mediaKind, file }),
    onSuccess: (result) => {
      setStarted(true)
      setTaskId(result.task_id)
      toast.success('已开始分析这首歌', { description: `歌曲 ID：${result.project_id} · 任务：${result.task_id}` })
    },
  })

  const taskQuery = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => apiClient.getTask(taskId ?? ''),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' || status === 'retrying' ? 2000 : false
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => apiClient.retryTask(taskId ?? ''),
    onSuccess: (task) => {
      setTaskId(task.task_id)
      queryClient.setQueryData(['task', task.task_id], task)
      toast.success('任务已重新入队', { description: `task_id: ${task.task_id}` })
    },
  })

  return (
    <div>
      <PageHeader title="上传歌曲" description="上传音频或视频，系统会提取主唱旋律并生成可检查的五线谱。" />
      <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>创建一首待扒谱歌曲</CardTitle>
            <CardDescription>
              上传文件会先成为原始来源，后续每一步都会留下可追踪的 <GlossaryTerm term="Artifact" />。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-name">歌曲或项目名称</Label>
              <Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：Mojito 主唱旋律" />
            </div>
            <div className="space-y-2">
              <Label>上传类型</Label>
              <Select
                value={mediaKind}
                onChange={(event) => setMediaKind(event.target.value as 'audio' | 'video')}
                options={[
                  { label: '音频文件', value: 'audio' },
                  { label: '视频文件', value: 'video' },
                ]}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="media-file">选择音频/视频文件</Label>
              <Input id="media-file" type="file" accept="audio/*,video/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <p className="text-xs text-muted-foreground">如果主唱分离或音高识别失败，系统会明确显示失败原因，不会用低质量结果冒充成功。</p>
            </div>
            <Button className="w-full" disabled={!name || !file || mutation.isPending} onClick={() => mutation.mutate()}>
              开始扒谱
            </Button>
            {mutation.isError ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {mutation.error instanceof Error ? mutation.error.message : '上传或创建任务失败。'}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>这首歌会经历哪些步骤？</CardTitle>
            <CardDescription>从上传歌曲到导出文件，每一步都对齐后端流水线。</CardDescription>
          </CardHeader>
          <CardContent>
            <StageProgress stages={stages} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <TaskStatusCard
          task={taskQuery.data}
          isLoading={taskQuery.isFetching}
          isRetrying={retryMutation.isPending}
          onRetry={() => retryMutation.mutate()}
        />
      </div>
    </div>
  )
}
