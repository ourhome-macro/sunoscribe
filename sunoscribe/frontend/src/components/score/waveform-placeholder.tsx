import { AudioLines } from 'lucide-react'

export function WaveformPlaceholder() {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 font-medium">
        <AudioLines className="h-4 w-4" /> Audio / waveform placeholder
      </div>
      <div className="flex h-28 items-center gap-1 rounded-lg bg-muted/40 px-4">
        {Array.from({ length: 64 }).map((_, index) => (
          <div
            key={index}
            className="w-full rounded-full bg-primary/55"
            style={{ height: `${18 + ((index * 17) % 62)}%` }}
          />
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">只作为诊断/对齐辅助占位，不从这里生成 ScoreRevision。</p>
    </div>
  )
}
