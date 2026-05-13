import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useAuth } from '@/hooks/useAuth'

export function SettingsSecurity() {
  const { user } = useAuth()

  return (
    <Card className="p-8" style={{ borderWidth: '0.5px' }}>
      <h2 className="text-primary mb-6 text-[18px] font-medium">
        Security settings
      </h2>

      <div className="space-y-6">
        {/* Authentication */}
        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Authentication
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-primary text-[13.5px]">
                  Two-factor authentication
                </p>
                <p className="text-tertiary text-[12px]">
                  Add an extra layer of security to your account
                </p>
              </div>
              <Switch />
            </div>
            <div className="bg-secondary/50 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-primary text-[13.5px]">
                    Current authentication method
                  </p>
                  <p className="text-tertiary mt-1 text-[12px]">
                    Google OAuth ({user?.email})
                  </p>
                </div>
                <Badge
                  className="border-green-200 bg-green-50 text-green-700"
                  style={{ borderWidth: '0.5px' }}
                  variant="outline"
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
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Session management
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-primary text-[13.5px]">
                  Auto-logout on inactivity
                </p>
                <p className="text-tertiary text-[12px]">
                  Automatically sign out after 30 minutes of inactivity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <Button
              className=""
              style={{ borderWidth: '0.5px' }}
              variant="outline"
            >
              View active sessions
            </Button>
          </div>
        </div>

        <Separator />

        {/* Access logs */}
        <div>
          <h3 className="text-primary mb-4 text-[16px] font-medium">
            Access logs
          </h3>
          <p className="text-tertiary mb-4 text-[12px]">
            View a history of access to your account
          </p>
          <Button
            className=""
            style={{ borderWidth: '0.5px' }}
            variant="outline"
          >
            View access logs
          </Button>
        </div>
      </div>
    </Card>
  )
}
