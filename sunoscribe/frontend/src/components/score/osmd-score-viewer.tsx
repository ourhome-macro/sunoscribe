import { useEffect, useRef, useState } from 'react'
import { Music2 } from 'lucide-react'
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function OsmdScoreViewer({ musicXml, isLoading, error }: { musicXml: string | null | undefined; isLoading?: boolean; error?: string | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function renderScore() {
      if (!containerRef.current || !musicXml) return
      setRenderError(null)
      containerRef.current.innerHTML = ''
      const osmd = new OpenSheetMusicDisplay(containerRef.current, {
        autoResize: true,
        drawTitle: false,
        drawComposer: false,
      })
      osmdRef.current = osmd
      try {
        await osmd.load(musicXml)
        if (cancelled) return
        osmd.render()
      } catch (caught) {
        if (cancelled) return
        setRenderError(caught instanceof Error ? caught.message : 'MusicXML 渲染失败。')
        containerRef.current.innerHTML = ''
      }
    }

    void renderScore()

    return () => {
      cancelled = true
    }
  }, [musicXml])

  const message = error ?? renderError

  return (
    <Card className="min-h-[520px] overflow-hidden">
      <CardHeader>
        <CardTitle>五线谱预览</CardTitle>
        <CardDescription>仅渲染选定 ScoreRevision 派生出的 MusicXML；MusicXML 不是可编辑事实源。</CardDescription>
      </CardHeader>
      <CardContent>
        {!musicXml || isLoading || message ? (
          <div className="flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed bg-muted/30 p-8 text-center">
            <Music2 className="h-10 w-10 text-muted-foreground" />
            <div className="mt-4 text-lg font-semibold">{isLoading ? '正在加载 MusicXML' : message ? '谱面暂不可用' : '等待选定乐谱版本'}</div>
            <p className="mt-2 max-w-lg text-sm text-muted-foreground">
              {message ?? '生成并导出 MusicXML 后，OSMD 会在这里渲染选定 revision 的谱面。'}
            </p>
          </div>
        ) : null}
        <div ref={containerRef} className={musicXml && !isLoading && !message ? 'min-h-[360px] overflow-auto rounded-xl border bg-white p-4' : 'hidden'} />
      </CardContent>
    </Card>
  )
}

