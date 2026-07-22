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
      <h2 className="text-primary mb-6 text-[18px] font-medium">
        Account settings
      </h2>

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <Label>Display name</Label>
            <div className="text-primary mt-2 text-[13.5px]">
              <InlineText
                onCommit={(next) => setDisplayName(next ?? '')}
                placeholder="Add display name"
                value={displayName}
              />
            </div>
          </div>
          <div>
            <Label>Email address</Label>
            <p className="text-tertiary mt-2 text-[13.5px]">
              {user?.email || '—'}
            </p>
          </div>
        </div>

        <Separator />

        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Preferences
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-primary text-[13.5px]">
                  Email notifications
                </p>
                <p className="text-tertiary text-[12px]">
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
