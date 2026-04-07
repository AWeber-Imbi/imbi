import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'

interface SettingsNotificationsProps {
  isDarkMode: boolean
}

export function SettingsNotifications({
  isDarkMode,
}: SettingsNotificationsProps) {
  return (
    <Card
      className={`p-8 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
      style={{ borderWidth: '0.5px' }}
    >
      <h2
        className={`mb-6 text-[18px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
      >
        Notification preferences
      </h2>

      <div className="space-y-6">
        {/* Deployment notifications */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Deployment notifications
          </h3>
          <div className="space-y-4">
            <ToggleRow
              isDarkMode={isDarkMode}
              label="Successful deployments"
              description="Get notified when deployments succeed"
              defaultChecked
            />
            <ToggleRow
              isDarkMode={isDarkMode}
              label="Failed deployments"
              description="Get notified when deployments fail"
              defaultChecked
            />
            <ToggleRow
              isDarkMode={isDarkMode}
              label="Production deployments only"
              description="Only notify for production environment"
            />
          </div>
        </div>

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        {/* Health & monitoring */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Health & monitoring
          </h3>
          <div className="space-y-4">
            <ToggleRow
              isDarkMode={isDarkMode}
              label="Health score changes"
              description="Alert when project health drops below threshold"
              defaultChecked
            />
            <ToggleRow
              isDarkMode={isDarkMode}
              label="Configuration changes"
              description="Notify when project configurations are updated"
              defaultChecked
            />
          </div>
        </div>

        <Separator className={isDarkMode ? 'bg-gray-700' : ''} />

        {/* Operations log */}
        <div>
          <h3
            className={`mb-4 text-[16px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
          >
            Operations log
          </h3>
          <div className="space-y-4">
            <ToggleRow
              isDarkMode={isDarkMode}
              label="New operations entries"
              description="Get notified of new operations log entries"
            />
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
            Reset to defaults
          </Button>
          <Button>Save preferences</Button>
        </div>
      </div>
    </Card>
  )
}

function ToggleRow({
  isDarkMode,
  label,
  description,
  defaultChecked,
}: {
  isDarkMode: boolean
  label: string
  description: string
  defaultChecked?: boolean
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p
          className={`text-[13.5px] ${isDarkMode ? 'text-gray-200' : 'text-gray-900'}`}
        >
          {label}
        </p>
        <p
          className={`text-[12px] ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
        >
          {description}
        </p>
      </div>
      <Switch defaultChecked={defaultChecked} />
    </div>
  )
}
