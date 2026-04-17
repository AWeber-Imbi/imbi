import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'

export function SettingsNotifications() {
  return (
    <Card className={'p-8'} style={{ borderWidth: '0.5px' }}>
      <h2 className={'mb-6 text-[18px] font-medium text-primary'}>
        Notification preferences
      </h2>

      <div className="space-y-6">
        {/* Deployment notifications */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Deployment notifications
          </h3>
          <div className="space-y-4">
            <ToggleRow
              label="Successful deployments"
              description="Get notified when deployments succeed"
              defaultChecked
            />
            <ToggleRow
              label="Failed deployments"
              description="Get notified when deployments fail"
              defaultChecked
            />
            <ToggleRow
              label="Production deployments only"
              description="Only notify for production environment"
            />
          </div>
        </div>

        <Separator />

        {/* Health & monitoring */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Health & monitoring
          </h3>
          <div className="space-y-4">
            <ToggleRow
              label="Health score changes"
              description="Alert when project health drops below threshold"
              defaultChecked
            />
            <ToggleRow
              label="Configuration changes"
              description="Notify when project configurations are updated"
              defaultChecked
            />
          </div>
        </div>

        <Separator />

        {/* Operations log */}
        <div>
          <h3 className={'mb-4 text-[16px] font-medium text-primary'}>
            Operations log
          </h3>
          <div className="space-y-4">
            <ToggleRow
              label="New operations entries"
              description="Get notified of new operations log entries"
            />
          </div>
        </div>

        <Separator />

        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            className={''}
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
  label,
  description,
  defaultChecked,
}: {
  label: string
  description: string
  defaultChecked?: boolean
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className={'text-[13.5px] text-primary'}>{label}</p>
        <p className={'text-[12px] text-tertiary'}>{description}</p>
      </div>
      <Switch defaultChecked={defaultChecked} />
    </div>
  )
}
