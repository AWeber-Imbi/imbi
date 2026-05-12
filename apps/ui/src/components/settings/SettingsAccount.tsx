import { useState } from 'react'

import { Card } from '@/components/ui/card'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/hooks/useAuth'

// NOTE: The backend currently exposes no self-update endpoint for the
// authenticated user, and `email_notifications` / `deployment_summaries`
// do not exist on the User schema. Inline commits are local-only until a
// `/users/me` PATCH endpoint (or equivalent) lands. UI behavior matches
// the rest of the app's inline-edit cards (commit on blur / on toggle).
export function SettingsAccount() {
  const { user } = useAuth()
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [emailNotifications, setEmailNotifications] = useState(true)

  return (
    <Card className="p-8" style={{ borderWidth: '0.5px' }}>
      <h2 className="mb-6 text-[18px] font-medium text-primary">
        Account settings
      </h2>

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <Label>Display name</Label>
            <div className="mt-2 text-[13.5px] text-primary">
              <InlineText
                onCommit={(next) => setDisplayName(next ?? '')}
                placeholder="Add display name"
                value={displayName}
              />
            </div>
          </div>
          <div>
            <Label>Email address</Label>
            <p className="mt-2 text-[13.5px] text-tertiary">
              {user?.email || '—'}
            </p>
          </div>
        </div>

        <Separator />

        <div>
          <h3 className="mb-4 text-[16px] font-medium text-primary">
            Preferences
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13.5px] text-primary">
                  Email notifications
                </p>
                <p className="text-[12px] text-tertiary">
                  Receive email updates about your projects
                </p>
              </div>
              <Switch
                checked={emailNotifications}
                onCheckedChange={setEmailNotifications}
              />
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}
