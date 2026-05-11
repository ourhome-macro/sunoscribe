import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ProjectsTable } from '@/features/projects/projects-table'
import { apiClient } from '@/lib/api/client'

export function ProjectsPage() {
  const { data = [] } = useQuery({ queryKey: ['projects'], queryFn: () => apiClient.listProjects() })

  return (
    <div>
      <PageHeader
        title="我的歌曲"
        description="每一首歌都有自己的处理状态、最新乐谱版本和可导出的文件。"
        actions={
          <Button asChild>
            <Link to="/upload">上传新歌曲</Link>
          </Button>
        }
      />
      <Card>
        <CardContent className="pt-6">
          <ProjectsTable projects={data} />
        </CardContent>
      </Card>
    </div>
  )
}
