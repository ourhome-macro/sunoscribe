import { Activity, BarChart3, FileAudio, FolderKanban, Home, Music2, Settings, UploadCloud } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { navCopy } from '@/lib/copy'
import { cn } from '@/lib/utils'

const navItems = [
  { label: navCopy.dashboard, href: '/', icon: Home },
  { label: navCopy.projects, href: '/projects', icon: FolderKanban },
  { label: navCopy.upload, href: '/upload', icon: UploadCloud },
  { label: navCopy.workspace, href: '/workspace', icon: Music2 },
  { label: navCopy.diagnostics, href: '/diagnostics', icon: Activity },
  { label: navCopy.settings, href: '/settings', icon: Settings },
]

export function AppSidebar() {
  return (
    <aside className="hidden h-screen w-72 shrink-0 border-r bg-card lg:sticky lg:top-0 lg:flex lg:flex-col">
      <div className="flex h-16 items-center gap-3 border-b px-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <FileAudio className="h-5 w-5" />
        </div>
        <div>
          <div className="font-semibold">SunoScribe</div>
          <div className="text-xs text-muted-foreground">AI 自动扒谱工作台</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => (
          <NavLink
            key={item.href}
            to={item.href}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
                isActive && 'bg-accent text-accent-foreground',
              )
            }
            end={item.href === '/'}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-4">
        <div className="rounded-xl bg-muted p-3 text-xs text-muted-foreground">
          <div className="mb-1 flex items-center gap-2 font-medium text-foreground">
            <BarChart3 className="h-3.5 w-3.5" /> 以乐谱版本为准
          </div>
          导出的 MIDI 和 MusicXML 只来自当前乐谱版本，不反过来当作原始答案。
        </div>
      </div>
    </aside>
  )
}

export function MobileNav() {
  return (
    <div className="flex gap-2 overflow-x-auto border-b bg-card px-4 py-2 lg:hidden">
      {navItems.map((item) => (
        <NavLink
          key={item.href}
          to={item.href}
          className={({ isActive }) =>
            cn(
              'flex min-w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium text-muted-foreground',
              isActive && 'bg-accent text-accent-foreground',
            )
          }
          end={item.href === '/'}
        >
          <item.icon className="h-3.5 w-3.5" />
          {item.label}
        </NavLink>
      ))}
    </div>
  )
}
