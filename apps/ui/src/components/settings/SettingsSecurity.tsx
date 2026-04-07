import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/hooks/useAuth'

interface SettingsSecurityProps {
  isDarkMode: boolean
}

export function SettingsSecurity({ isDarkMode }: SettingsSecurityProps) {
  const { user } = useAuth()

  return (
    <Card
      className={`p-8 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
      style={{ borderWidth: '0.5px' }}
    >
      <h2
        className={`mb-6 text-[18px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
      >
        Security settings
      </h2>

      <div className="space-y-6">
        {/* Authentication */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Authentication
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p
                  className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  Two-factor authentication
                </p>
                <p
                  className={`text-[12px] ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                >
                  Add an extra layer of security to your account
                </p>
              </div>
              <Switch />
            </div>
            <div
              className={`rounded-lg p-4 ${isDarkMode ? 'bg-gray-700/50' : 'bg-gray-50'}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p
                    className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                  >
                    Current authentication method
                  </p>
                  <p
                    className={`mt-1 text-[12px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                  >
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

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        {/* Session management */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Session management
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p
                  className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  Auto-logout on inactivity
                </p>
                <p
                  className={`text-[12px] ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                >
                  Automatically sign out after 30 minutes of inactivity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <Button
              variant="outline"
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
              style={{ borderWidth: '0.5px' }}
            >
              View active sessions
            </Button>
          </div>
        </div>

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        {/* Access logs */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Access logs
          </h3>
          <p
            className={`mb-4 text-[12px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            View a history of access to your account
          </p>
          <Button
            variant="outline"
            className={
              isDarkMode
                ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                : ''
            }
            style={{ borderWidth: '0.5px' }}
          >
            View access logs
          </Button>
        </div>
      </div>
    </Card>
  )
}
