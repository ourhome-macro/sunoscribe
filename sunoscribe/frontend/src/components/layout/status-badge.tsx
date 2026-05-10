import { Badge } from '@/components/ui/badge'

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const value = status ?? 'unknown'
  const variant = value === 'ready' || value === 'available' || value === 'success' || value === 'complete' ? 'success' : value === 'failed' ? 'destructive' : value === 'processing' || value === 'running' || value === 'pending' ? 'warning' : 'secondary'
  return <Badge variant={variant}>{value}</Badge>
}
