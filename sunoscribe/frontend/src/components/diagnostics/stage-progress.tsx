import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { StageProgressItem } from '@/types/project'

const iconMap = {
  pending: Circle,
  running: Loader2,
  success: CheckCircle2,
  failed: XCircle,
}

export function StageProgress({ stages }: { stages: StageProgressItem[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {stages.map((stage) => {
        const Icon = iconMap[stage.status]
        return (
          <div key={stage.stage} className="rounded-xl border bg-card p-4">
            <div className="flex items-center gap-2">
              <Icon
                className={cn(
                  'h-4 w-4',
                  stage.status === 'success' && 'text-emerald-500',
                  stage.status === 'failed' && 'text-destructive',
                  stage.status === 'running' && 'animate-spin text-amber-500',
                  stage.status === 'pending' && 'text-muted-foreground',
                )}
              />
              <div className="font-medium">{stage.stage}</div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{stage.summary ?? stage.status}</p>
          </div>
        )
      })}
    </div>
  )
}
