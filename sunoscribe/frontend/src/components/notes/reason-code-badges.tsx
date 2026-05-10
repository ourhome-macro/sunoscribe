import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { describeReasonCode } from '@/lib/reason-codes'

export function ReasonCodeBadges({ codes }: { codes: string[] }) {
  if (!codes.length) return <span className="text-muted-foreground">—</span>

  return (
    <div className="flex flex-wrap gap-1.5">
      {codes.map((code) => {
        const description = describeReasonCode(code)
        return (
          <Tooltip key={code}>
            <TooltipTrigger asChild>
              <span>
                <Badge variant="outline" className="cursor-help">
                  {description.label}
                </Badge>
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{description.tooltip}</TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}
