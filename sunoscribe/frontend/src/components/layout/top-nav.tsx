import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

import { ThemeToggle } from './theme-toggle'

export function TopNav() {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b bg-background/90 px-4 backdrop-blur lg:px-6">
      <div className="flex-1">
        <div className="relative max-w-xl">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" placeholder="搜索 project_id、revision、note_id..." />
        </div>
      </div>
      <div className="hidden text-right text-xs text-muted-foreground sm:block">
        <div className="font-medium text-foreground">AI 自动扒谱工作台</div>
        <div>ScoreIR / ScoreRevision 为事实源</div>
      </div>
      <ThemeToggle />
    </header>
  )
}
