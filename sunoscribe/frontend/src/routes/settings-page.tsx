import { useState } from 'react'
import { toast } from 'sonner'

import { GlossaryTerm } from '@/components/layout/glossary-term'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { accessTokenStorageKey } from '@/lib/api/client'

export function SettingsPage() {
  const [token, setToken] = useState(() => window.localStorage.getItem(accessTokenStorageKey) ?? '')

  const apiMode = import.meta.env.VITE_API_MODE ?? 'backend'
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api via Vite proxy'

  return (
    <div className="space-y-6">
      <PageHeader title="??" description="???????? API ????????????????????" />

      <Card>
        <CardHeader>
          <CardTitle>?? API ??</CardTitle>
          <CardDescription>
            ?????<span className="font-mono">{apiMode}</span>?API ???<span className="font-mono">{apiBaseUrl}</span>?
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="api-token">Bearer token</Label>
            <Input
              id="api-token"
              type="password"
              value={token}
              placeholder="?????? access_token???? VITE_API_ACCESS_TOKEN"
              onChange={(event) => setToken(event.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button
              onClick={() => {
                window.localStorage.setItem(accessTokenStorageKey, token.trim())
                toast.success('API token ?????????')
              }}
            >
              ?? token
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                window.localStorage.removeItem(accessTokenStorageKey)
                setToken('')
                toast.success('API token ???')
              }}
            >
              ??
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            ????????????????????? `.env.local` ?? `VITE_API_MODE=mock`?
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>?????</CardTitle>
          <CardDescription>SunoScribe ??????????????????????</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>????????????</p>
          <p>????????????????????????</p>
          <p>
            <GlossaryTerm term="MIDI" />?<GlossaryTerm term="MusicXML" /> ??????????? <GlossaryTerm term="ScoreRevision" /> ???
          </p>
          <p>?????????????????????????</p>
        </CardContent>
      </Card>
    </div>
  )
}
