import { Link } from 'react-router-dom'

import { StatusBadge } from '@/components/layout/status-badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDateTime } from '@/lib/utils'
import type { ProjectSummary } from '@/types/project'

export function ProjectsTable({ projects }: { projects: ProjectSummary[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>歌曲 ID</TableHead>
          <TableHead>歌曲/项目名</TableHead>
          <TableHead>处理状态</TableHead>
          <TableHead>上传时间</TableHead>
          <TableHead>最新乐谱版本</TableHead>
          <TableHead>导出文件</TableHead>
          <TableHead className="text-right">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {projects.map((project) => (
          <TableRow key={project.project_id}>
            <TableCell className="font-mono text-xs">{project.project_id}</TableCell>
            <TableCell className="font-medium">{project.name}</TableCell>
            <TableCell>
              <StatusBadge status={project.status} />
            </TableCell>
            <TableCell>{formatDateTime(project.created_at)}</TableCell>
            <TableCell className="font-mono text-xs">{project.latest_revision ?? '—'}</TableCell>
            <TableCell>
              <StatusBadge status={project.export_status} />
            </TableCell>
            <TableCell className="text-right">
              <Button asChild variant="outline" size="sm">
                <Link to={`/projects/${project.project_id}`}>查看详情</Link>
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
