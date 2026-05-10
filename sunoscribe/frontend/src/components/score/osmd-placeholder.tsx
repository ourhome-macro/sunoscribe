import { FileMusic } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function OsmdPlaceholder() {
  return (
    <Card className="h-full min-h-[520px]">
      <CardHeader>
        <CardTitle>OSMD MusicXML 渲染区</CardTitle>
        <CardDescription>后续加载由选定 ScoreRevision 派生的 MusicXML artifact。</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex min-h-[400px] flex-col items-center justify-center rounded-xl border border-dashed bg-muted/40 p-8 text-center">
          <FileMusic className="mb-4 h-12 w-12 text-muted-foreground" />
          <div className="text-lg font-semibold">ScoreIR → ScoreRevision → MusicXML</div>
          <p className="mt-2 max-w-lg text-sm text-muted-foreground">
            这里先保留谱面渲染封装位。UI 不直接解析 MIDI，也不把 MusicXML 当事实源，只展示 revision 派生结果。
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
