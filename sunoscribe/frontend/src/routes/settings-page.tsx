import { PageHeader } from '@/components/layout/page-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" description="前端工作台占位设置页。" />
      <Card>
        <CardHeader>
          <CardTitle>Workbench Guardrails</CardTitle>
          <CardDescription>SunoScribe 前端不越过 typed artifacts 和 ScoreRevision 边界。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>不展示后端内部存储路径。</p>
          <p>不请求完整 F0Track summary 之外的数据。</p>
          <p>不把 MIDI / MusicXML / score view JSON 当作事实源。</p>
          <p>Patch 操作应经过后端 validator 并生成新 revision。</p>
        </CardContent>
      </Card>
    </div>
  )
}
