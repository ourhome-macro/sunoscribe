import { RefreshCw } from 'lucide-react'

import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/lib/utils'
import type { TaskStatusResponse } from '@/types/task'

export function TaskStatusCard({
  task,
  isLoading,
  isRetrying,
  onRetry,
}: {
  task: TaskStatusResponse | null | undefined
  isLoading?: boolean
  isRetrying?: boolean
  onRetry?: () => void
}) {
  if (!task) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>后端任务</CardTitle>
          <CardDescription>当前页面还没有可轮询的后端 task_id。</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          上传并触发生成后，前端会用后端返回的 task_id 轮询状态；不会在缺少任务时伪造成功。
        </CardContent>
      </Card>
    )
  }

  const failed = task.status === 'failed'

  return (
    <Card className={failed ? 'border-destructive/50' : undefined}>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>后端任务</CardTitle>
            <CardDescription>task_id: {task.task_id}</CardDescription>
          </div>
          <StatusBadge status={task.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div>
          <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
            <span>{task.task_type}</span>
            <span>{task.progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className={failed ? 'h-full bg-destructive' : 'h-full bg-primary'} style={{ width: `${Math.max(0, Math.min(100, task.progress))}%` }} />
          </div>
        </div>

        {failed ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-destructive">
            <div className="font-medium">Required stage failed</div>
            <div className="mt-1 text-xs">{task.error_message ?? '后端任务失败，但没有返回具体错误信息。'}</div>
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-3">
          <Meta label="排队时间" value={formatDateTime(task.queued_at)} />
          <Meta label="开始时间" value={formatDateTime(task.started_at)} />
          <Meta label="结束时间" value={formatDateTime(task.finished_at)} />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground">
            Retry {task.retry_count}/{task.max_retries} · {isLoading ? '轮询中' : '等待下一次轮询'}
          </div>
          <Button variant="outline" size="sm" disabled={!task.can_retry || isRetrying} onClick={onRetry}>
            <RefreshCw className={isRetrying ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            重试任务
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-all font-medium">{value}</div>
    </div>
  )
}

