import { AudioLines } from 'lucide-react'

export function WaveformPlaceholder() {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 font-medium">
        <AudioLines className="h-4 w-4" /> 音频波形占位
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
      <p className="mt-2 text-xs text-muted-foreground">这里以后用于辅助听辨和对齐；乐谱版本不会从波形直接生成或修改。</p>
    </div>
  )
}
