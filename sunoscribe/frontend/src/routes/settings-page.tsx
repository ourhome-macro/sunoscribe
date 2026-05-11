import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function SettingsPage() {
  return (
    <div>
      <PageHeader title="设置" description="这里记录工作台必须遵守的扒谱边界。" />
      <Card>
        <CardHeader>
          <CardTitle>工作台规则</CardTitle>
          <CardDescription>SunoScribe 前端只展示和修改乐谱版本，不绕过后端流水线。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>不展示后端内部存储路径。</p>
          <p>不请求完整的人声音高轨迹，只读取摘要和诊断结果。</p>
          <p><GlossaryTerm term="MIDI" />、<GlossaryTerm term="MusicXML" /> 和前端显示数据都是从当前 <GlossaryTerm term="ScoreRevision" /> 导出的文件。</p>
          <p>任何音符修正都必须由后端校验，并生成新的乐谱版本。</p>
        </CardContent>
      </Card>
    </div>
  )
}
