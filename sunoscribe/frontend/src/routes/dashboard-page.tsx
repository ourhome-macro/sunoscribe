import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileStack, FolderKanban, Music2 } from 'lucide-react'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/layout/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiClient } from '@/lib/api/client'
import { formatStatus } from '@/lib/copy'
import { formatDateTime } from '@/lib/utils'

export function DashboardPage() {
  const { data } = useQuery({ queryKey: ['dashboard'], queryFn: () => apiClient.getDashboard() })
  const problemNoteCount = data?.recent_revisions.reduce((total, revision) => total + (revision.client_summary?.uncertain_note_count ?? 0), 0) ?? 0

  return (
    <div>
      <PageHeader title="扒谱进度概览" description="从上传歌曲到生成主唱五线谱，这里显示每首歌现在走到哪一步。" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={FolderKanban} label="已上传歌曲" value={data?.stats.project_count ?? 0} />
        <MetricCard icon={Music2} label="已生成乐谱" value={data?.stats.ready_count ?? 0} />
        <MetricCard icon={FileStack} label="需要确认的音符" value={problemNoteCount} />
        <MetricCard icon={AlertTriangle} label="失败任务" value={data?.stats.failed_task_count ?? 0} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>最近歌曲</CardTitle>
            <CardDescription>选择一首歌，进入详情或继续检查它的乐谱版本。</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>歌曲/项目名</TableHead>
                  <TableHead>处理状态</TableHead>
                  <TableHead>最新乐谱版本</TableHead>
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
            <CardTitle>最近需要处理的问题</CardTitle>
            <CardDescription>如果主唱分离、音高识别或导出失败，系统会明确告诉你卡在哪一步。</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>卡住的步骤</TableHead>
                  <TableHead>原因</TableHead>
                  <TableHead>时间</TableHead>
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
          <CardTitle>最近乐谱版本</CardTitle>
          <CardDescription>
            <GlossaryTerm term="MIDI" />、<GlossaryTerm term="MusicXML" /> 和前端显示数据都从某个 <GlossaryTerm term="ScoreRevision" /> 导出。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>乐谱版本 ID</TableHead>
                <TableHead>版本来源</TableHead>
                <TableHead>音符数</TableHead>
                <TableHead>待确认音符</TableHead>
                <TableHead>导出状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_revisions.map((revision) => (
                <TableRow key={revision.id}>
                  <TableCell className="font-mono text-xs">{revision.id}</TableCell>
                  <TableCell>{formatStatus(revision.revision_type).label}</TableCell>
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
