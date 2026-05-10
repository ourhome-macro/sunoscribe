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
        title="Projects"
        description="项目列表展示分析状态、latest revision 与 revision-scoped export 状态。"
        actions={
          <Button asChild>
            <Link to="/upload">创建项目</Link>
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
