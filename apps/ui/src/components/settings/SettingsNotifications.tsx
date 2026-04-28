import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'

export function SettingsNotifications() {
  return (
    <Card className="p-8" style={{ borderWidth: '0.5px' }}>
      <h2 className="mb-6 text-[18px] font-medium text-primary">
        Notification preferences
      </h2>

      <div className="space-y-6">
        {/* Deployment notifications */}
        <div>
          <h3 className="mb-4 text-[16px] font-medium text-primary">
            Deployment notifications
          </h3>
          <div className="space-y-4">
            <ToggleRow
              defaultChecked
              description="Get notified when deployments succeed"
              label="Successful deployments"
            />
            <ToggleRow
              defaultChecked
              description="Get notified when deployments fail"
              label="Failed deployments"
            />
            <ToggleRow
              description="Only notify for production environment"
              label="Production deployments only"
            />
          </div>
        </div>

        <Separator />

        {/* Health & monitoring */}
        <div>
          <h3 className="mb-4 text-[16px] font-medium text-primary">
            Health & monitoring
          </h3>
          <div className="space-y-4">
            <ToggleRow
              defaultChecked
              description="Alert when project health drops below threshold"
              label="Health score changes"
            />
            <ToggleRow
              defaultChecked
              description="Notify when project configurations are updated"
              label="Configuration changes"
            />
          </div>
        </div>

        <Separator />

        {/* Operations log */}
        <div>
          <h3 className="mb-4 text-[16px] font-medium text-primary">
            Operations log
          </h3>
          <div className="space-y-4">
            <ToggleRow
              description="Get notified of new operations log entries"
              label="New operations entries"
            />
          </div>
        </div>

        <Separator />

        <div className="flex justify-end gap-3">
          <Button
            className=""
            style={{ borderWidth: '0.5px' }}
            variant="outline"
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
  defaultChecked,
  description,
  label,
}: {
  defaultChecked?: boolean
  description: string
  label: string
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-[13.5px] text-primary">{label}</p>
        <p className="text-[12px] text-tertiary">{description}</p>
      </div>
      <Switch defaultChecked={defaultChecked} />
    </div>
  )
}
