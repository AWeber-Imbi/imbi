import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/hooks/useAuth'

export function SettingsAccount() {
  const { user } = useAuth()

  return (
    <Card className={'p-8'} style={{ borderWidth: '0.5px' }}>
      <h2 className={'mb-6 text-[18px] font-medium text-primary'}>
        Account settings
      </h2>

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <Label htmlFor="display-name">Display name</Label>
            <Input
              id="display-name"
              defaultValue={user?.display_name || ''}
              className={'mt-2'}
              style={{ borderWidth: '0.5px' }}
            />
          </div>
          <div>
            <Label htmlFor="email">Email address</Label>
            <Input
              id="email"
              type="email"
              defaultValue={user?.email || ''}
              disabled
              className={'mt-2'}
              style={{ borderWidth: '0.5px' }}
            />
          </div>
        </div>

        <Separator />

        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Preferences
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className={'text-[13.5px] text-primary'}>
                  Email notifications
                </p>
                <p className={'text-[12px] text-tertiary'}>
                  Receive email updates about your projects
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className={'text-[13.5px] text-primary'}>
                  Deployment summaries
                </p>
                <p className={'text-[12px] text-tertiary'}>
                  Daily digest of deployment activity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
          </div>
        </div>

        <Separator />

        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            className={''}
            style={{ borderWidth: '0.5px' }}
          >
            Cancel
          </Button>
          <Button>Save changes</Button>
        </div>
      </div>
    </Card>
  )
}
