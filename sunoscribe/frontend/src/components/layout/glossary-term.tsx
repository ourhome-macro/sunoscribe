import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { glossaryCopy } from '@/lib/copy'

interface GlossaryTermProps {
  term: keyof typeof glossaryCopy
  variant?: 'inline' | 'badge'
}

export function GlossaryTerm({ term, variant = 'inline' }: GlossaryTermProps) {
  const copy = glossaryCopy[term]
  const content = variant === 'badge' ? <Badge variant="outline">{copy.label}</Badge> : <span className="cursor-help underline decoration-dotted underline-offset-4">{copy.label}</span>

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="font-medium">{term}</div>
        <div className="mt-1 text-xs text-muted-foreground">{copy.description}</div>
      </TooltipContent>
    </Tooltip>
  )
}
