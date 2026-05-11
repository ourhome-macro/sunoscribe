import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

import { ThemeToggle } from './theme-toggle'

export function TopNav() {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b bg-background/90 px-4 backdrop-blur lg:px-6">
      <div className="flex-1">
        <div className="relative max-w-xl">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" placeholder="搜索歌曲、乐谱版本、问题音符..." />
        </div>
      </div>
      <div className="hidden text-right text-xs text-muted-foreground sm:block">
        <div className="font-medium text-foreground">上传歌曲，检查乐谱，导出文件</div>
        <div>乐谱版本是修改和导出的依据</div>
      </div>
      <ThemeToggle />
    </header>
  )
}
