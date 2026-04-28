import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

interface Integration {
  account: null | string
  connected: boolean
  description: string
  icon: string
  name: string
}

const integrations: Integration[] = [
  {
    account: 'github.ghe.com/gavinr',
    connected: true,
    description: 'Connect your GitHub account to link repositories',
    icon: '⑂',
    name: 'GitHub',
  },
  {
    account: 'sentry.io/aweber-communications',
    connected: true,
    description: 'Monitor errors and performance',
    icon: '⚠',
    name: 'Sentry',
  },
  {
    account: null,
    connected: false,
    description: 'Get notifications in Slack channels',
    icon: '💬',
    name: 'Slack',
  },
  {
    account: null,
    connected: false,
    description: 'Integrate incident management',
    icon: '⚡',
    name: 'PagerDuty',
  },
]

export function SettingsIntegrations() {
  return (
    <div className="space-y-4">
      {integrations.map((integration) => (
        <Card
          className="p-6"
          key={integration.name}
          style={{ borderWidth: '0.5px' }}
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-secondary text-xl">
                {integration.icon}
              </div>
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <h3 className="text-[14px] font-medium text-primary">
                    {integration.name}
                  </h3>
                  {integration.connected && (
                    <Badge
                      className="border-green-200 bg-green-50 text-green-700"
                      style={{ borderWidth: '0.5px' }}
                      variant="outline"
                    >
                      ✓ Connected
                    </Badge>
                  )}
                </div>
                <p className="mb-2 text-[12px] text-tertiary">
                  {integration.description}
                </p>
                {integration.connected && integration.account && (
                  <p className="font-mono text-[12px] text-secondary">
                    {integration.account}
                  </p>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              {integration.connected ? (
                <>
                  <Button
                    className=""
                    size="sm"
                    style={{ borderWidth: '0.5px' }}
                    variant="outline"
                  >
                    Configure
                  </Button>
                  <Button
                    className="text-red-600 hover:text-red-700"
                    size="sm"
                    style={{ borderWidth: '0.5px' }}
                    variant="outline"
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
