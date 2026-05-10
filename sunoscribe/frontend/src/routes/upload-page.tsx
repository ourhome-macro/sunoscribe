import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { StageProgress } from '@/components/diagnostics/stage-progress'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { apiClient } from '@/lib/api/client'
import type { StageProgressItem } from '@/types/project'

const uploadStages: StageProgressItem[] = [
  { stage: 'Media Ingest', status: 'pending' },
  { stage: 'StemService', status: 'pending' },
  { stage: 'F0Track', status: 'pending' },
  { stage: 'PitchContourIR', status: 'pending' },
  { stage: 'MelodySelector', status: 'pending' },
  { stage: 'DP Quantizer', status: 'pending' },
  { stage: 'ScoreIR', status: 'pending' },
  { stage: 'Exports', status: 'pending' },
]

export function UploadPage() {
  const [name, setName] = useState('')
  const [mediaKind, setMediaKind] = useState<'audio' | 'video'>('audio')
  const [file, setFile] = useState<File | null>(null)
  const [started, setStarted] = useState(false)

  const stages = useMemo(
    () => uploadStages.map((stage, index) => ({ ...stage, status: started && index === 0 ? 'running' : stage.status } as StageProgressItem)),
    [started],
  )

  const mutation = useMutation({
    mutationFn: () => apiClient.createProject({ name, media_kind: mediaKind, file }),
    onSuccess: (result) => {
      setStarted(true)
      toast.success('分析任务已创建', { description: `${result.project_id} · ${result.task_id}` })
    },
  })

  return (
    <div>
      <PageHeader title="Upload / Create Project" description="上传音频或视频，启动 lead-vocal transcription pipeline。" />
      <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>创建项目</CardTitle>
            <CardDescription>上传文件只创建 source media；后续阶段从 typed artifacts 继续。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-name">项目名称</Label>
              <Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：Mojito lead vocal" />
            </div>
            <div className="space-y-2">
              <Label>媒体类型</Label>
              <Select
                value={mediaKind}
                onChange={(event) => setMediaKind(event.target.value as 'audio' | 'video')}
                options={[
                  { label: '音频', value: 'audio' },
                  { label: '视频', value: 'video' },
                ]}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="media-file">音频/视频文件</Label>
              <Input id="media-file" type="file" accept="audio/*,video/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <p className="text-xs text-muted-foreground">MVP 只展示上传入口；生产链路必须显式失败而非静默 fallback。</p>
            </div>
            <Button className="w-full" disabled={!name || !file || mutation.isPending} onClick={() => mutation.mutate()}>
              开始分析
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Stage progress</CardTitle>
            <CardDescription>Media Ingest → StemService → F0Track → ScoreIR → Exports。</CardDescription>
          </CardHeader>
          <CardContent>
            <StageProgress stages={stages} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
