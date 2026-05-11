import { FileMusic } from 'lucide-react'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function OsmdPlaceholder() {
  return (
    <Card className="h-full min-h-[520px]">
      <CardHeader>
        <CardTitle>这里显示五线谱</CardTitle>
        <CardDescription>
          之后会用 OSMD 渲染当前乐谱版本导出的 <GlossaryTerm term="MusicXML" />。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex min-h-[400px] flex-col items-center justify-center rounded-xl border border-dashed bg-muted/40 p-8 text-center">
          <FileMusic className="mb-4 h-12 w-12 text-muted-foreground" />
          <div className="text-lg font-semibold">主唱旋律五线谱预览</div>
          <p className="mt-2 max-w-lg text-sm text-muted-foreground">
            这里是谱面渲染占位。系统会先生成乐谱版本，再从该版本导出 MusicXML 用于显示；不会把 MIDI 或 MusicXML 当作原始事实源。
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
