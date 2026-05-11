import { Badge } from '@/components/ui/badge'
import { formatStatus } from '@/lib/copy'

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const copy = formatStatus(status)
  return <Badge variant={copy.tone}>{copy.label}</Badge>
}
