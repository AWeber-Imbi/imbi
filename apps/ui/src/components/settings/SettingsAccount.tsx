import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/hooks/useAuth'

interface SettingsAccountProps {
  isDarkMode: boolean
}

export function SettingsAccount({ isDarkMode }: SettingsAccountProps) {
  const { user } = useAuth()

  return (
    <Card
      className={`p-8 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
      style={{ borderWidth: '0.5px' }}
    >
      <h2
        className={`mb-6 text-[18px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
      >
        Account settings
      </h2>

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <Label
              htmlFor="display-name"
              className={isDarkMode ? 'text-gray-300' : ''}
            >
              Display name
            </Label>
            <Input
              id="display-name"
              defaultValue={user?.display_name || ''}
              className={`mt-2 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : ''}`}
              style={{ borderWidth: '0.5px' }}
            />
          </div>
          <div>
            <Label
              htmlFor="email"
              className={isDarkMode ? 'text-gray-300' : ''}
            >
              Email address
            </Label>
            <Input
              id="email"
              type="email"
              defaultValue={user?.email || ''}
              disabled
              className={`mt-2 ${isDarkMode ? 'border-gray-600 bg-gray-700/50 text-gray-400' : ''}`}
              style={{ borderWidth: '0.5px' }}
            />
          </div>
        </div>

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Preferences
          </h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p
                  className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  Email notifications
                </p>
                <p
                  className={`text-[12px] ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                >
                  Receive email updates about your projects
                </p>
              </div>
              <Switch defaultChecked />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p
                  className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
                >
                  Deployment summaries
                </p>
                <p
                  className={`text-[12px] ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                >
                  Daily digest of deployment activity
                </p>
              </div>
              <Switch defaultChecked />
            </div>
          </div>
        </div>

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            className={
              isDarkMode
                ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                : ''
            }
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
