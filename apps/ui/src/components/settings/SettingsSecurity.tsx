import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/hooks/useAuth'

export function SettingsSecurity() {
  const { user } = useAuth()

  return (
    <Card className={'p-8'} style={{ borderWidth: '0.5px' }}>
      <h2 className={'mb-6 text-[18px] font-medium text-primary'}>
        Security settings
      </h2>

      <div className="space-y-6">
        {/* Authentication */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Authentication
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className={'text-[13.5px] text-primary'}>
                  Two-factor authentication
                </p>
                <p className={'text-[12px] text-tertiary'}>
                  Add an extra layer of security to your account
                </p>
              </div>
              <Switch />
            </div>
            <div className={'bg-secondary/50 rounded-lg p-4'}>
              <div className="flex items-center justify-between">
                <div>
                  <p className={'text-[13.5px] text-primary'}>
                    Current authentication method
                  </p>
                  <p className={'mt-1 text-[12px] text-tertiary'}>
                    Google OAuth ({user?.email})
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className="border-green-200 bg-green-50 text-green-700"
                  style={{ borderWidth: '0.5px' }}
                >
                  Active
                </Badge>
              </div>
            </div>
          </div>
        </div>

        <Separator />

        {/* Session management */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Session management
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className={'text-[13.5px] text-primary'}>
                  Auto-logout on inactivity
                </p>
                <p className={'text-[12px] text-tertiary'}>
                  Automatically sign out after 30 minutes of inactivity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <Button
              variant="outline"
              className={''}
              style={{ borderWidth: '0.5px' }}
            >
              View active sessions
            </Button>
          </div>
        </div>

        <Separator />

        {/* Access logs */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Access logs
          </h3>
          <p className={'mb-4 text-[12px] text-tertiary'}>
            View a history of access to your account
          </p>
          <Button
            variant="outline"
            className={''}
            style={{ borderWidth: '0.5px' }}
          >
            View access logs
          </Button>
        </div>
      </div>
    </Card>
  )
}
