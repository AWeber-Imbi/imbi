import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

interface Integration {
  name: string
  description: string
  icon: string
  connected: boolean
  account: string | null
}

const integrations: Integration[] = [
  {
    name: 'GitHub',
    description: 'Connect your GitHub account to link repositories',
    icon: '⑂',
    connected: true,
    account: 'github.ghe.com/gavinr',
  },
  {
    name: 'Sentry',
    description: 'Monitor errors and performance',
    icon: '⚠',
    connected: true,
    account: 'sentry.io/aweber-communications',
  },
  {
    name: 'Slack',
    description: 'Get notifications in Slack channels',
    icon: '💬',
    connected: false,
    account: null,
  },
  {
    name: 'PagerDuty',
    description: 'Integrate incident management',
    icon: '⚡',
    connected: false,
    account: null,
  },
]

export function SettingsIntegrations() {
  return (
    <div className="space-y-4">
      {integrations.map((integration) => (
        <Card
          key={integration.name}
          className={'p-6'}
          style={{ borderWidth: '0.5px' }}
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-lg text-xl ${'bg-secondary'}`}
              >
                {integration.icon}
              </div>
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <h3 className={'text-[14px] font-medium text-primary'}>
                    {integration.name}
                  </h3>
                  {integration.connected && (
                    <Badge
                      variant="outline"
                      className="border-green-200 bg-green-50 text-green-700"
                      style={{ borderWidth: '0.5px' }}
                    >
                      ✓ Connected
                    </Badge>
                  )}
                </div>
                <p className={'mb-2 text-[12px] text-tertiary'}>
                  {integration.description}
                </p>
                {integration.connected && integration.account && (
                  <p className={'font-mono text-[12px] text-secondary'}>
                    {integration.account}
                  </p>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              {integration.connected ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className={''}
                    style={{ borderWidth: '0.5px' }}
                  >
                    Configure
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-red-600 hover:text-red-700"
                    style={{ borderWidth: '0.5px' }}
                  >
                    Disconnect
                  </Button>
                </>
              ) : (
                <Button size="sm">+ Connect</Button>
              )}
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}
