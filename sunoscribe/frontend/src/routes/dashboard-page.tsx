import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileStack, FolderKanban, GitBranch } from 'lucide-react'

import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiClient } from '@/lib/api/client'
import { formatDateTime } from '@/lib/utils'

export function DashboardPage() {
  const { data } = useQuery({ queryKey: ['dashboard'], queryFn: () => apiClient.getDashboard() })

  return (
    <div>
      <PageHeader title="Dashboard" description="AI lead-vocal transcription 工作台概览。" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={FolderKanban} label="项目数" value={data?.stats.project_count ?? 0} />
        <MetricCard icon={FileStack} label="Ready" value={data?.stats.ready_count ?? 0} />
        <MetricCard icon={AlertTriangle} label="失败任务" value={data?.stats.failed_task_count ?? 0} />
        <MetricCard icon={GitBranch} label="Revisions" value={data?.stats.revision_count ?? 0} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>最近项目</CardTitle>
            <CardDescription>按项目和最新 revision 进入工作流。</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>name</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>latest_revision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.recent_projects.map((project) => (
                  <TableRow key={project.project_id}>
                    <TableCell className="font-medium">{project.name}</TableCell>
                    <TableCell>
                      <StatusBadge status={project.status} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{project.latest_revision ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近失败任务</CardTitle>
            <CardDescription>required stage 失败应明确展示。</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>stage</TableHead>
                  <TableHead>reason</TableHead>
                  <TableHead>created_at</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.recent_failed_tasks.map((task) => (
                  <TableRow key={task.task_id}>
                    <TableCell>{task.stage}</TableCell>
                    <TableCell>{task.reason}</TableCell>
                    <TableCell>{formatDateTime(task.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>最近 revision</CardTitle>
          <CardDescription>MIDI、MusicXML、view JSON 均由具体 revision 派生。</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>revision_id</TableHead>
                <TableHead>type</TableHead>
                <TableHead>notes</TableHead>
                <TableHead>uncertain</TableHead>
                <TableHead>export_status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_revisions.map((revision) => (
                <TableRow key={revision.id}>
                  <TableCell className="font-mono text-xs">{revision.id}</TableCell>
                  <TableCell>{revision.revision_type}</TableCell>
                  <TableCell>{revision.client_summary?.note_count ?? '—'}</TableCell>
                  <TableCell>{revision.client_summary?.uncertain_note_count ?? '—'}</TableCell>
                  <TableCell>
                    <StatusBadge status={revision.client_summary?.export_status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function MetricCard({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
      </CardContent>
    </Card>
  )
}
