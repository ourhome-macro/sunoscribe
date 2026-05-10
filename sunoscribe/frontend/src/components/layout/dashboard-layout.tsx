import { Outlet } from 'react-router-dom'

import { AppSidebar, MobileNav } from './app-sidebar'
import { TopNav } from './top-nav'

export function DashboardLayout() {
  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopNav />
          <MobileNav />
          <main className="flex-1 p-4 lg:p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
