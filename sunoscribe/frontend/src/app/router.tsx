import { createBrowserRouter } from 'react-router-dom'

import { DashboardLayout } from '@/components/layout/dashboard-layout'
import { DashboardPage } from '@/routes/dashboard-page'
import { DiagnosticsPage } from '@/routes/diagnostics-page'
import { ProjectDetailPage } from '@/routes/project-detail-page'
import { ProjectsPage } from '@/routes/projects-page'
import { SettingsPage } from '@/routes/settings-page'
import { UploadPage } from '@/routes/upload-page'
import { WorkspacePage } from '@/routes/workspace-page'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <DashboardLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'projects', element: <ProjectsPage /> },
      { path: 'projects/:projectId', element: <ProjectDetailPage /> },
      { path: 'upload', element: <UploadPage /> },
      { path: 'workspace', element: <WorkspacePage /> },
      { path: 'diagnostics', element: <DiagnosticsPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
])
